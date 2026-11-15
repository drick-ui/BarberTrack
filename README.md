# BarberTrack (Gunting Master)

Barbershop financial record and queue system for the shop owner.
Flask + MySQL (XAMPP). HTML in `templates/`, CSS in `static/css/`, JavaScript in `static/js/`.

## Setup
1. Start **MySQL** (and Apache for phpMyAdmin) in the XAMPP Control Panel.
2. Open http://localhost/phpmyadmin → **Import** → choose `database.sql` → **Import**.
   *(Existing database from an older version? Import `migration_security.sql` instead.)*
3. Install the packages:
   ```
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your Gmail and its **App Password**
   (Google Account → Security → 2-Step Verification → App passwords).
5. Run the app: `python app.py` → http://127.0.0.1:5000
6. Run the tests (no MySQL needed): `python -m unittest discover -s tests -t .`

`.env` is ignored by Git. Set `APP_DEBUG=0` for the defense so errors never show a stack trace.

## Features
- Owner-only access: the first registration creates the owner account, then registration closes.
- Login = email + password, then a 6-digit OTP sent by email (5 minutes, 5 tries, resend with cooldown).
- Dashboard (sales, commissions, shop share), profile (details, photo, password).
- CRUD for Barbers, Services, Products and Transactions (commission on services, product stock kept in sync).
- Walk-in queue: waiting → serving → done. *Done* is only allowed after the payment is recorded.

## Security
- Passwords and OTP codes are stored as hashes; password policy: 8+ characters, letters and numbers.
- Login lockout (5 wrong passwords → 5 minutes) and OTP attempt limit; idle session timeout (30 min).
- CSRF protection on every form, parameterized SQL, auto-escaped output, security headers, `no-store` caching.
- Uploads: size limit, extension check and file-signature check.
- Friendly error pages; tracebacks go to the terminal only. Secrets live in `.env`.

## Structure (OOP)
```
app.py            routes + error handling (business rules are NOT here)
config.py         settings read from .env
database.sql      full schema
models/base.py    Database helper + BaseModel (parent class: encapsulated row, generic CRUD)
models/user.py    User  (password check, lockout, OTP)         - inherits BaseModel
models/shop.py    Barber, Service, Product, Transaction, QueueEntry - inherit BaseModel
templates/        HTML (Jinja)          static/css/  all design        static/js/  behaviour
tests/            unit + web tests
```
