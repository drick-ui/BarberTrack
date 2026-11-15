"""Email test.
  python test_email.py            -> send a test email to MAIL_USERNAME
  python test_email.py --debug    -> same, but prints the whole SMTP conversation (to find where it fails)"""
import smtplib
import sys
from email.message import EmailMessage

from config import BASE_DIR, Config

user, password = Config.MAIL_USERNAME, Config.MAIL_PASSWORD
if not user or not password:
    sys.exit("MAIL_USERNAME or MAIL_PASSWORD is missing. Fill them in your .env file.")

msg = EmailMessage()
msg["Subject"] = "BarberTrack test email"
msg["From"] = user
msg["To"] = user
msg.set_content("Your email setup works. This is where the BarberTrack OTP will arrive.")

mode = "SSL" if Config.MAIL_USE_SSL else "STARTTLS"
print("Settings in use:")
print(f"  .env file found : {(BASE_DIR / '.env').exists()}")
print(f"  server          : {Config.MAIL_SERVER}")
print(f"  port / mode     : {Config.MAIL_PORT} / {mode}")
print(f"  username        : {user}")
print(f"  password length : {len(password)} (a Gmail App Password has 16 characters)")
if Config.MAIL_PORT == 465 and not Config.MAIL_USE_SSL:
    print("  WARNING: port 465 needs MAIL_USE_SSL=1 in .env (otherwise the server hangs up).")
if Config.MAIL_PORT == 587 and Config.MAIL_USE_SSL:
    print("  WARNING: port 587 must NOT use MAIL_USE_SSL. Remove that line or use port 465.")
if len(password) != 16:
    print("  WARNING: the App Password is not 16 characters. Copy it again from Google.")
print("Connecting ...")
server = None
try:
    server = smtplib.SMTP_SSL(timeout=20) if Config.MAIL_USE_SSL else smtplib.SMTP(timeout=20)
    if "--debug" in sys.argv:
        server.set_debuglevel(1)
    server.connect(Config.MAIL_SERVER, Config.MAIL_PORT)
    if not Config.MAIL_USE_SSL:
        server.starttls()
    server.login(user, password)
    server.send_message(msg)
    print(f"OK! A test email was sent to {user}. Check the Inbox (and Spam).")
except smtplib.SMTPAuthenticationError:
    print("FAILED: Wrong email or App Password. Use the 16-character App Password "
          "(not your normal Gmail password) and make sure 2-Step Verification is on.")
except smtplib.SMTPServerDisconnected:
    print("FAILED: The connection was closed. Run again with --debug and send the output.\n"
          "Usual causes: antivirus 'email shield', VPN/proxy, or firewall software.")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
finally:
    if server is not None:
        try:
            server.close()
        except Exception:
            pass
