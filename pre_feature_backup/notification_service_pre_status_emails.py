"""Pluggable notification service for SMS and Email confirmations.

Providers are configured via environment variables. If credentials are not configured,
development providers are used which clearly report 'not_configured' status and never
fake delivery.
"""
from abc import ABC, abstractmethod
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
import json
import logging
import smtplib
import ssl
from typing import NamedTuple
import urllib.parse
import urllib.request
import urllib.error

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.appointment import Appointment

logger = logging.getLogger(__name__)


class NotificationResult(NamedTuple):
    email_status: str  # "sent", "failed", "not_configured", "skipped"
    sms_status: str    # "sent", "failed", "not_configured"
    message: str       # Honest user-facing explanation for confirmation page


class BaseEmailProvider(ABC):
    @abstractmethod
    def send(self, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> tuple[bool, str]:
        """Returns (success: bool, status: str)"""
        pass


class BaseSMSProvider(ABC):
    @abstractmethod
    def send(self, to_phone: str, message: str) -> tuple[bool, str]:
        """Returns (success: bool, status: str)"""
        pass


class DevelopmentEmailProvider(BaseEmailProvider):
    def send(self, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> tuple[bool, str]:
        logger.info("Development mode: SMTP is not configured. Email not sent to %s (Subject: %s)", to_email, subject)
        return False, "not_configured"


class SMTPEmailProvider(BaseEmailProvider):
    def __init__(self, host: str, port: int, from_email: str, user: str | None = None,
                 password: str | None = None, use_tls: bool = True, use_ssl: bool = False,
                 timeout: int = 10, display_name: str | None = None):
        self.host = host
        self.port = port
        self.from_email = from_email
        self.user = user.strip() if user else None
        # Clean potential spaces from Google App Passwords (e.g. 'xxxx yyyy zzzz wwww' -> 'xxxxyyyyzzzzwwww')
        self.password = password.replace(" ", "").strip() if password else None
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.display_name = display_name

    def send(self, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> tuple[bool, str]:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            if self.display_name:
                msg["From"] = formataddr((self.display_name, self.from_email))
            else:
                msg["From"] = self.from_email
            msg["To"] = to_email
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            if html_body:
                msg.attach(MIMEText(html_body, "html", "utf-8"))

            if self.use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context) as server:
                    if self.user and self.password:
                        server.login(self.user, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                    if self.use_tls:
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                    if self.user and self.password:
                        server.login(self.user, self.password)
                    server.send_message(msg)

            logger.info("Confirmation email sent successfully to %s", to_email)
            return True, "sent"
        except Exception as e:
            logger.error("Failed to send email to %s: %s", to_email, str(e))
            return False, "failed"


class DevelopmentSMSProvider(BaseSMSProvider):
    def send(self, to_phone: str, message: str) -> tuple[bool, str]:
        logger.info("Development mode: SMS gateway is not configured. SMS not sent to %s", to_phone)
        return False, "not_configured"


class TwilioSMSProvider(BaseSMSProvider):
    def __init__(self, account_sid: str, auth_token: str, from_number: str, timeout: int = 5):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.timeout = timeout

    def send(self, to_phone: str, message: str) -> tuple[bool, str]:
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
            data = urllib.parse.urlencode({
                "To": to_phone,
                "From": self.from_number,
                "Body": message,
            }).encode("utf-8")

            req = urllib.request.Request(url, data=data, method="POST")
            auth_header = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", f"Basic {auth_header}")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    logger.info("SMS sent via Twilio to %s", to_phone)
                    return True, "sent"
                logger.error("Twilio returned non-200 status: %s", resp.status)
                return False, "failed"
        except Exception as e:
            logger.error("Failed to send SMS via Twilio to %s: %s", to_phone, str(e))
            return False, "failed"


class GenericHttpSMSProvider(BaseSMSProvider):
    def __init__(self, url: str, api_key: str | None = None, sender_id: str | None = None, timeout: int = 5):
        self.url = url
        self.api_key = api_key
        self.sender_id = sender_id
        self.timeout = timeout

    def send(self, to_phone: str, message: str) -> tuple[bool, str]:
        try:
            payload = {
                "to": to_phone,
                "message": message,
                "sender": self.sender_id or "RECEPTION",
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(self.url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
                req.add_header("X-API-Key", self.api_key)

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    logger.info("SMS sent via generic HTTP gateway to %s", to_phone)
                    return True, "sent"
                return False, "failed"
        except Exception as e:
            logger.error("Failed to send SMS via HTTP gateway to %s: %s", to_phone, str(e))
            return False, "failed"


def get_email_provider(settings: Settings | None = None) -> BaseEmailProvider:
    s = settings or get_settings()
    if s.smtp_host:
        clean_pwd = s.smtp_password.replace(" ", "").strip() if s.smtp_password else None
        # If user is configured (like Gmail SMTP) but password is missing/empty, fall back safely to avoid failed relay attempts
        if s.smtp_user and not clean_pwd:
            logger.warning(
                "SMTP host is configured with user '%s' but SMTP_PASSWORD is not set. "
                "Falling back to DevelopmentEmailProvider until password is provided.",
                s.smtp_user,
            )
            return DevelopmentEmailProvider()

        from_email = s.smtp_from_email or (f"reception@{s.smtp_host}" if not s.smtp_user else s.smtp_user)
        return SMTPEmailProvider(
            host=s.smtp_host,
            port=s.smtp_port,
            from_email=from_email,
            user=s.smtp_user,
            password=clean_pwd,
            use_tls=s.smtp_use_tls,
            use_ssl=s.smtp_use_ssl,
            timeout=s.smtp_timeout_seconds,
            display_name=s.app_name,
        )
    return DevelopmentEmailProvider()


def get_sms_provider(settings: Settings | None = None) -> BaseSMSProvider:
    s = settings or get_settings()
    provider_name = (s.sms_provider or "auto").lower()

    if provider_name in ("twilio", "auto") and s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number:
        return TwilioSMSProvider(
            account_sid=s.twilio_account_sid,
            auth_token=s.twilio_auth_token,
            from_number=s.twilio_from_number,
            timeout=s.sms_timeout_seconds,
        )
    elif provider_name in ("generic_http", "auto") and s.sms_gateway_url:
        return GenericHttpSMSProvider(
            url=s.sms_gateway_url,
            api_key=s.sms_api_key,
            sender_id=s.sms_sender_id,
            timeout=s.sms_timeout_seconds,
        )
    return DevelopmentSMSProvider()


def format_appointment_sms(appt: Appointment, app_name: str) -> str:
    start_str = appt.start_at.strftime("%d %b %Y at %I:%M %p")
    return (
        f"Your appointment request ({appt.reference_code}) for {start_str} with {appt.department.name} "
        f"has been received. Status: Pending staff approval. Check progress anytime on our website using your "
        f"reference code and mobile number."
    )


def format_appointment_email(appt: Appointment, app_name: str) -> tuple[str, str, str]:
    subject = f"Appointment Request Received - {appt.reference_code}"
    start_str = appt.start_at.strftime("%A, %d %B %Y at %I:%M %p")
    visitor_name = appt.visitor.full_name

    text_body = f"""Dear {visitor_name},

Thank you for requesting an appointment with {app_name}.

Appointment Details:
- Reference Code: {appt.reference_code}
- Date & Time: {start_str}
- Department: {appt.department.name}
- With: {appt.staff.full_name}
- Status: Pending Staff Approval

Important Information:
Your request is currently waiting for confirmation by the reception team.
To check your appointment status at any time, visit our website's "Check Status" page and enter:
1. Reference Code: {appt.reference_code}
2. Mobile Number: {appt.visitor.phone}

Please keep your reference code for your records.

Warm regards,
Reception Team
{app_name}
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{subject}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.5; color: #334155; margin: 0; padding: 24px;">
  <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px;">
    <h2 style="color: #4338ca; margin-top: 0;">Appointment Request Received</h2>
    <p>Dear <strong>{visitor_name}</strong>,</p>
    <p>Your appointment request has been saved and is currently <strong>Pending Staff Approval</strong>.</p>
    
    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 20px 0;">
      <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
        <tr><td style="color: #64748b; padding: 4px 0;">Reference Code:</td><td style="font-family: monospace; font-weight: bold; color: #1e293b;">{appt.reference_code}</td></tr>
        <tr><td style="color: #64748b; padding: 4px 0;">When:</td><td style="font-weight: 600;">{start_str}</td></tr>
        <tr><td style="color: #64748b; padding: 4px 0;">With:</td><td>{appt.staff.full_name}</td></tr>
        <tr><td style="color: #64748b; padding: 4px 0;">Department:</td><td>{appt.department.name}</td></tr>
        <tr><td style="color: #64748b; padding: 4px 0;">Status:</td><td><span style="background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 9999px; font-size: 12px; font-weight: 600;">Pending Approval</span></td></tr>
      </table>
    </div>

    <p style="font-size: 14px;">You can check your status anytime on our website using your reference code <code>{appt.reference_code}</code> and your phone number.</p>
    <p style="font-size: 12px; color: #94a3b8; margin-top: 24px; border-top: 1px solid #e2e8f0; padding-top: 12px;">This is an automated notification from {app_name}. Please do not reply directly to this email.</p>
  </div>
</body>
</html>
"""
    return subject, text_body, html_body


def send_booking_notifications(
    db: Session,
    appointment: Appointment,
    settings: Settings | None = None,
    email_provider: BaseEmailProvider | None = None,
    sms_provider: BaseSMSProvider | None = None,
) -> NotificationResult:
    """Dispatches SMS and Email notifications. Never raises or breaks appointment save."""
    s = settings or get_settings()
    ep = email_provider or get_email_provider(s)
    sp = sms_provider or get_sms_provider(s)

    sms_status = appointment.sms_status or "pending"
    email_status = appointment.email_status or "pending"

    # Avoid duplicate sends if retried
    if sms_status != "sent" and appointment.visitor.phone:
        sms_text = format_appointment_sms(appointment, s.app_name)
        ok, res_status = sp.send(appointment.visitor.phone, sms_text)
        sms_status = "sent" if ok else res_status

    if email_status != "sent":
        if appointment.visitor.email:
            subj, text_b, html_b = format_appointment_email(appointment, s.app_name)
            ok, res_status = ep.send(appointment.visitor.email, subj, text_b, html_b)
            email_status = "sent" if ok else res_status
        else:
            email_status = "skipped"

    # Persist notification status
    appointment.sms_status = sms_status
    appointment.email_status = email_status
    try:
        db.commit()
    except Exception as e:
        logger.error("Failed to persist notification status: %s", str(e))
        db.rollback()

    # Determine user-facing notification summary message
    is_dev = (sms_status == "not_configured" and (email_status in ("not_configured", "skipped")))
    all_sent = (sms_status == "sent" and (email_status in ("sent", "skipped")))

    if all_sent:
        if email_status == "sent":
            msg = f"Confirmation notifications sent by SMS to {appointment.visitor.phone} and by email to {appointment.visitor.email}."
        else:
            msg = f"Confirmation notification sent by SMS to {appointment.visitor.phone}."
    elif sms_status == "sent":
        msg = f"Confirmation SMS sent to {appointment.visitor.phone}."
    elif email_status == "sent":
        msg = f"Confirmation email sent to {appointment.visitor.email}."
    elif is_dev:
        msg = "Development mode: external SMS/email gateways are not configured. Please save your reference code."
    else:
        msg = "External notifications could not be delivered, but your appointment request is safely saved."

    return NotificationResult(email_status=email_status, sms_status=sms_status, message=msg)
