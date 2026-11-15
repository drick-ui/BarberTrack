"""Unit tests for the model layer (business rules). Run: python -m unittest discover -s tests"""
import unittest
from datetime import datetime, timedelta

from models import (Barber, Database, Product, QueueEntry, QueueError, Service,
                    Transaction, User)
from tests.helpers import DatabaseTestCase


class UserTests(DatabaseTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.register("Owner", "owner@example.com", "Secret123")

    def test_password_is_hashed_and_hidden(self):
        self.assertTrue(self.user.check_password("Secret123"))
        self.assertFalse(self.user.check_password("wrong"))
        with self.assertRaises(AttributeError):
            self.user.password_hash
        self.assertNotIn("password_hash", self.user.to_dict())
        stored = Database.query("SELECT password_hash FROM users", one=True)["password_hash"]
        self.assertNotEqual(stored, "Secret123")  # only a hash is stored

    def test_password_policy(self):
        self.assertIsNotNone(User.password_problem("short1"))
        self.assertIsNotNone(User.password_problem("onlyletters"))
        self.assertIsNotNone(User.password_problem("12345678"))
        self.assertIsNone(User.password_problem("Secret123"))

    def test_login_lockout_after_five_failures(self):
        for _ in range(4):
            self.assertEqual(User.authenticate("owner@example.com", "bad")[1], "invalid")
        self.assertEqual(User.authenticate("owner@example.com", "bad")[1], "invalid")  # 5th failure locks
        user, status = User.authenticate("owner@example.com", "Secret123")
        self.assertEqual(status, "locked")  # even the right password is refused while locked
        self.assertGreaterEqual(user.lock_minutes_left, 1)

    def test_successful_login_resets_failures(self):
        User.authenticate("owner@example.com", "bad")
        user, status = User.authenticate("owner@example.com", "Secret123")
        self.assertEqual(status, "ok")
        self.assertEqual(Database.query("SELECT failed_logins FROM users", one=True)["failed_logins"], 0)

    def test_unknown_email_is_invalid(self):
        self.assertEqual(User.authenticate("nobody@example.com", "x"), (None, "invalid"))

    def test_otp_flow(self):
        code = self.user.issue_otp()
        self.assertEqual(len(code), 6)
        self.assertEqual(self.user.verify_otp("000000" if code != "000000" else "111111"), "invalid")
        self.assertEqual(self.user.verify_otp(code), "ok")
        self.assertEqual(self.user.verify_otp(code), "expired")  # a code works only once

    def test_otp_locks_after_five_wrong_codes(self):
        code = self.user.issue_otp()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.user.verify_otp(wrong), "invalid")
        self.assertEqual(self.user.verify_otp(code), "locked")

    def test_otp_expires(self):
        code = self.user.issue_otp()
        Database.execute("UPDATE users SET otp_expires=%s", (datetime.now() - timedelta(minutes=1),))
        self.assertEqual(self.user.verify_otp(code), "expired")


class ShopTests(DatabaseTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.barber = Barber.find(Barber.create({"name": "Juan", "phone": "", "commission_rate": "50"}))
        self.service = Service.find(Service.create({"name": "Haircut", "price": "100"}))
        self.product = Product.find(Product.create({"name": "Pomade", "price": "250", "stock": "10"}))

    def sale(self, **overrides):
        data = {"barber_id": self.barber.id, "service_id": self.service.id, "product_id": "",
                "product_qty": "", "customer_name": "", "amount": "100", "payment_method": "Cash"}
        data.update(overrides)
        return data

    def stock(self):
        return Product.find(self.product.id).stock

    def test_commission_applies_to_service_only(self):
        data = self.sale(product_id=self.product.id, product_qty="2", amount="600")  # 100 service + 500 product
        Transaction.create(data)
        t = Transaction.all()[0]
        self.assertEqual((float(t.commission), float(t.shop_share)), (50.0, 550.0))
        self.assertEqual(self.stock(), 8)

    def test_product_only_sale_needs_no_barber_or_service(self):
        data = self.sale(barber_id="", service_id="", product_id=self.product.id, product_qty="1", amount="250")
        self.assertEqual(Transaction.check(data), [])
        Transaction.create(data)
        t = Transaction.all()[0]
        self.assertEqual((float(t.commission), float(t.shop_share)), (0.0, 250.0))
        self.assertEqual(t.product_label, "Pomade x1")

    def test_validation_rules(self):
        self.assertEqual(len(Transaction.check(self.sale(barber_id="", service_id=""))), 1)  # nothing chosen
        self.assertEqual(len(Transaction.check(self.sale(barber_id=""))), 1)                  # service, no barber
        self.assertEqual(len(Transaction.check(self.sale(product_id=self.product.id, product_qty="99"))), 1)
        self.assertEqual(len(Transaction.check(self.sale(product_qty="2"))), 1)              # qty without product

    def test_update_and_delete_keep_stock_in_sync(self):
        new_id = Transaction.create(self.sale(product_id=self.product.id, product_qty="2", amount="600"))
        self.assertEqual(self.stock(), 8)
        Transaction.update(new_id, self.sale(product_id=self.product.id, product_qty="5", amount="1350"))
        self.assertEqual(self.stock(), 5)
        Transaction.delete(new_id)
        self.assertEqual(self.stock(), 10)

    def test_dashboard_summary(self):
        Transaction.create(self.sale(amount="100"))
        s = Transaction.summary("day")
        self.assertEqual((s["cuts"], float(s["sales"]), float(s["commission"])), (1, 100.0, 50.0))
        self.assertEqual(Transaction.per_barber_today()[0]["name"], "Juan")


class QueueTests(DatabaseTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.b1 = Barber.find(Barber.create({"name": "A", "phone": "", "commission_rate": "50"}))
        self.b2 = Barber.find(Barber.create({"name": "B", "phone": "", "commission_rate": "50"}))

    def entry(self, number):
        return [e for e in QueueEntry.today() if e.queue_no == number][0]

    def test_numbers_increase(self):
        self.assertEqual([QueueEntry.add("x"), QueueEntry.add("y"), QueueEntry.add("z")], [1, 2, 3])

    def test_start_requires_a_barber(self):
        QueueEntry.add("x")
        with self.assertRaises(QueueError):
            self.entry(1).start()
        self.entry(1).start(self.b1.id)
        self.assertEqual(self.entry(1).status, "Serving")

    def test_one_customer_per_barber(self):
        QueueEntry.add("x")
        QueueEntry.add("y")
        self.entry(1).start(self.b1.id)
        with self.assertRaises(QueueError):
            self.entry(2).start(self.b1.id)
        self.entry(2).start(self.b2.id)

    def test_done_requires_payment(self):
        QueueEntry.add("x")
        entry = self.entry(1)
        entry.start(self.b1.id)
        with self.assertRaises(QueueError):
            entry.finish()
        entry.attach_payment(Transaction.create({
            "barber_id": self.b1.id, "service_id": "", "product_id": "", "product_qty": "",
            "customer_name": "", "amount": "100", "payment_method": "Cash"}))
        entry = self.entry(1)
        self.assertTrue(entry.is_paid)
        entry.finish()
        self.assertEqual(self.entry(1).status, "Done")

    def test_only_waiting_can_be_cancelled(self):
        QueueEntry.add("x")
        QueueEntry.add("y")
        self.entry(2).cancel()
        self.entry(1).start(self.b1.id)
        with self.assertRaises(QueueError):
            self.entry(1).cancel()


if __name__ == "__main__":
    unittest.main()
