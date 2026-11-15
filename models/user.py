"""The User entity: authentication, OTP, lockout, and profile behaviour."""
import math
import re
import secrets
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from .base import BaseModel, Database


class User(BaseModel):
    table = "users"
    columns = ("name", "email", "password_hash", "photo")
    hidden = ("password_hash", "otp_hash", "otp_expires", "otp_attempts",
              "failed_logins", "locked_until")

    OTP_MINUTES = 5
    MAX_OTP_ATTEMPTS = 5
    MAX_LOGIN_ATTEMPTS = 5
    LOCK_MINUTES = 5

    # ----- lookups -----
    @classmethod
    def find_by_email(cls, email):
        row = Database.query("SELECT * FROM users WHERE email=%s", (email,), one=True)
        return cls(row) if row else None

    @classmethod
    def count(cls):
        return Database.query("SELECT COUNT(*) AS n FROM users", one=True)["n"]

    # ----- registration and passwords -----
    @staticmethod
    def password_problem(password):
        """Return a message if the password is too weak, otherwise None."""
        if len(password) < 8:
            return "Password must be at least 8 characters long."
        if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            return "Password must contain at least one letter and one number."
        return None

    @classmethod
    def register(cls, name, email, password):
        new_id = cls.create({"name": name, "email": email, "photo": "",
                             "password_hash": generate_password_hash(password)})
        return cls.find(new_id)

    def check_password(self, password):
        return check_password_hash(self._row["password_hash"], password)

    def change_password(self, new_password):
        self._row["password_hash"] = generate_password_hash(new_password)
        Database.execute("UPDATE users SET password_hash=%s WHERE id=%s",
                         (self._row["password_hash"], self.id))

    # ----- login throttling -----
    @property
    def is_locked(self):
        until = self._row.get("locked_until")
        return bool(until and until > datetime.now())

    @property
    def lock_minutes_left(self):
        until = self._row.get("locked_until")
        if not until:
            return 0
        return max(1, math.ceil((until - datetime.now()).total_seconds() / 60))

    def register_failed_login(self):
        attempts = (self._row.get("failed_logins") or 0) + 1
        if attempts >= self.MAX_LOGIN_ATTEMPTS:
            until = datetime.now() + timedelta(minutes=self.LOCK_MINUTES)
            Database.execute("UPDATE users SET failed_logins=0, locked_until=%s WHERE id=%s",
                             (until, self.id))
            self._row.update(failed_logins=0, locked_until=until)
        else:
            Database.execute("UPDATE users SET failed_logins=%s WHERE id=%s", (attempts, self.id))
            self._row["failed_logins"] = attempts

    def clear_login_failures(self):
        Database.execute("UPDATE users SET failed_logins=0, locked_until=NULL WHERE id=%s", (self.id,))
        self._row.update(failed_logins=0, locked_until=None)

    @classmethod
    def authenticate(cls, email, password):
        """Return (user, status). status is 'ok', 'invalid' or 'locked'."""
        user = cls.find_by_email(email)
        if user is None:
            return None, "invalid"
        if user.is_locked:
            return user, "locked"
        if user.check_password(password):
            user.clear_login_failures()
            return user, "ok"
        user.register_failed_login()
        return user, "invalid"

    # ----- one-time password (second factor) -----
    def issue_otp(self):
        """Create a 6-digit code, store only its hash, and return the plain code to be sent."""
        code = f"{secrets.randbelow(10**6):06d}"
        expires = datetime.now() + timedelta(minutes=self.OTP_MINUTES)
        Database.execute("UPDATE users SET otp_hash=%s, otp_expires=%s, otp_attempts=0 WHERE id=%s",
                         (generate_password_hash(code), expires, self.id))
        return code

    def verify_otp(self, code):
        """Return 'ok', 'invalid', 'expired' or 'locked'."""
        self.refresh()
        row = self._row
        expires = row.get("otp_expires")
        if not row.get("otp_hash") or not expires or expires < datetime.now():
            return "expired"
        if (row.get("otp_attempts") or 0) >= self.MAX_OTP_ATTEMPTS:
            return "locked"
        if check_password_hash(row["otp_hash"], code):
            Database.execute("UPDATE users SET otp_hash=NULL, otp_expires=NULL, otp_attempts=0 "
                             "WHERE id=%s", (self.id,))
            return "ok"
        Database.execute("UPDATE users SET otp_attempts=otp_attempts+1 WHERE id=%s", (self.id,))
        return "invalid"

    # ----- profile -----
    def update_profile(self, name, email):
        Database.execute("UPDATE users SET name=%s, email=%s WHERE id=%s", (name, email, self.id))
        self._row.update(name=name, email=email)

    def set_photo(self, filename):
        Database.execute("UPDATE users SET photo=%s WHERE id=%s", (filename, self.id))
        self._row["photo"] = filename
