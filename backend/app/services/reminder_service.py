"""Scheduled email reminder service for confirmed appointments.

Manages persistent reminder jobs in the `appointment_reminders` ledger table,
ensuring 24-hour and 2-hour reminders are delivered reliably without duplicate sends
and surviving application restarts.
"""
from datetime import datetime, timedelta
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.timeutils import now_local
from app.models import Appointment, AppointmentReminder
from app.models.appointment import (
    REMINDER_STATUS_CANCELLED,
    REMINDER_STATUS_FAILED,
    REMINDER_STATUS_PENDING,
    REMINDER_STATUS_PROCESSING,
    REMINDER_STATUS_SENT,
    REMINDER_STATUS_SKIPPED,
    REMINDER_TYPE_2H,
    REMINDER_TYPE_24H,
    STATUS_CONFIRMED,
)
from app.services.notification_service import (
    BaseEmailProvider,
    format_reminder_email,
    get_email_provider,
)

logger = logging.getLogger(__name__)


def schedule_reminders(db: Session, appt: Appointment) -> list[AppointmentReminder]:
    """Schedules 24h and 2h reminders for a confirmed appointment.

    Idempotent: uses the unique constraint (appointment_id, reminder_type, appointment_start_at).
    """
    if appt.status != STATUS_CONFIRMED:
        return []

    now = now_local()
    reminders: list[AppointmentReminder] = []
    specs = [
        (REMINDER_TYPE_24H, appt.start_at - timedelta(hours=24)),
        (REMINDER_TYPE_2H, appt.start_at - timedelta(hours=2)),
    ]

    for r_type, sched_time in specs:
        # Check if already exists for this appointment, type, and start time
        existing = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appt.id,
                AppointmentReminder.reminder_type == r_type,
                AppointmentReminder.appointment_start_at == appt.start_at,
            )
        ).scalar_one_or_none()

        if existing:
            reminders.append(existing)
            continue

        # Determine initial status:
        # If the appointment itself is already past, mark skipped
        if appt.start_at <= now:
            init_status = REMINDER_STATUS_SKIPPED
            err = "Appointment date/time is in the past"
        # If 24h reminder is already within 2h of appointment, skip 24h reminder
        elif r_type == REMINDER_TYPE_24H and now >= appt.start_at - timedelta(hours=2):
            init_status = REMINDER_STATUS_SKIPPED
            err = "Confirmed within 2-hour window; 24h reminder skipped"
        else:
            init_status = REMINDER_STATUS_PENDING
            err = None

        reminder = AppointmentReminder(
            appointment_id=appt.id,
            reminder_type=r_type,
            scheduled_for=sched_time,
            appointment_start_at=appt.start_at,
            status=init_status,
            last_error=err,
            created_at=now,
            updated_at=now,
        )
        db.add(reminder)
        reminders.append(reminder)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrently created by another process; fetch existing records
        reminders = list(
            db.execute(
                select(AppointmentReminder).where(
                    AppointmentReminder.appointment_id == appt.id,
                    AppointmentReminder.appointment_start_at == appt.start_at,
                )
            ).scalars()
        )
    except Exception as e:
        db.rollback()
        logger.error("Failed to schedule reminders for appointment %s: %s", appt.reference_code, str(e))

    return reminders


def handle_reschedule(db: Session, appt: Appointment) -> None:
    """Cancels obsolete reminders for an appointment that was rescheduled and creates new ones if confirmed."""
    try:
        pending_reminders = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appt.id,
                AppointmentReminder.status.in_([REMINDER_STATUS_PENDING, REMINDER_STATUS_PROCESSING]),
                AppointmentReminder.appointment_start_at != appt.start_at,
            )
        ).scalars().all()

        for r in pending_reminders:
            r.status = REMINDER_STATUS_CANCELLED
            r.last_error = f"Appointment rescheduled to {appt.start_at:%Y-%m-%d %H:%M}"
            r.updated_at = now_local()

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to cancel obsolete reminders on reschedule for %s: %s", appt.reference_code, str(e))

    if appt.status == STATUS_CONFIRMED:
        schedule_reminders(db, appt)


def cancel_pending_reminders(db: Session, appt_id: int, reason: str = "Appointment status changed") -> None:
    """Cancels all pending/processing reminders when an appointment is cancelled or completed."""
    try:
        pending_reminders = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appt_id,
                AppointmentReminder.status.in_([REMINDER_STATUS_PENDING, REMINDER_STATUS_PROCESSING]),
            )
        ).scalars().all()

        for r in pending_reminders:
            r.status = REMINDER_STATUS_CANCELLED
            r.last_error = reason
            r.updated_at = now_local()

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to cancel reminders for appointment id %s: %s", appt_id, str(e))


def process_due_reminders(
    db: Session,
    now: datetime | None = None,
    settings: Settings | None = None,
    email_provider: BaseEmailProvider | None = None,
) -> int:
    """Finds, claims, and delivers due appointment reminders.

    Prevents race conditions:
    1. Reclaims stale 'processing' jobs older than reminder_stale_claim_minutes.
    2. Atomically selects and claims due pending reminders, setting status='processing'.
    3. Commits claim immediately so DB transactions are NOT held during slow SMTP network calls.
    4. Performs SMTP dispatch.
    5. Records success ('sent') or failure ('pending' with backoff or 'failed' if max attempts reached).
    """
    s = settings or get_settings()
    now = now or now_local()
    ep = email_provider or get_email_provider(s)

    # 1. Recover stale processing claims (in case worker previously crashed mid-send)
    stale_cutoff = now - timedelta(minutes=s.reminder_stale_claim_minutes)
    try:
        stale_reminders = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.status == REMINDER_STATUS_PROCESSING,
                AppointmentReminder.updated_at < stale_cutoff,
            )
        ).scalars().all()

        for sr in stale_reminders:
            sr.status = REMINDER_STATUS_PENDING
            sr.last_error = "Reclaimed from stale processing claim"
            sr.updated_at = now
        if stale_reminders:
            db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to recover stale processing reminders: %s", str(e))

    # 2. Query due reminders
    stmt = (
        select(AppointmentReminder)
        .where(
            AppointmentReminder.status == REMINDER_STATUS_PENDING,
            AppointmentReminder.scheduled_for <= now,
            AppointmentReminder.attempts < s.reminder_max_retries,
        )
        .order_by(AppointmentReminder.scheduled_for.asc())
        .limit(50)
    )

    # Use SKIP LOCKED on MySQL/PostgreSQL to prevent multiple workers from blocking or double-processing
    is_sqlite = "sqlite" in str(db.bind.url) if db.bind else False
    if not is_sqlite:
        stmt = stmt.with_for_update(skip_locked=True)

    try:
        candidates = list(db.execute(stmt).scalars().all())
    except Exception as e:
        logger.error("Failed to query due reminders: %s", str(e))
        return 0

    if not candidates:
        return 0

    claimed: list[int] = []
    for r in candidates:
        appt = r.appointment
        if not appt:
            r.status = REMINDER_STATUS_CANCELLED
            r.last_error = "Appointment deleted"
            r.updated_at = now
            continue

        # Eligibility Check 1: Appointment must be Confirmed
        if appt.status != STATUS_CONFIRMED:
            r.status = REMINDER_STATUS_CANCELLED
            r.last_error = f"Appointment is {appt.status}, not confirmed"
            r.updated_at = now
            continue

        # Eligibility Check 2: Start time must match the reminder's target time
        if appt.start_at != r.appointment_start_at:
            r.status = REMINDER_STATUS_CANCELLED
            r.last_error = "Appointment start time changed"
            r.updated_at = now
            continue

        # Eligibility Check 3: Appointment must still be in the future
        if appt.start_at <= now:
            r.status = REMINDER_STATUS_SKIPPED
            r.last_error = "Appointment has already occurred"
            r.updated_at = now
            continue

        # Eligibility Check 4: Obsolete 24h reminder check (if within 2h window)
        if r.reminder_type == REMINDER_TYPE_24H and now >= appt.start_at - timedelta(hours=2):
            r.status = REMINDER_STATUS_SKIPPED
            r.last_error = "Obsolete (within 2-hour window)"
            r.updated_at = now
            continue

        # Eligibility Check 5: Visitor must have an email
        if not appt.visitor or not appt.visitor.email:
            r.status = REMINDER_STATUS_SKIPPED
            r.last_error = "Visitor has no email address"
            r.updated_at = now
            continue

        # Claim the reminder atomically
        r.status = REMINDER_STATUS_PROCESSING
        r.attempts += 1
        r.updated_at = now
        claimed.append(r.id)

    # Commit claims to release table/row locks before doing SMTP network calls
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit reminder claims: %s", str(e))
        return 0

    # 3. Deliver claimed reminders outside the locking transaction
    delivered_count = 0
    for rem_id in claimed:
        try:
            rem = db.get(AppointmentReminder, rem_id)
            if not rem or rem.status != REMINDER_STATUS_PROCESSING:
                continue

            appt = rem.appointment
            subject, text_body, html_body = format_reminder_email(
                appt, s.app_name, reminder_type=rem.reminder_type
            )

            # Send via provider without holding DB locks
            ok, status_msg = ep.send(appt.visitor.email, subject, text_body, html_body)

            if ok:
                rem.status = REMINDER_STATUS_SENT
                rem.sent_at = now_local()
                rem.last_error = None
                delivered_count += 1
            else:
                if rem.attempts >= s.reminder_max_retries:
                    rem.status = REMINDER_STATUS_FAILED
                    rem.last_error = f"SMTP error ({status_msg}) after {rem.attempts} attempts"
                else:
                    rem.status = REMINDER_STATUS_PENDING
                    rem.scheduled_for = now_local() + timedelta(seconds=s.reminder_retry_backoff_seconds)
                    rem.last_error = f"Attempt {rem.attempts} failed: {status_msg}"

            rem.updated_at = now_local()
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Error delivering reminder id %s: %s", rem_id, str(e))
            try:
                rem = db.get(AppointmentReminder, rem_id)
                if rem:
                    rem.status = REMINDER_STATUS_PENDING if rem.attempts < s.reminder_max_retries else REMINDER_STATUS_FAILED
                    rem.last_error = str(e)[:255]
                    rem.updated_at = now_local()
                    db.commit()
            except Exception:
                db.rollback()

    return delivered_count
