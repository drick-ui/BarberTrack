"""Data-access layer: a Database helper and the BaseModel parent class."""
import pymysql
from flask import current_app


class Database:
    """Thin wrapper around PyMySQL. Every query is parameterized (prevents SQL injection)."""

    @staticmethod
    def _connect():
        cfg = current_app.config
        return pymysql.connect(
            host=cfg["DB_HOST"], user=cfg["DB_USER"], password=cfg["DB_PASSWORD"],
            database=cfg["DB_NAME"], cursorclass=pymysql.cursors.DictCursor, autocommit=True,
        )

    @classmethod
    def query(cls, sql, params=(), one=False):
        conn = cls._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone() if one else cur.fetchall()
        finally:
            conn.close()

    @classmethod
    def execute(cls, sql, params=()):
        conn = cls._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.lastrowid
        finally:
            conn.close()


class BaseModel:
    """Parent of every entity. One instance wraps one database row.

    Encapsulation: the raw row lives in the private ``_row`` dictionary. Columns listed in
    ``hidden`` (e.g. password hashes) cannot be read through attributes, indexing, or to_dict().
    Templates can still use ``obj.name`` or ``obj["name"]`` for the visible columns.
    """

    table = ""
    columns = ()   # columns that can be written by create()/update()
    hidden = ()    # columns that must never be exposed

    def __init__(self, row=None):
        self._row = dict(row or {})

    # ----- read access -----
    @property
    def id(self):
        return self._row.get("id")

    def __getattr__(self, name):
        if name.startswith("_") or name in self.hidden:
            raise AttributeError(name)
        try:
            return self._row[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, key):
        if key in self.hidden:
            raise KeyError(key)
        return self._row[key]

    def get(self, key, default=None):
        return default if key in self.hidden else self._row.get(key, default)

    def to_dict(self):
        return {k: v for k, v in self._row.items() if k not in self.hidden}

    def __repr__(self):
        return f"<{type(self).__name__} id={self.id}>"

    def refresh(self):
        """Reload this object from the database."""
        row = Database.query(f"SELECT * FROM {self.table} WHERE id=%s", (self.id,), one=True)
        self._row = dict(row or {})
        return self

    # ----- generic CRUD (inherited by every subclass) -----
    @classmethod
    def _wrap(cls, rows):
        return [cls(r) for r in rows]

    @classmethod
    def all(cls):
        return cls._wrap(Database.query(f"SELECT * FROM {cls.table} ORDER BY id DESC"))

    @classmethod
    def find(cls, record_id):
        row = Database.query(f"SELECT * FROM {cls.table} WHERE id=%s", (record_id,), one=True)
        return cls(row) if row else None

    @classmethod
    def create(cls, data):
        cols = ", ".join(cls.columns)
        marks = ", ".join(["%s"] * len(cls.columns))
        return Database.execute(f"INSERT INTO {cls.table} ({cols}) VALUES ({marks})",
                                [data[c] for c in cls.columns])

    @classmethod
    def update(cls, record_id, data):
        sets = ", ".join(f"{c}=%s" for c in cls.columns)
        Database.execute(f"UPDATE {cls.table} SET {sets} WHERE id=%s",
                         [data[c] for c in cls.columns] + [record_id])

    @classmethod
    def delete(cls, record_id):
        Database.execute(f"DELETE FROM {cls.table} WHERE id=%s", (record_id,))
