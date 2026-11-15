"""BarberTrack - Flask application (routes). Business rules live in the models/ package."""
import os
import re
import time
import uuid
from datetime import datetime
from functools import wraps

import pymysql
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import mailer
from config import BASE_DIR, Config
from models import (Barber, Product, QueueEntry, QueueError, Service,
                    Transaction, User)

app = Flask(__name__)
app.config.from_object(Config)
CSRFProtect(app)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_PHOTO = {"png", "jpg", "jpeg", "webp"}
PENDING_LOGIN_SECONDS = 600  # time allowed to enter the OTP after the password step


# =====================================================================
# Request hooks, helpers, and error handling
# =====================================================================
@app.before_request
def load_current_user():
    """Load the logged-in user once per request (None when logged out)."""
    g.user = None
    if request.endpoint == "static":
        return
    uid = session.get("user_id")
    if uid:
        try:
            g.user = User.find(uid)
        except pymysql.err.MySQLError:
            g.user = None
        if g.user is None:
            session.pop("user_id", None)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.endpoint != "static":  # stop the back button from showing pages after logout
        response.headers["Cache-Control"] = "no-store"
    return response


@app.context_processor
def inject_globals():
    try:
        owner_missing = User.count() == 0
    except pymysql.err.MySQLError:
        owner_missing = False

    def versioned_url_for(endpoint, **values):
        """Append the file's modified time to static URLs so browsers never use stale CSS/JS."""
        if endpoint == "static" and values.get("filename"):
            path = os.path.join(app.static_folder, values["filename"])
            if os.path.isfile(path):
                values["v"] = int(os.path.getmtime(path))
        return url_for(endpoint, **values)

    def vendor_exists(local):
        return os.path.isfile(os.path.join(app.static_folder, "vendor", *local.split("/")))

    def vendor(local, cdn_url):
        """Use the copy saved by download_assets.py (works offline); otherwise fall back to the CDN."""
        if vendor_exists(local):
            return versioned_url_for("static", filename=f"vendor/{local}")
        return cdn_url

    return {"current_user": getattr(g, "user", None), "registration_open": owner_missing,
            "url_for": versioned_url_for, "vendor": vendor, "vendor_exists": vendor_exists}


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def render_error(code, message):
    return render_template("error.html", code=code, message=message), code


@app.errorhandler(CSRFError)
def csrf_error(_):
    return render_error(400, "This form has expired or is invalid. Please go back, refresh the page, and try again.")


@app.errorhandler(HTTPException)
def http_error(e):
    messages = {400: "The request could not be understood.", 403: "You do not have permission to do that.",
                404: "Page not found.", 405: "That action is not allowed here.",
                413: "The uploaded file is too large (maximum 2 MB)."}
    return render_error(e.code, messages.get(e.code, "Something went wrong."))


@app.errorhandler(pymysql.err.OperationalError)
def database_error(e):
    code = e.args[0] if e.args else 0
    if code in (2002, 2003, 1045, 1049):  # cannot connect / wrong login / unknown database
        message = "Unable to connect to the database. Make sure MySQL is running in XAMPP and database.sql was imported."
    else:  # e.g. 1054 unknown column = the database is missing a migration
        message = "A database error occurred. The database structure may be out of date."
        if app.debug and len(e.args) > 1:
            message += f" ({e.args[1]})"
    return render_error(500, message)


@app.errorhandler(Exception)
def unexpected_error(_):
    app.logger.exception("Unhandled error")  # the traceback goes to the terminal, never to the browser
    return render_error(500, "Something went wrong on our side. Please try again.")


def send_email(subject, recipient, body):
    """Send an email; returns True on success. Failures are logged (and kept in g.mail_error)."""
    try:
        mailer.send_mail(app.config, subject, recipient, body)
        return True
    except Exception as e:
        g.mail_error = f"{type(e).__name__}: {e}"
        app.logger.warning("Email to %s failed: %s", recipient, g.mail_error, exc_info=True)
        return False


def mail_failure_message():
    text = "We couldn't send the email. Check the Gmail settings in your .env file."
    if app.debug and g.get("mail_error"):  # the real reason is only shown while developing
        text += f" ({g.mail_error})"
    return text


def deliver_otp(user):
    """Create an OTP for the user and email it. Returns True if the email was sent."""
    code = user.issue_otp()
    session["otp_sent_at"] = time.time()
    sent = send_email(
        "BarberTrack login code", user.email,
        f"Hi {user.name},\n\nYour BarberTrack verification code is: {code}\n"
        f"It is valid for {User.OTP_MINUTES} minutes. Do not share it with anyone.")
    if not sent and app.debug:  # development only: lets you keep testing without email
        app.logger.warning("DEV ONLY - OTP for %s is %s", user.email, code)
    return sent


def validate(spec, form):
    """Server-side validation of a form against a field specification."""
    data, errors = {}, []
    for f in spec:
        value = form.get(f["name"], "").strip()
        if not value:
            if f.get("required", True):
                errors.append(f"{f['label']} is required.")
            data[f["name"]] = ""
            continue
        if f["type"] == "number":
            try:
                n = float(value)
            except ValueError:
                errors.append(f"{f['label']} must be a number.")
                continue
            if f.get("step") == "1" and not n.is_integer():
                errors.append(f"{f['label']} must be a whole number.")
                continue
            if n < 0 or n > f.get("max", 1_000_000):
                errors.append(f"{f['label']} is out of range.")
                continue
        data[f["name"]] = value
    return data, errors


def is_real_image(file, ext):
    """Check the file's first bytes, not just its extension."""
    head = file.stream.read(12)
    file.stream.seek(0)
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def delete_upload(filename):
    if filename:
        path = os.path.join(app.config["UPLOAD_FOLDER"], os.path.basename(filename))
        if os.path.isfile(path):
            os.remove(path)


def mask_email(email):
    name, _, domain = (email or "").partition("@")
    return f"{name[:1]}***@{domain}" if name and domain else ""


# =====================================================================
# Public pages and authentication
# =====================================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if User.count() > 0:  # the system is for the shop owner only
        flash("The owner account has already been set up. Please log in.", "info")
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password, confirm = request.form.get("password", ""), request.form.get("confirm", "")
        errors = []
        if not name:
            errors.append("Name is required.")
        if not EMAIL_RE.match(email):
            errors.append("Invalid email address.")
        elif User.find_by_email(email):
            errors.append("Email is already registered.")
        problem = User.password_problem(password)
        if problem:
            errors.append(problem)
        if password != confirm:
            errors.append("Passwords do not match.")
        if not errors:
            user = User.register(name, email, password)
            send_email("Welcome to BarberTrack!", user.email,
                       f"Hi {user.name},\n\nYour BarberTrack owner account has been created. You may now log in.")
            flash("The owner account has been created. You may now log in.", "success")
            return redirect(url_for("login"))
        for e in errors:
            flash(e, "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user, status = User.authenticate(request.form.get("email", "").strip().lower(),
                                         request.form.get("password", ""))
        if status == "ok":
            session.clear()
            session["pending_user"] = user.id  # password accepted; OTP still required
            session["pending_at"] = time.time()
            if deliver_otp(user):
                flash("A 6-digit verification code was sent to your email.", "info")
            else:
                flash("We couldn't send the email. Check the Gmail settings in your .env file.", "warning")
            return redirect(url_for("verify_otp"))
        if status == "locked":
            flash(f"Too many failed attempts. Try again in {user.lock_minutes_left} minute(s).", "danger")
        else:
            flash("Incorrect email or password.", "danger")
    return render_template("login.html")


def pending_user():
    """The user who passed the password step and still has to enter the OTP."""
    uid = session.get("pending_user")
    if not uid or time.time() - session.get("pending_at", 0) > PENDING_LOGIN_SECONDS:
        session.pop("pending_user", None)
        return None
    return User.find(uid)


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    user = pending_user()
    if user is None:
        flash("Your login session expired. Please log in again.", "warning")
        return redirect(url_for("login"))
    if request.method == "POST":
        result = user.verify_otp(request.form.get("code", "").strip())
        if result == "ok":
            session.clear()
            session["user_id"] = user.id
            session.permanent = True  # enables the idle timeout (SESSION_MINUTES)
            return redirect(url_for("dashboard"))
        flash({"invalid": "Wrong code.",
               "expired": "The code has expired. Please click Resend code.",
               "locked": "Too many wrong codes. Please click Resend code for a new one."}[result], "danger")
    return render_template("otp.html", masked_email=mask_email(user.email))


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    user = pending_user()
    if user is None:
        return redirect(url_for("login"))
    if time.time() - session.get("otp_sent_at", 0) < 30:
        flash("Please wait 30 seconds before requesting another code.", "warning")
    elif deliver_otp(user):
        flash("A new code has been sent.", "info")
    else:
        flash("We couldn't send the email. Check the Gmail settings in your .env file.", "warning")
    return redirect(url_for("verify_otp"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# =====================================================================
# Dashboard and profile
# =====================================================================
@app.route("/dashboard")
@login_required
def dashboard():
    now = datetime.now()
    greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
    queue = QueueEntry.today()
    week = Transaction.sales_by_day(7)
    return render_template("dashboard.html", now=now, greeting=greeting,
                           today=Transaction.summary("day"),
                           month=Transaction.summary("month"),
                           week=week, week_total=sum(d["sales"] for d in week),
                           queue_counts={"waiting": sum(e.status == "Waiting" for e in queue),
                                         "serving": sum(e.status == "Serving" for e in queue)},
                           barbers=Transaction.per_barber_today(),
                           recent=Transaction.all()[:8])


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = g.user
    if request.method == "POST":
        action = request.form.get("action")
        if action == "details":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            other = User.find_by_email(email)
            if not name or not EMAIL_RE.match(email):
                flash("A valid name and email address are required.", "danger")
            elif other and other.id != user.id:
                flash("That email address is already used by another account.", "danger")
            else:
                user.update_profile(name, email)
                photo = request.files.get("photo")
                if photo and photo.filename:
                    ext = photo.filename.rsplit(".", 1)[-1].lower()
                    if ext in ALLOWED_PHOTO and is_real_image(photo, ext):
                        filename = f"{uuid.uuid4().hex}.{ext}"
                        photo.save(os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(filename)))
                        delete_upload(user.photo)
                        user.set_photo(filename)
                    else:
                        flash("Please upload a real PNG, JPG, or WEBP image.", "danger")
                flash("Your profile has been updated.", "success")
        elif action == "password":
            new, confirm = request.form.get("new_password", ""), request.form.get("confirm", "")
            problem = User.password_problem(new)
            if not user.check_password(request.form.get("current", "")):
                flash("Your current password is incorrect.", "danger")
            elif problem:
                flash(problem, "danger")
            elif new != confirm:
                flash("The new passwords do not match.", "danger")
            else:
                user.change_password(new)
                flash("Your password has been changed.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html")


# =====================================================================
# Queue
# =====================================================================
def queue_context():
    entries = QueueEntry.today()
    return {"serving": [e for e in entries if e.status == "Serving"],
            "waiting": [e for e in entries if e.status == "Waiting"],
            "finished": [e for e in entries if e.status in ("Done", "Cancelled")]}


@app.route("/queue")
@login_required
def queue_page():
    return render_template("queue.html", services=Service.all(), barbers=Barber.all(), **queue_context())


@app.route("/queue/add", methods=["POST"])
@login_required
def queue_add():
    name = request.form.get("customer_name", "").strip()[:100]
    service_id = request.form.get("service_id") or None
    barber_id = request.form.get("barber_id") or None
    if (service_id and not Service.find(service_id)) or (barber_id and not Barber.find(barber_id)):
        flash("Invalid service or barber.", "danger")
    else:
        flash(f"Added to the queue: #{QueueEntry.add(name, service_id, barber_id):03d}", "success")
    return redirect(url_for("queue_page"))


@app.route("/queue/<int:entry_id>/status", methods=["POST"])
@login_required
def queue_status(entry_id):
    entry = QueueEntry.find(entry_id) or abort(404)
    action = request.form.get("status")
    try:
        if action == "Serving":
            entry.start(request.form.get("barber_id"))
        elif action == "Done":
            entry.finish()
        elif action == "Cancelled":
            entry.cancel()
        else:
            abort(400)
    except QueueError as e:
        flash(str(e), "danger")
    return redirect(url_for("queue_page"))


# =====================================================================
# CRUD pages (Barbers, Services, Products, Transactions)
# =====================================================================
def register_crud(name, title, singular, model, spec, columns):
    """Create list/add/edit/delete routes for one model from a field specification."""

    def build_fields(values):
        out = []
        for f in spec:
            f = dict(f)
            if callable(f.get("options")):
                f["choices"] = f["options"]()
            f["value"] = values.get(f["name"], "") if values else ""
            out.append(f)
        return out

    @login_required
    def list_view():
        return render_template("list.html", title=title, name=name, columns=columns, rows=model.all())

    @login_required
    def add_view():
        values = request.args  # allows pre-filling from a link (e.g. "Record payment" in the queue)
        queue_id = request.args.get("queue_id") or request.form.get("queue_id")
        if request.method == "POST":
            values = request.form
            data, errors = validate(spec, request.form)
            if not errors and hasattr(model, "check"):
                errors = model.check(data)
            if not errors:
                new_id = model.create(data)
                flash(f"{singular} added.", "success")
                entry = QueueEntry.find(int(queue_id)) if name == "transactions" and str(queue_id).isdigit() else None
                if entry:
                    entry.attach_payment(new_id)  # the queue customer is now marked as paid
                    return redirect(url_for("queue_page"))
                return redirect(url_for(f"{name}_list"))
            for e in errors:
                flash(e, "danger")
        return render_template("form.html", title=f"Add {singular}", queue_id=queue_id,
                               fields=build_fields(values), back=url_for(f"{name}_list"))

    @login_required
    def edit_view(record_id):
        item = model.find(record_id) or abort(404)
        values = item.to_dict()
        if request.method == "POST":
            values = request.form
            data, errors = validate(spec, request.form)
            if not errors and hasattr(model, "check"):
                errors = model.check(data, record_id)
            if not errors:
                model.update(record_id, data)
                flash(f"{singular} updated.", "success")
                return redirect(url_for(f"{name}_list"))
            for e in errors:
                flash(e, "danger")
        return render_template("form.html", title=f"Edit {singular}",
                               fields=build_fields(values), back=url_for(f"{name}_list"))

    @login_required
    def delete_view(record_id):
        try:
            model.delete(record_id)
            flash(f"{singular} deleted.", "info")
        except pymysql.err.IntegrityError:
            flash(f"This {singular.lower()} cannot be deleted because it is used by other records.", "danger")
        return redirect(url_for(f"{name}_list"))

    both = ["GET", "POST"]
    app.add_url_rule(f"/{name}", f"{name}_list", list_view)
    app.add_url_rule(f"/{name}/add", f"{name}_add", add_view, methods=both)
    app.add_url_rule(f"/{name}/<int:record_id>/edit", f"{name}_edit", edit_view, methods=both)
    app.add_url_rule(f"/{name}/<int:record_id>/delete", f"{name}_delete", delete_view, methods=["POST"])


register_crud("barbers", "Barbers", "Barber", Barber, [
    {"name": "name", "label": "Name", "type": "text"},
    {"name": "phone", "label": "Phone", "type": "text", "required": False},
    {"name": "commission_rate", "label": "Commission rate (%)", "type": "number", "max": 100},
], [("name", "Name", None), ("phone", "Phone", None), ("commission_rate", "Commission", "pct")])

register_crud("services", "Services", "Service", Service, [
    {"name": "name", "label": "Service name", "type": "text"},
    {"name": "price", "label": "Price (₱)", "type": "number"},
], [("name", "Service", None), ("price", "Price", "money")])

register_crud("products", "Products", "Product", Product, [
    {"name": "name", "label": "Product name", "type": "text"},
    {"name": "price", "label": "Price (₱)", "type": "number"},
    {"name": "stock", "label": "Stock (qty)", "type": "number", "step": "1"},
], [("name", "Product", None), ("price", "Price", "money"), ("stock", "Stock", None)])

register_crud("transactions", "Transactions", "Transaction", Transaction, [
    {"name": "barber_id", "label": "Barber (for the service)", "type": "select", "required": False,
     "options": lambda: [(b.id, b.name, "") for b in Barber.all()]},
    {"name": "service_id", "label": "Service (optional for product-only sales)", "type": "select",
     "required": False,
     "options": lambda: [(s.id, f"{s.name} (₱{s.price})", s.price) for s in Service.all()]},
    {"name": "product_id", "label": "Product (optional)", "type": "select", "required": False,
     "options": lambda: [(p.id, f"{p.name} (₱{p.price}, stock: {p.stock})", p.price) for p in Product.all()]},
    {"name": "product_qty", "label": "Product quantity", "type": "number", "step": "1", "required": False},
    {"name": "customer_name", "label": "Customer (optional)", "type": "text", "required": False},
    {"name": "amount", "label": "Total amount (₱)", "type": "number"},
    {"name": "payment_method", "label": "Payment method", "type": "select",
     "options": lambda: [(m, m, "") for m in ("Cash", "GCash", "Card")]},
], [("txn_date", "Date", "date"), ("customer_name", "Customer", None), ("barber_name", "Barber", None),
    ("service_name", "Service", None), ("product_label", "Product", None), ("amount", "Amount", "money"),
    ("commission", "Commission", "money"), ("shop_share", "Shop share", "money")])


if __name__ == "__main__":
    env_file = BASE_DIR / ".env"
    # extra_files: the dev server restarts by itself when .env changes
    app.run(debug=app.config["APP_DEBUG"], extra_files=[str(env_file)] if env_file.exists() else None)
