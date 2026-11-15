"""Test helpers: run the models against an in-memory SQLite database (no MySQL needed)."""
import sqlite3
from datetime import date, datetime, timezone
from unittest import mock

from models import base

sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))
sqlite3.register_converter("DATETIME", lambda b: datetime.fromisoformat(b.decode()))

SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, photo TEXT DEFAULT '', otp_hash TEXT, otp_expires DATETIME,
  otp_attempts INTEGER NOT NULL DEFAULT 0, failed_logins INTEGER NOT NULL DEFAULT 0, locked_until DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE barbers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT DEFAULT '',
  commission_rate REAL NOT NULL DEFAULT 50);
CREATE TABLE services (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price REAL NOT NULL);
CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price REAL NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0);
CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, barber_id INTEGER, service_id INTEGER,
  product_id INTEGER, product_qty INTEGER NOT NULL DEFAULT 0, product_total REAL NOT NULL DEFAULT 0,
  customer_name TEXT DEFAULT '', amount REAL NOT NULL, commission REAL NOT NULL, shop_share REAL NOT NULL,
  payment_method TEXT NOT NULL DEFAULT 'Cash', txn_date DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE queue_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, queue_date TEXT NOT NULL,
  queue_no INTEGER NOT NULL, customer_name TEXT NOT NULL DEFAULT '', service_id INTEGER, barber_id INTEGER,
  status TEXT NOT NULL DEFAULT 'Waiting', transaction_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (queue_date, queue_no));
"""


class _Cursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("%s", "?"), tuple(params))

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Connection:
    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return _Cursor(self._raw.cursor())

    def close(self):  # keep the in-memory database alive between queries
        pass


def new_database():
    """Create an in-memory SQLite database that understands the few MySQL functions we use."""
    raw = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    today = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw.create_function("CURDATE", 0, today)
    raw.create_function("YEAR", 1, lambda v: int(str(v)[:4]))
    raw.create_function("MONTH", 1, lambda v: int(str(v)[5:7]))
    raw.executescript(SCHEMA)
    return raw


class DatabaseTestCase:
    """Mixin: gives each test a fresh empty database."""

    def setUp(self):
        self.raw = new_database()
        patcher = mock.patch.object(base.Database, "_connect", staticmethod(lambda: _Connection(self.raw)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.raw.close)
