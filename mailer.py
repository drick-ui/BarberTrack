"""Sends email with Python's smtplib (the same code path as test_email.py)."""
import smtplib
from email.message import EmailMessage

outbox = []  # when MAIL_SUPPRESS_SEND is on (tests) messages are stored here instead of being sent


def send_mail(config, subject, recipient, body):
    """Send one plain-text email using the MAIL_* settings. Raises an exception if it fails."""
    sender = config.get("MAIL_DEFAULT_SENDER") or config.get("MAIL_USERNAME")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    if config.get("MAIL_SUPPRESS_SEND"):
        outbox.append(message)
        return

    use_ssl = config.get("MAIL_USE_SSL")
    connect = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with connect(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=20) as server:
        if not use_ssl:
            server.starttls()
        if config.get("MAIL_USERNAME") and config.get("MAIL_PASSWORD"):
            server.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
        server.send_message(message)
