"""Описания таблиц SQLite и допустимые значения статусов."""

CLIENT_STATUSES = ("active", "archived", "lead")
DEAL_STATUSES = ("new", "in_progress", "won", "lost")

CLIENTS_TABLE = """
CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT    NOT NULL,
    company     TEXT,
    email       TEXT,
    phone       TEXT,
    status      TEXT    NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived', 'lead')),
    notes       TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)
"""

DEALS_TABLE = """
CREATE TABLE IF NOT EXISTS deals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    client_id   INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    amount      REAL    NOT NULL DEFAULT 0,
    currency    TEXT    NOT NULL DEFAULT 'RUB',
    status      TEXT    NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'in_progress', 'won', 'lost')),
    close_date  TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)
"""

TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT,
    due_date    TEXT,
    is_done     INTEGER NOT NULL DEFAULT 0 CHECK (is_done IN (0, 1)),
    client_id   INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    deal_id     INTEGER REFERENCES deals(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status)",
    "CREATE INDEX IF NOT EXISTS idx_deals_client ON deals(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_client ON tasks(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_deal ON tasks(deal_id)",
)

ALL_TABLES = (CLIENTS_TABLE, DEALS_TABLE, TASKS_TABLE)
