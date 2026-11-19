"""Заполнение мини-CRM реалистичными тестовыми данными через API.

    python fill_test_data.py                # по 1000 клиентов, сделок и задач
    python fill_test_data.py --count 50
    python fill_test_data.py --api-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta

import requests
from faker import Faker
from tqdm import tqdm

fake = Faker("ru_RU")

DEAL_TEMPLATES = (
    "Поставка {product}", "Внедрение {system}", "Годовое обслуживание {system}",
    "Аудит {area}", "Разработка {thing}", "Аренда {product}", "Консалтинг по {area}",
    "Обучение персонала: {area}", "Модернизация {thing}", "Лицензии {system}",
)
PRODUCTS = ("серверного оборудования", "офисной мебели", "ноутбуков", "спецтехники",
            "упаковочных материалов", "кондиционеров", "строительных материалов", "оргтехники")
SYSTEMS = ("CRM", "1С:Бухгалтерия", "ERP-системы", "СЭД", "WMS", "BI-платформы", "IP-телефонии")
AREAS = ("информационной безопасности", "бизнес-процессов", "логистики", "маркетинга",
         "охраны труда", "финансовой отчётности", "продаж")
THINGS = ("интернет-магазина", "корпоративного сайта", "мобильного приложения",
          "складского комплекса", "локальной сети", "колл-центра")

TASK_TEMPLATES = (
    ("Позвонить клиенту", "Уточнить потребности и сроки"),
    ("Отправить коммерческое предложение", "КП с учётом скидки за объём"),
    ("Подготовить договор", "Согласовать с юристом и отправить на подпись"),
    ("Назначить встречу", "Презентация решения у клиента"),
    ("Выставить счёт", "Счёт на предоплату 50 %"),
    ("Проверить оплату", "Сверить поступление по выписке"),
    ("Отправить закрывающие документы", "Акт и счёт-фактура"),
    ("Провести демонстрацию", "Онлайн-демо для команды клиента"),
    ("Собрать обратную связь", "Короткий опрос после внедрения"),
    ("Согласовать ТЗ", "Финальная версия технического задания"),
)


def amount() -> float:
    """5 000 – 2 000 000 ₽, логнормально: много средних сделок, мало крупных."""
    value = random.lognormvariate(11.8, 1.0)  # медиана ≈ 133 000 ₽
    value = min(max(value, 5_000), 2_000_000)
    return round(value / 100) * 100.0


def past_datetime(days: int = 365) -> str:
    moment = datetime.now() - timedelta(days=random.randint(0, days), seconds=random.randint(0, 86_399))
    return moment.isoformat(timespec="seconds")


def make_client() -> dict:
    has_company = random.random() < 0.8
    return {
        "full_name": fake.name(),
        "company": fake.company() if has_company else None,
        "email": fake.unique.email(),
        "phone": fake.phone_number(),
        "status": random.choices(("active", "lead", "archived"), weights=(60, 25, 15))[0],
        "notes": random.choice((None, None, fake.sentence(nb_words=8))),
        "created_at": past_datetime(),
    }


def make_deal(client_ids: list[int]) -> dict:
    status = random.choices(("new", "in_progress", "won", "lost"), weights=(20, 30, 30, 20))[0]
    template = random.choice(DEAL_TEMPLATES)
    title = template.format(product=random.choice(PRODUCTS), system=random.choice(SYSTEMS),
                            area=random.choice(AREAS), thing=random.choice(THINGS))
    shift = random.randint(-180, -1) if status in ("won", "lost") else random.randint(1, 180)
    return {
        "title": title,
        "client_id": random.choice(client_ids) if client_ids and random.random() >= 0.15 else None,
        "amount": amount(),
        "currency": "RUB",
        "status": status,
        "close_date": (date.today() + timedelta(days=shift)).isoformat(),
        "created_at": past_datetime(),
    }


def make_task(client_ids: list[int], deals: list[tuple[int, int | None]]) -> dict:
    title, description = random.choice(TASK_TEMPLATES)
    roll = random.random()
    client_id = deal_id = None
    if roll < 0.4 and deals:
        deal_id, client_id = random.choice(deals)
    elif roll < 0.7 and client_ids:
        client_id = random.choice(client_ids)
    due = date.today() + timedelta(days=random.randint(-60, 60))
    is_done = random.random() < (0.7 if due < date.today() else 0.2)
    return {
        "title": title,
        "description": description,
        "due_date": due.isoformat(),
        "is_done": is_done,
        "client_id": client_id,
        "deal_id": deal_id,
        "created_at": past_datetime(120),
    }


def post_many(session: requests.Session, url: str, factory, count: int, label: str) -> list[dict]:
    created = []
    for _ in tqdm(range(count), desc=label, unit="шт", ncols=80):
        resp = session.post(url, json=factory(), timeout=15)
        resp.raise_for_status()
        created.append(resp.json())
    return created


def existing_ids(session: requests.Session, api: str, entity: str) -> list[dict]:
    items, offset = [], 0
    while True:
        page = session.get(f"{api}/{entity}", params={"limit": 1000, "offset": offset}, timeout=15).json()
        items += page["items"]
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            return items


def fill(api_url: str, count: int, seed: int | None = None) -> dict:
    api = api_url.rstrip("/")
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)
    session = requests.Session()
    try:
        session.get(f"{api}/health", timeout=5).raise_for_status()
    except requests.RequestException:
        raise SystemExit(
            f"Бэкенд недоступен по адресу {api}.\nЗапустите его: docker compose up -d --build"
        ) from None

    clients = post_many(session, f"{api}/clients", make_client, count, "Клиенты")
    client_ids = [c["id"] for c in existing_ids(session, api, "clients") if c["status"] != "archived"]

    deals = post_many(session, f"{api}/deals", lambda: make_deal(client_ids), count, "Сделки  ")
    deal_refs = [(d["id"], d.get("client_id")) for d in existing_ids(session, api, "deals")]

    tasks = post_many(session, f"{api}/tasks", lambda: make_task(client_ids, deal_refs), count, "Задачи  ")
    return {"clients": len(clients), "deals": len(deals), "tasks": len(tasks)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Заполнение мини-CRM тестовыми данными")
    parser.add_argument("--count", type=int, default=1000, help="записей каждого типа (по умолчанию 1000)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="адрес бэкенда")
    parser.add_argument("--seed", type=int, default=None, help="зерно генератора для воспроизводимости")
    args = parser.parse_args()
    result = fill(args.api_url, args.count, args.seed)
    print(f"Готово: клиентов {result['clients']}, сделок {result['deals']}, задач {result['tasks']}.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        sys.exit(f"Ошибка API: {exc} — {exc.response.text}")
