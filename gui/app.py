"""Tkinter-интерфейс мини-CRM: клиенты, сделки, задачи и выгрузка отчётов в Google Drive."""

from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
import webbrowser
from datetime import date
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from google_integration import load_config
from google_integration.config import PROJECT_ROOT, read_gui_settings, save_gui_settings
from gui.api_client import APIError, CRMClient
from gui.reports import (
    CLIENT_STATUS_RU,
    DEAL_STATUS_RU,
    REPORT_TITLES,
    ReportResult,
    export_report,
    local_path,
)

PAGE = 200
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NO_LINK = "— не выбрано —"


# ======================= утилиты =======================
def install_layout_independent_shortcuts(root: tk.Misc) -> None:
    """Ctrl+C/V/X/A по коду клавиши: в Tkinter они не работают при русской раскладке."""
    actions = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>", 65: "<<SelectAll>>"}  # Windows keycodes

    def handler(event: tk.Event) -> str | None:
        if event.keysym.lower() in ("v", "c", "x", "a"):
            return None  # латинская раскладка — стандартная обработка
        virtual = actions.get(event.keycode)
        if virtual:
            event.widget.event_generate(virtual)
            return "break"
        return None

    for cls in ("Entry", "TEntry", "TCombobox", "Text"):
        root.bind_class(cls, "<Control-KeyPress>", handler, add="+")


def valid_date(value: str) -> bool:
    if not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def id_from_choice(value: str) -> int | None:
    """«12 — Иванов Иван» -> 12; «— не выбрано —» -> None."""
    head = value.split("—", 1)[0].strip()
    return int(head) if head.isdigit() else None


class BackgroundRunner:
    """Выполняет функцию в потоке и возвращает результат в главный поток через очередь."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self._poll()

    def _poll(self) -> None:
        try:
            while True:
                callback, args = self.q.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def post(self, callback: Callable, *args) -> None:
        self.q.put((callback, args))

    def run(self, func: Callable, on_done: Callable, on_error: Callable) -> None:
        def worker() -> None:
            try:
                result = func()
            except Exception as exc:  # noqa: BLE001 — показываем пользователю любую ошибку
                self.post(on_error, exc)
            else:
                self.post(on_done, result)

        threading.Thread(target=worker, daemon=True).start()


# ======================= диалоги =======================
class FormDialog(tk.Toplevel):
    """Базовая модальная форма: поля в сетке, «Сохранить» / «Отмена»."""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result: dict | None = None
        self.body = ttk.Frame(self, padding=16)
        self.body.grid(sticky="nsew")
        self.body.columnconfigure(1, weight=1)
        self._row = 0

    def add(self, label: str, widget: tk.Widget) -> tk.Widget:
        ttk.Label(self.body, text=label).grid(row=self._row, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=self._row, column=1, sticky="ew", pady=4)
        self._row += 1
        return widget

    def finish(self) -> None:
        buttons = ttk.Frame(self.body)
        buttons.grid(row=self._row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Сохранить", command=self._submit).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self._submit())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.wait_window()

    def _submit(self) -> None:
        try:
            data = self.collect()
        except ValueError as exc:
            messagebox.showwarning("Проверьте данные", str(exc), parent=self)
            return
        self.result = data
        self.destroy()

    def collect(self) -> dict:
        raise NotImplementedError


class ClientForm(FormDialog):
    def __init__(self, parent: tk.Misc, client: dict | None = None) -> None:
        super().__init__(parent, "Клиент: изменение" if client else "Клиент: новый")
        c = client or {}
        self.name = self.add("ФИО *", ttk.Entry(self.body, width=44))
        self.company = self.add("Компания", ttk.Entry(self.body))
        self.email = self.add("Email", ttk.Entry(self.body))
        self.phone = self.add("Телефон", ttk.Entry(self.body))
        self.status = self.add(
            "Статус", ttk.Combobox(self.body, state="readonly", values=list(CLIENT_STATUS_RU.values()))
        )
        self.notes = self.add("Заметки", tk.Text(self.body, height=4, width=44, wrap="word"))
        for entry, key in ((self.name, "full_name"), (self.company, "company"),
                           (self.email, "email"), (self.phone, "phone")):
            entry.insert(0, c.get(key) or "")
        self.status.set(CLIENT_STATUS_RU.get(c.get("status", "active")))
        self.notes.insert("1.0", c.get("notes") or "")
        self.name.focus_set()
        self.finish()

    def collect(self) -> dict:
        name = self.name.get().strip()
        if not name:
            raise ValueError("Укажите ФИО клиента.")
        status = {v: k for k, v in CLIENT_STATUS_RU.items()}[self.status.get()]
        return {
            "full_name": name,
            "company": self.company.get().strip() or None,
            "email": self.email.get().strip() or None,
            "phone": self.phone.get().strip() or None,
            "status": status,
            "notes": self.notes.get("1.0", "end").strip() or None,
        }


class DealForm(FormDialog):
    def __init__(self, parent: tk.Misc, client_choices: list[str], deal: dict | None = None) -> None:
        super().__init__(parent, "Сделка: изменение" if deal else "Сделка: новая")
        d = deal or {}
        self.title_e = self.add("Название *", ttk.Entry(self.body, width=44))
        self.client = self.add(
            "Клиент", ttk.Combobox(self.body, values=[NO_LINK, *client_choices], height=20)
        )
        self.amount = self.add("Сумма, ₽", ttk.Entry(self.body))
        self.status = self.add(
            "Статус", ttk.Combobox(self.body, state="readonly", values=list(DEAL_STATUS_RU.values()))
        )
        self.close_date = self.add("Дата закрытия", ttk.Entry(self.body))
        ttk.Label(self.body, text="формат ГГГГ-ММ-ДД, можно оставить пустым",
                  foreground="gray").grid(row=self._row, column=1, sticky="w")
        self._row += 1

        self.title_e.insert(0, d.get("title") or "")
        if d.get("client_id"):
            match = next((c for c in client_choices if id_from_choice(c) == d["client_id"]), None)
            self.client.set(match or f"{d['client_id']} — {d.get('client_name') or ''}")
        else:
            self.client.set(NO_LINK)
        self.amount.insert(0, f"{d['amount']:.2f}" if d.get("amount") is not None else "")
        self.status.set(DEAL_STATUS_RU.get(d.get("status", "new")))
        self.close_date.insert(0, d.get("close_date") or "")
        self.title_e.focus_set()
        self.finish()

    def collect(self) -> dict:
        title = self.title_e.get().strip()
        if not title:
            raise ValueError("Укажите название сделки.")
        raw = self.amount.get().replace(" ", "").replace(" ", "").replace(",", ".") or "0"
        try:
            amount = float(raw)
        except ValueError:
            raise ValueError("Сумма должна быть числом, например 150000 или 150000,50.") from None
        if amount < 0:
            raise ValueError("Сумма не может быть отрицательной.")
        close = self.close_date.get().strip()
        if close and not valid_date(close):
            raise ValueError("Дата закрытия — в формате ГГГГ-ММ-ДД, например 2026-12-31.")
        choice = self.client.get().strip()
        client_id = id_from_choice(choice)
        if choice and choice != NO_LINK and client_id is None:
            raise ValueError("Выберите клиента из списка («ID — Имя») или «не выбрано».")
        return {
            "title": title,
            "client_id": client_id,
            "amount": round(amount, 2),
            "status": {v: k for k, v in DEAL_STATUS_RU.items()}[self.status.get()],
            "close_date": close or None,
        }


class TaskForm(FormDialog):
    def __init__(self, parent: tk.Misc, client_choices: list[str], deal_choices: list[str],
                 task: dict | None = None) -> None:
        super().__init__(parent, "Задача: изменение" if task else "Задача: новая")
        t = task or {}
        self.title_e = self.add("Задача *", ttk.Entry(self.body, width=44))
        self.desc = self.add("Описание", tk.Text(self.body, height=4, width=44, wrap="word"))
        self.due = self.add("Срок (ГГГГ-ММ-ДД)", ttk.Entry(self.body))
        self.client = self.add("Клиент", ttk.Combobox(self.body, values=[NO_LINK, *client_choices], height=20))
        self.deal = self.add("Сделка", ttk.Combobox(self.body, values=[NO_LINK, *deal_choices], height=20))
        self.done = tk.BooleanVar(value=bool(t.get("is_done")))
        self.add("", ttk.Checkbutton(self.body, text="Выполнена", variable=self.done))

        self.title_e.insert(0, t.get("title") or "")
        self.desc.insert("1.0", t.get("description") or "")
        self.due.insert(0, t.get("due_date") or "")
        for box, key, choices in ((self.client, "client_id", client_choices),
                                  (self.deal, "deal_id", deal_choices)):
            ref = t.get(key)
            box.set(next((c for c in choices if id_from_choice(c) == ref), str(ref)) if ref else NO_LINK)
        self.title_e.focus_set()
        self.finish()

    def collect(self) -> dict:
        title = self.title_e.get().strip()
        if not title:
            raise ValueError("Укажите название задачи.")
        due = self.due.get().strip()
        if due and not valid_date(due):
            raise ValueError("Срок — в формате ГГГГ-ММ-ДД, например 2026-12-01.")
        return {
            "title": title,
            "description": self.desc.get("1.0", "end").strip() or None,
            "due_date": due or None,
            "is_done": self.done.get(),
            "client_id": id_from_choice(self.client.get()),
            "deal_id": id_from_choice(self.deal.get()),
        }


class GoogleSettingsDialog(tk.Toplevel):
    """Окно «Настройки Google»: пути к JSON, ID папки, индикатор режима."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("Настройки Google")
        self.transient(parent)
        self.resizable(False, False)
        cfg = load_config()
        saved = read_gui_settings()

        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)

        mode_text = ("Эмуляция (mock): отчёты сохраняются в папку mock_drive"
                     if cfg.is_mock else "Настоящий Google Drive (real)")
        ttk.Label(frame, text="Режим:").grid(row=0, column=0, sticky="w")
        tk.Label(frame, text=f"  {mode_text}  ", fg="white",
                 bg="#2e7d32" if cfg.is_mock else "#1565c0").grid(row=0, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Label(frame, text="Режим меняется переменной GOOGLE_MODE в файле .env",
                  foreground="gray").grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 10))

        self.secret = tk.StringVar(value=saved.get("client_secret_file") or str(cfg.client_secret_file or ""))
        self.service = tk.StringVar(value=saved.get("service_account_file") or str(cfg.service_account_file or ""))
        self.folder = tk.StringVar(value=saved.get("folder_id") or (cfg.folder_id or ""))

        rows = (
            ("OAuth client_secret JSON", self.secret, "Выбрать…", self._pick(self.secret)),
            ("Сервисный аккаунт JSON", self.service, "Выбрать…", self._pick(self.service)),
            ("ID папки на Диске", self.folder, "Вставить", self._paste),
        )
        for i, (label, var, btn_text, command) in enumerate(rows, start=2):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 12))
            ttk.Entry(frame, textvariable=var, width=52).grid(row=i, column=1, sticky="ew", pady=4)
            ttk.Button(frame, text=btn_text, command=command).grid(row=i, column=2, padx=(8, 0))

        ttk.Label(
            frame,
            text="ID папки — часть адреса после /folders/. Кнопка «Вставить» берёт его из буфера обмена\n"
                 "(Ctrl+V в Tkinter не срабатывает при русской раскладке).",
            foreground="gray",
        ).grid(row=5, column=1, columnspan=2, sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="right", padx=(0, 8))
        self.grab_set()

    def _pick(self, var: tk.StringVar) -> Callable[[], None]:
        def pick() -> None:
            path = filedialog.askopenfilename(
                parent=self, title="Выберите JSON-файл", initialdir=PROJECT_ROOT,
                filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
            )
            if path:
                var.set(path)
        return pick

    def _paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            messagebox.showinfo("Буфер обмена пуст", "Скопируйте ID папки или ссылку на неё.", parent=self)
            return
        # Если вставили всю ссылку — вытащим ID после /folders/
        match = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
        self.folder.set(match.group(1) if match else text)

    def _save(self) -> None:
        path = save_gui_settings({
            "client_secret_file": self.secret.get(),
            "service_account_file": self.service.get(),
            "folder_id": self.folder.get(),
        })
        messagebox.showinfo("Сохранено", f"Настройки сохранены в {path.relative_to(PROJECT_ROOT)}", parent=self)
        self.destroy()


class ExportSuccessDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, result: ReportResult) -> None:
        super().__init__(parent)
        self.title("Отчёт выгружен")
        self.transient(parent)
        self.resizable(False, False)
        self.link = result.link
        frame = ttk.Frame(self, padding=18)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text=result.title, font=("TkDefaultFont", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        where = "в эмулированный Google Drive (mock_drive)" if result.mode == "mock" else "в Google Drive"
        ttk.Label(frame, text=f"Записей: {result.rows}. Таблица создана {where}.").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 2))
        ttk.Label(frame, text=result.summary, foreground="gray").grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text=f"ID таблицы: {result.spreadsheet_id}", foreground="gray").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(frame, text="Ссылка на отчёт:").grid(row=4, column=0, columnspan=3, sticky="w")
        entry = ttk.Entry(frame, width=90)
        entry.insert(0, result.link)
        entry.configure(state="readonly")
        entry.grid(row=5, column=0, columnspan=3, sticky="ew")
        if result.mode == "mock":
            ttk.Label(frame, text=f"Файл: {local_path(result.link)}", foreground="gray",
                      wraplength=640).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Закрыть", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Копировать ссылку", command=self._copy).pack(side="right", padx=(0, 8))
        open_btn = ttk.Button(buttons, text="Открыть", command=self._open)
        open_btn.pack(side="right", padx=(0, 8))
        open_btn.focus_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _open(self) -> None:
        webbrowser.open(self.link)

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.link)
        self.update()  # чтобы ссылка осталась в буфере после закрытия окна


# ======================= вкладки =======================
class EntityTab(ttk.Frame):
    entity = ""
    columns: tuple[tuple[str, str, int], ...] = ()  # (ключ, заголовок, ширина)
    filters: dict[str, object] = {}                 # подпись -> значение фильтра

    def __init__(self, master: tk.Misc, app: "CRMApp") -> None:
        super().__init__(master, padding=8)
        self.app = app
        self.api = app.api
        self.offset = 0
        self.total = 0
        self.rows: dict[str, dict] = {}
        self._build()

    # ----- разметка -----
    def _build(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Поиск:").pack(side="left")
        self.search = ttk.Entry(bar, width=28)
        self.search.pack(side="left", padx=(4, 8))
        self.search.bind("<Return>", lambda _e: self.reload(reset=True))
        ttk.Label(bar, text="Статус:").pack(side="left")
        self.filter = ttk.Combobox(bar, state="readonly", width=16, values=list(self.filters))
        self.filter.set(next(iter(self.filters)))
        self.filter.pack(side="left", padx=(4, 8))
        self.filter.bind("<<ComboboxSelected>>", lambda _e: self.reload(reset=True))
        ttk.Button(bar, text="Найти", command=lambda: self.reload(reset=True)).pack(side="left")
        ttk.Button(bar, text="Сбросить", command=self._reset_filters).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Выгрузить отчёт", command=self.export).pack(side="right")

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Добавить", command=self.add).pack(side="left")
        ttk.Button(actions, text="Изменить", command=self.edit).pack(side="left", padx=4)
        for text, command in self.extra_actions():
            ttk.Button(actions, text=text, command=command).pack(side="left", padx=(0, 4))
        ttk.Button(actions, text="Обновить", command=self.reload).pack(side="left")

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in self.columns], show="headings",
                                 selectmode="browse")
        for key, title, width in self.columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="e" if key in ("id", "amount") else "w",
                             stretch=key not in ("id",))
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.edit())
        self.tree.tag_configure("muted", foreground="gray")

        pager = ttk.Frame(self)
        pager.pack(fill="x", pady=(6, 0))
        self.info = ttk.Label(pager, text="")
        self.info.pack(side="left")
        ttk.Button(pager, text="Следующие ›", command=lambda: self._page(+1)).pack(side="right")
        ttk.Button(pager, text="‹ Предыдущие", command=lambda: self._page(-1)).pack(side="right", padx=4)

    def extra_actions(self) -> list[tuple[str, Callable]]:
        return []

    # ----- данные -----
    def query_params(self) -> dict:
        return {"search": self.search.get().strip() or None}

    def format_row(self, item: dict) -> tuple[list, tuple]:
        raise NotImplementedError

    def reload(self, reset: bool = False) -> None:
        if reset:
            self.offset = 0
        try:
            page = self.api.list(self.entity, limit=PAGE, offset=self.offset, **self.query_params())
        except APIError as exc:
            self.app.set_status(str(exc))
            messagebox.showerror("Ошибка API", str(exc), parent=self)
            return
        self.total = page["total"]
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for item in page["items"]:
            values, tags = self.format_row(item)
            iid = str(item["id"])
            self.rows[iid] = item
            self.tree.insert("", "end", iid=iid, values=values, tags=tags)
        shown_to = self.offset + len(page["items"])
        self.info.configure(
            text=f"Показаны {self.offset + 1 if page['items'] else 0}–{shown_to} из {self.total}"
        )

    def _page(self, direction: int) -> None:
        new = self.offset + direction * PAGE
        if 0 <= new < max(self.total, 1):
            self.offset = new
            self.reload()

    def _reset_filters(self) -> None:
        self.search.delete(0, "end")
        self.filter.set(next(iter(self.filters)))
        self.reload(reset=True)

    def selected(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Нет выбора", "Выберите строку в таблице.", parent=self)
            return None
        return self.rows[sel[0]]

    def call(self, func: Callable, *args, done: str = "") -> bool:
        try:
            func(*args)
        except APIError as exc:
            messagebox.showerror("Ошибка API", str(exc.detail), parent=self)
            return False
        if done:
            self.app.set_status(done)
        self.reload()
        return True

    # ----- действия -----
    def add(self) -> None: ...
    def edit(self) -> None: ...

    def export(self) -> None:
        self.app.export(self.entity)


class ClientsTab(EntityTab):
    entity = "clients"
    columns = (("id", "ID", 60), ("full_name", "ФИО", 220), ("company", "Компания", 200),
               ("email", "Email", 200), ("phone", "Телефон", 140), ("status", "Статус", 90),
               ("created_at", "Создан", 140))
    filters = {"Все": None, **{v: k for k, v in CLIENT_STATUS_RU.items()}}

    def extra_actions(self):
        return [("Архивировать", self.archive), ("Удалить", self.delete)]

    def query_params(self) -> dict:
        return {**super().query_params(), "status": self.filters[self.filter.get()]}

    def format_row(self, c: dict):
        values = [c["id"], c["full_name"], c.get("company") or "", c.get("email") or "",
                  c.get("phone") or "", CLIENT_STATUS_RU.get(c["status"]), c["created_at"].replace("T", " ")]
        return values, ("muted",) if c["status"] == "archived" else ()

    def add(self) -> None:
        form = ClientForm(self)
        if form.result:
            self.call(self.api.create_client, form.result, done="Клиент добавлен")
            self.app.invalidate_choices()

    def edit(self) -> None:
        c = self.selected()
        if c:
            form = ClientForm(self, c)
            if form.result:
                self.call(self.api.update_client, c["id"], form.result, done="Клиент сохранён")
                self.app.invalidate_choices()

    def archive(self) -> None:
        c = self.selected()
        if c and messagebox.askyesno("Архивировать", f"Перевести «{c['full_name']}» в архив?", parent=self):
            self.call(self.api.archive_client, c["id"], done="Клиент отправлен в архив")

    def delete(self) -> None:
        c = self.selected()
        if c and messagebox.askyesno(
            "Удалить", f"Удалить клиента «{c['full_name']}»?\nСделки и задачи останутся без клиента.",
            icon="warning", parent=self,
        ):
            self.call(self.api.delete_client, c["id"], done="Клиент удалён")
            self.app.invalidate_choices()


class DealsTab(EntityTab):
    entity = "deals"
    columns = (("id", "ID", 60), ("title", "Название", 260), ("client", "Клиент", 220),
               ("amount", "Сумма, ₽", 120), ("status", "Статус", 100), ("close_date", "Закрытие", 100))
    filters = {"Все": None, **{v: k for k, v in DEAL_STATUS_RU.items()}}

    def extra_actions(self):
        return [("Удалить", self.delete)]

    def query_params(self) -> dict:
        return {**super().query_params(), "status": self.filters[self.filter.get()]}

    def format_row(self, d: dict):
        client = f"{d['client_id']} — {d.get('client_name') or ''}" if d.get("client_id") else "— без клиента —"
        amount = f"{d['amount']:,.2f}".replace(",", " ")
        values = [d["id"], d["title"], client, amount, DEAL_STATUS_RU.get(d["status"]), d.get("close_date") or ""]
        return values, ("muted",) if d["status"] == "lost" else ()

    def add(self) -> None:
        form = DealForm(self, self.app.client_choices())
        if form.result:
            self.call(self.api.create_deal, form.result, done="Сделка добавлена")
            self.app.invalidate_choices()

    def edit(self) -> None:
        d = self.selected()
        if d:
            form = DealForm(self, self.app.client_choices(), d)
            if form.result:
                self.call(self.api.update_deal, d["id"], form.result, done="Сделка сохранена")
                self.app.invalidate_choices()

    def delete(self) -> None:
        d = self.selected()
        if d and messagebox.askyesno("Удалить", f"Удалить сделку «{d['title']}»?", icon="warning", parent=self):
            self.call(self.api.delete_deal, d["id"], done="Сделка удалена")
            self.app.invalidate_choices()


class TasksTab(EntityTab):
    entity = "tasks"
    columns = (("id", "ID", 60), ("title", "Задача", 280), ("due_date", "Срок", 100),
               ("is_done", "Выполнена", 90), ("client_id", "Клиент", 80), ("deal_id", "Сделка", 80))
    filters = {"Все": None, "Не выполнены": False, "Выполнены": True}

    def extra_actions(self):
        return [("Выполнено / нет", self.toggle_done), ("Удалить", self.delete)]

    def query_params(self) -> dict:
        return {**super().query_params(), "is_done": self.filters[self.filter.get()]}

    def format_row(self, t: dict):
        overdue = not t["is_done"] and t.get("due_date") and t["due_date"] < date.today().isoformat()
        values = [t["id"], t["title"], t.get("due_date") or "", "✓" if t["is_done"] else "",
                  t.get("client_id") or "", t.get("deal_id") or ""]
        tags = ("muted",) if t["is_done"] else ("overdue",) if overdue else ()
        return values, tags

    def _build(self) -> None:
        super()._build()
        self.tree.tag_configure("overdue", foreground="#b3261e")

    def add(self) -> None:
        form = TaskForm(self, self.app.client_choices(), self.app.deal_choices())
        if form.result:
            self.call(self.api.create_task, form.result, done="Задача добавлена")

    def edit(self) -> None:
        t = self.selected()
        if t:
            form = TaskForm(self, self.app.client_choices(), self.app.deal_choices(), t)
            if form.result:
                self.call(self.api.update_task, t["id"], form.result, done="Задача сохранена")

    def toggle_done(self) -> None:
        t = self.selected()
        if t:
            self.call(self.api.set_task_done, t["id"], not t["is_done"], done="Статус задачи изменён")

    def delete(self) -> None:
        t = self.selected()
        if t and messagebox.askyesno("Удалить", f"Удалить задачу «{t['title']}»?", icon="warning", parent=self):
            self.call(self.api.delete_task, t["id"], done="Задача удалена")


# ======================= главное окно =======================
class CRMApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Мини-CRM")
        self.geometry("1180x680")
        self.minsize(900, 480)
        install_layout_independent_shortcuts(self)
        self.config_ = load_config()
        self.api = CRMClient(self.config_.api_url)
        self.runner = BackgroundRunner(self)
        self._clients_cache: list[str] | None = None
        self._deals_cache: list[str] | None = None
        self._exporting = False

        top = ttk.Frame(self, padding=(8, 8, 8, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Мини-CRM", font=("TkDefaultFont", 14, "bold")).pack(side="left")
        ttk.Button(top, text="Настройки Google", command=lambda: GoogleSettingsDialog(self)).pack(side="right")
        self.mode_label = ttk.Label(top, foreground="gray")
        self.mode_label.pack(side="right", padx=12)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.tabs = {
            "clients": ClientsTab(self.notebook, self),
            "deals": DealsTab(self.notebook, self),
            "tasks": TasksTab(self.notebook, self),
        }
        for key, title in (("clients", "Клиенты"), ("deals", "Сделки"), ("tasks", "Задачи")):
            self.notebook.add(self.tabs[key], text=title)

        self.status = ttk.Label(self, relief="sunken", anchor="w", padding=(8, 2))
        self.status.pack(fill="x", side="bottom")
        self._refresh_mode()
        self.after(100, self._initial_load)

    def _refresh_mode(self) -> None:
        cfg = load_config()
        self.mode_label.configure(text=f"Google: {'эмуляция (mock)' if cfg.is_mock else 'real'} · API: {cfg.api_url}")

    def _initial_load(self) -> None:
        if not self.api.health():
            self.set_status("Бэкенд недоступен. Запустите: docker compose up -d --build — и нажмите «Обновить».")
            messagebox.showwarning(
                "Бэкенд недоступен",
                f"Не удалось подключиться к {self.api.base_url}.\n\nЗапустите бэкенд командой\n"
                "docker compose up -d --build\nи нажмите «Обновить» на вкладке.",
            )
            return
        for tab in self.tabs.values():
            tab.reload()
        self.set_status("Готово")

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    # ----- списки для выпадающих полей -----
    def invalidate_choices(self) -> None:
        self._clients_cache = None
        self._deals_cache = None

    def client_choices(self) -> list[str]:
        if self._clients_cache is None:
            try:
                items = self.api.fetch_all("clients")
            except APIError as exc:
                messagebox.showerror("Ошибка API", str(exc))
                return []
            self._clients_cache = [f"{c['id']} — {c['full_name']}" for c in items if c["status"] != "archived"]
        return self._clients_cache

    def deal_choices(self) -> list[str]:
        if self._deals_cache is None:
            try:
                items = self.api.fetch_all("deals")
            except APIError as exc:
                messagebox.showerror("Ошибка API", str(exc))
                return []
            self._deals_cache = [f"{d['id']} — {d['title']}" for d in items]
        return self._deals_cache

    # ----- выгрузка отчёта -----
    def export(self, kind: str) -> None:
        if self._exporting:
            messagebox.showinfo("Подождите", "Предыдущая выгрузка ещё выполняется.")
            return
        self._exporting = True
        self._refresh_mode()
        self.configure(cursor="watch")
        self.set_status(f"{REPORT_TITLES[kind]}: подготовка…")
        progress = lambda msg: self.runner.post(self.set_status, f"{REPORT_TITLES[kind]}: {msg}")  # noqa: E731
        self.runner.run(
            lambda: export_report(kind, self.api, progress),
            on_done=self._export_done,
            on_error=self._export_failed,
        )

    def _export_done(self, result: ReportResult) -> None:
        self._exporting = False
        self.configure(cursor="")
        self.set_status(f"{result.title}: выгружено {result.rows} записей")
        ExportSuccessDialog(self, result)

    def _export_failed(self, exc: Exception) -> None:
        self._exporting = False
        self.configure(cursor="")
        self.set_status(f"Ошибка выгрузки: {exc}")
        messagebox.showerror("Ошибка выгрузки", f"{type(exc).__name__}: {exc}")


def main() -> None:
    CRMApp().mainloop()


if __name__ == "__main__":
    main()
