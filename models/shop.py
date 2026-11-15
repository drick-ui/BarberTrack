"""Shop entities: Barber, Service, Product, Transaction and QueueEntry."""
from datetime import date, timedelta

import pymysql

from .base import BaseModel, Database


class Barber(BaseModel):
    table = "barbers"
    columns = ("name", "phone", "commission_rate")

    def commission_for(self, amount):
        """The barber's share of a service amount."""
        return round(float(amount) * float(self.commission_rate) / 100, 2)


class Service(BaseModel):
    table = "services"
    columns = ("name", "price")


class Product(BaseModel):
    table = "products"
    columns = ("name", "price", "stock")

    def has_stock(self, quantity):
        return int(self.stock) >= quantity

    @classmethod
    def adjust_stock(cls, product_id, delta):
        """Add (positive) or remove (negative) stock."""
        if product_id and delta:
            Database.execute("UPDATE products SET stock = stock + %s WHERE id=%s", (delta, product_id))


class Transaction(BaseModel):
    """A sale: a service, a product, or both. Commission applies to the service part only."""
    table = "transactions"
    columns = ("barber_id", "service_id", "product_id", "product_qty", "product_total",
               "customer_name", "amount", "commission", "shop_share", "payment_method")

    # ----- business rules -----
    @staticmethod
    def _compute(data):
        amount = float(data["amount"])
        barber = Barber.find(int(data["barber_id"])) if data.get("barber_id") else None
        service_id = int(data["service_id"]) if data.get("service_id") else None
        product = Product.find(int(data["product_id"])) if data.get("product_id") else None
        qty = int(float(data.get("product_qty") or 0)) if product else 0
        product_total = round(float(product.price) * qty, 2) if product else 0.0
        service_part = max(amount - product_total, 0.0) if service_id else 0.0
        commission = barber.commission_for(service_part) if barber else 0.0
        return {**data, "amount": amount,
                "barber_id": barber.id if barber else None, "service_id": service_id,
                "product_id": product.id if product else None, "product_qty": qty,
                "product_total": product_total, "commission": commission,
                "shop_share": round(amount - commission, 2)}

    @classmethod
    def check(cls, data, record_id=None):
        """Cross-field validation. Returns a list of error messages."""
        barber, service = data.get("barber_id"), data.get("service_id")
        pid, qty = data.get("product_id"), data.get("product_qty")
        try:
            qty = int(float(qty)) if qty else 0
            pid = int(pid) if pid else None
        except ValueError:
            return ["Invalid product or quantity."]
        if not service and not pid:
            return ["Choose a service or a product (or both)."]
        if service and not barber:
            return ["Choose a barber for the service."]
        if not pid:
            return ["Choose a product if you entered a quantity."] if qty else []
        if qty < 1:
            return ["Product quantity must be at least 1."]
        product = Product.find(pid)
        if not product:
            return ["Invalid product."]
        available = int(product.stock)
        if record_id:  # when editing, the old quantity is returned to stock first
            old = cls.find(record_id)
            if old and old.product_id == pid:
                available += int(old.product_qty)
        if qty > available:
            return [f"Not enough stock for {product.name} (available: {available})."]
        return []

    # ----- persistence (keeps product stock in sync) -----
    @classmethod
    def create(cls, data):
        d = cls._compute(data)
        new_id = super().create(d)
        Product.adjust_stock(d["product_id"], -d["product_qty"])
        return new_id

    @classmethod
    def update(cls, record_id, data):
        old = cls.find(record_id)
        d = cls._compute(data)
        super().update(record_id, d)
        if old:
            Product.adjust_stock(old.product_id, int(old.product_qty))
        Product.adjust_stock(d["product_id"], -d["product_qty"])

    @classmethod
    def delete(cls, record_id):
        old = cls.find(record_id)
        super().delete(record_id)
        if old:
            Product.adjust_stock(old.product_id, int(old.product_qty))

    # ----- queries -----
    @classmethod
    def all(cls):
        rows = Database.query(
            "SELECT t.*, COALESCE(b.name, '-') AS barber_name, COALESCE(s.name, '-') AS service_name, "
            "p.name AS product_name "
            "FROM transactions t LEFT JOIN barbers b ON b.id=t.barber_id "
            "LEFT JOIN services s ON s.id=t.service_id "
            "LEFT JOIN products p ON p.id=t.product_id ORDER BY t.txn_date DESC, t.id DESC")
        for row in rows:
            row["product_label"] = f"{row['product_name']} x{row['product_qty']}" if row["product_id"] else ""
        return cls._wrap(rows)

    @staticmethod
    def summary(period="day"):
        cond = ("DATE(txn_date)=CURDATE()" if period == "day" else
                "YEAR(txn_date)=YEAR(CURDATE()) AND MONTH(txn_date)=MONTH(CURDATE())")
        return Database.query(
            "SELECT COUNT(*) AS cuts, COALESCE(SUM(amount),0) AS sales, "
            "COALESCE(SUM(commission),0) AS commission, COALESCE(SUM(shop_share),0) AS shop "
            f"FROM transactions WHERE {cond}", one=True)

    @staticmethod
    def sales_by_day(days=7):
        """Sales for each of the last `days` days (oldest first), used by the dashboard chart."""
        today = date.today()
        start = today - timedelta(days=days - 1)
        rows = Database.query(
            "SELECT DATE(txn_date) AS day, COALESCE(SUM(amount), 0) AS sales FROM transactions "
            "WHERE DATE(txn_date) >= %s GROUP BY DATE(txn_date)", (start.isoformat(),))
        totals = {str(r["day"])[:10]: float(r["sales"]) for r in rows}
        series = []
        for i in range(days):
            day = start + timedelta(days=i)
            series.append({"date": day, "label": day.strftime("%a"), "full": day.strftime("%b %d"),
                           "sales": totals.get(day.isoformat(), 0.0), "is_today": day == today})
        biggest = max((d["sales"] for d in series), default=0) or 1
        for d in series:
            d["pct"] = round(d["sales"] / biggest * 100, 1)
        return series

    @staticmethod
    def per_barber_today():
        return Database.query(
            "SELECT b.name, COUNT(*) AS cuts, SUM(t.amount) AS sales, SUM(t.commission) AS commission "
            "FROM transactions t JOIN barbers b ON b.id=t.barber_id "
            "WHERE DATE(t.txn_date)=CURDATE() GROUP BY b.id, b.name ORDER BY sales DESC")


class QueueError(ValueError):
    """Raised when a queue rule is broken (shown to the user as a message)."""


class QueueEntry(BaseModel):
    """A walk-in customer in today's queue. The status rules live here, not in the routes."""
    table = "queue_entries"
    STATUSES = ("Waiting", "Serving", "Done", "Cancelled")

    @property
    def is_paid(self):
        return bool(self._row.get("transaction_id"))

    # ----- queries -----
    @classmethod
    def today(cls):
        return cls._wrap(Database.query(
            "SELECT q.*, b.name AS barber_name, s.name AS service_name, t.amount AS paid_amount "
            "FROM queue_entries q LEFT JOIN barbers b ON b.id=q.barber_id "
            "LEFT JOIN services s ON s.id=q.service_id "
            "LEFT JOIN transactions t ON t.id=q.transaction_id "
            "WHERE q.queue_date=CURDATE() ORDER BY q.queue_no"))

    @classmethod
    def add(cls, customer_name, service_id=None, barber_id=None):
        """Add a walk-in to today's queue and return its number (resets every day)."""
        for attempt in range(3):  # retry if two people add at the same moment
            number = Database.query(
                "SELECT COALESCE(MAX(queue_no), 0) + 1 AS n FROM queue_entries "
                "WHERE queue_date=CURDATE()", one=True)["n"]
            try:
                Database.execute(
                    "INSERT INTO queue_entries (queue_date, queue_no, customer_name, service_id, barber_id) "
                    "VALUES (CURDATE(), %s, %s, %s, %s)",
                    (number, customer_name, service_id or None, barber_id or None))
                return number
            except pymysql.err.IntegrityError:
                if attempt == 2:
                    raise

    # ----- status transitions -----
    def _set_status(self, status, barber_id=None):
        if barber_id:
            Database.execute("UPDATE queue_entries SET status=%s, barber_id=%s WHERE id=%s",
                             (status, barber_id, self.id))
            self._row["barber_id"] = barber_id
        else:
            Database.execute("UPDATE queue_entries SET status=%s WHERE id=%s", (status, self.id))
        self._row["status"] = status

    def start(self, barber_id=None):
        barber_id = barber_id or self._row.get("barber_id")
        if self.status != "Waiting":
            raise QueueError("Only waiting customers can be started.")
        if not barber_id or not Barber.find(barber_id):
            raise QueueError("Choose a barber first.")
        busy = Database.query(
            "SELECT COUNT(*) AS n FROM queue_entries WHERE queue_date=CURDATE() "
            "AND status='Serving' AND barber_id=%s", (barber_id,), one=True)["n"]
        if busy:
            raise QueueError("That barber is already serving a customer.")
        self._set_status("Serving", barber_id)

    def finish(self):
        if self.status != "Serving":
            raise QueueError("Only customers being served can be marked as done.")
        if not self.is_paid:
            raise QueueError("Record the payment first before marking this customer as Done.")
        self._set_status("Done")

    def cancel(self):
        if self.status != "Waiting":
            raise QueueError("Only waiting customers can be cancelled.")
        self._set_status("Cancelled")

    def attach_payment(self, transaction_id):
        """Link a recorded transaction to this customer (allowed while being served)."""
        Database.execute("UPDATE queue_entries SET transaction_id=%s "
                         "WHERE id=%s AND status='Serving' AND transaction_id IS NULL",
                         (transaction_id, self.id))
