"""End-to-end tests of the web pages (login + OTP, CRUD, queue). Run: python -m unittest discover -s tests"""
import re
import unittest
from unittest import mock

import mailer
from app import app
from models import Barber, Product, QueueEntry, Service, User
from tests.helpers import DatabaseTestCase

PASSWORD = "Secret123"


class WebTestCase(DatabaseTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, MAIL_SUPPRESS_SEND=True, APP_DEBUG=False)
        self.client = app.test_client()
        self.owner = User.register("Owner", "owner@example.com", PASSWORD)

    def login(self):
        mailer.outbox.clear()
        self.client.post("/login", data={"email": "owner@example.com", "password": PASSWORD})
        code = re.search(r"\b(\d{6})\b", mailer.outbox[0].get_content()).group(1)
        return self.client.post("/verify-otp", data={"code": code}, follow_redirects=True)


class AuthTests(WebTestCase):
    def test_public_pages_and_protected_redirect(self):
        for url in ("/", "/login"):
            self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_registration_is_closed_after_the_owner_exists(self):
        response = self.client.get("/register", follow_redirects=True)
        self.assertIn(b"already been set up", response.data)

    def test_login_sends_otp_to_the_account_email_then_opens_dashboard(self):
        mailer.outbox.clear()
        response = self.client.post("/login", data={"email": "owner@example.com", "password": PASSWORD},
                                    follow_redirects=True)
        self.assertIn(b"Enter your code", response.data)
        self.assertEqual(mailer.outbox[0]["To"], "owner@example.com")
        self.assertEqual(self.client.get("/dashboard").status_code, 302)  # not logged in until the OTP is entered
        page = self.login()
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Dashboard", page.data)

    def test_email_failure_is_reported_without_crashing(self):
        with mock.patch("mailer.send_mail", side_effect=OSError("boom")):
            response = self.client.post("/login", data={"email": "owner@example.com", "password": PASSWORD},
                                        follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"couldn&#39;t send the email", response.data)

    def test_wrong_otp_is_rejected(self):
        self.client.post("/login", data={"email": "owner@example.com", "password": PASSWORD})
        response = self.client.post("/verify-otp", data={"code": "000000"}, follow_redirects=True)
        self.assertTrue(b"Wrong code" in response.data or b"expired" in response.data)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_lockout_after_repeated_wrong_passwords(self):
        for _ in range(5):
            self.client.post("/login", data={"email": "owner@example.com", "password": "bad"})
        response = self.client.post("/login", data={"email": "owner@example.com", "password": PASSWORD},
                                    follow_redirects=True)
        self.assertIn(b"Too many failed attempts", response.data)

    def test_logout_ends_the_session(self):
        self.login()
        self.client.post("/logout")
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_friendly_404_and_security_headers(self):
        response = self.client.get("/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Page not found", response.data)
        self.assertNotIn(b"Traceback", response.data)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


class PagesTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.barber = Barber.find(Barber.create({"name": "Juan", "phone": "", "commission_rate": "50"}))
        self.service = Service.find(Service.create({"name": "Haircut", "price": "100"}))
        self.product = Product.find(Product.create({"name": "Pomade", "price": "250", "stock": "10"}))
        self.login()

    def test_every_page_renders(self):
        for url in ("/dashboard", "/profile", "/queue", "/barbers", "/services", "/products", "/transactions",
                    "/barbers/add", "/services/add", "/products/add", "/transactions/add",
                    f"/barbers/{self.barber.id}/edit", f"/products/{self.product.id}/edit"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_product_only_sale_and_stock(self):
        response = self.client.post("/transactions/add", follow_redirects=True, data={
            "barber_id": "", "service_id": "", "product_id": self.product.id, "product_qty": "2",
            "customer_name": "", "amount": "500", "payment_method": "Cash"})
        self.assertIn(b"Transaction added", response.data)
        self.assertIn(b"Pomade x2", response.data)
        self.assertEqual(Product.find(self.product.id).stock, 8)

    def test_empty_sale_is_rejected(self):
        response = self.client.post("/transactions/add", follow_redirects=True, data={
            "barber_id": "", "service_id": "", "product_id": "", "product_qty": "",
            "customer_name": "", "amount": "100", "payment_method": "Cash"})
        self.assertIn(b"Choose a service or a product", response.data)

    def test_queue_done_is_blocked_until_payment_is_recorded(self):
        self.client.post("/queue/add", data={"customer_name": "Migs", "service_id": self.service.id,
                                             "barber_id": self.barber.id})
        entry = QueueEntry.today()[0]
        self.client.post(f"/queue/{entry.id}/status", data={"status": "Serving", "barber_id": self.barber.id})
        page = self.client.post(f"/queue/{entry.id}/status", data={"status": "Done"}, follow_redirects=True)
        self.assertIn(b"Record the payment first", page.data)
        self.assertEqual(QueueEntry.today()[0].status, "Serving")
        self.client.post("/transactions/add", data={
            "queue_id": entry.id, "barber_id": self.barber.id, "service_id": self.service.id, "product_id": "",
            "product_qty": "", "customer_name": "Migs", "amount": "100", "payment_method": "Cash"})
        page = self.client.get("/queue")
        self.assertIn(b"Paid", page.data)
        self.client.post(f"/queue/{entry.id}/status", data={"status": "Done"})
        self.assertEqual(QueueEntry.today()[0].status, "Done")

    def test_profile_password_rules(self):
        response = self.client.post("/profile", follow_redirects=True, data={
            "action": "password", "current": PASSWORD, "new_password": "weakpass", "confirm": "weakpass"})
        self.assertIn(b"at least one letter and one number", response.data)


if __name__ == "__main__":
    unittest.main()
