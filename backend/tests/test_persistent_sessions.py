"""Automated tests for Phase 5: Production Readiness and Persistent Conversation Recovery.

Tests verify:
1. Safe persistence of unfinished booking sessions across backend restarts (in-memory wipe).
2. Proper restoration of conversation state at each booking step.
3. Expiration handling (expired sessions reset cleanly without crashes or duplicate bookings).
4. Abandoned and invalid session tokens (safe handling without data leaks).
5. Duplicate submission prevention on retries and resumed sessions.
6. Real-time slot re-check on recovery and confirmation (detecting concurrent bookings or expired lead time).
7. Strict local handling of visitor PII (never sent to Gemini).
8. Gemini fallback during booking flow.
"""
import json
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from app.api.public import get_chat_service
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.timeutils import now_local
from app.models import Appointment, Conversation, Department, Message, Staff, StaffAvailability
from app.services import appointment_service as appts
from app.services.chat_service import (
    NOT_FOUND_REPLY,
    BookingSession,
    ChatService,
    HybridGeminiResponder,
    RuleBasedResponder,
    _booking_sessions,
)
from app.services.gemini_service import GeminiIntent, GeminiInterpretation, GeminiService
from tests.conftest import future_slot, iso


def ask(client, msg: str, token: str | None = None, headers: dict | None = None) -> dict:
    payload = {"message": msg}
    if token:
        payload["session_token"] = token
    r = client.post("/api/public/chat", json=payload, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def get_state(client, token: str) -> dict:
    r = client.get("/api/public/chat", params={"session_token": token})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1. Persistence across backend restarts (in-memory wipe)
# ---------------------------------------------------------------------------

def test_session_persists_across_simulated_backend_restart(client, org):
    """When a visitor is midway through a booking and the backend restarts (in-memory _booking_sessions wiped),
    their unfinished booking state is safely recovered from the database when they return."""
    # Step 1: Start booking
    r1 = ask(client, "I want to book an appointment")
    token = r1["session_token"]
    assert r1["booking_flow"]["step"] == "department"

    # Step 2: Choose department
    r2 = ask(client, "Admissions", token)
    assert r2["booking_flow"]["step"] == "staff"

    # Step 3: Choose staff
    r3 = ask(client, "Dr. Ravi", token)
    assert r3["booking_flow"]["step"] == "date"

    # Verify state is saved in DB
    with SessionLocal() as db:
        convo = db.execute(select(Conversation).where(Conversation.session_token == token)).scalar_one()
        assert convo.booking_step == "date"
        assert convo.booking_state is not None
        saved_data = json.loads(convo.booking_state)
        assert saved_data["department_name"] == "Admissions"
        assert saved_data["staff_name"] == "Dr. Ravi"

    # SIMULATE BACKEND RESTART: Wipe in-memory dictionary completely
    _booking_sessions.clear()
    assert token not in _booking_sessions

    # Step 4: Visitor returns and calls GET /api/public/chat
    recovered = get_state(client, token)
    assert recovered["booking_flow"] is not None
    assert recovered["booking_flow"]["step"] == "date"
    assert recovered["booking_flow"]["staff_name"] == "Dr. Ravi"
    assert "What date would you like to visit" in recovered["reply"]

    # Step 5: Visitor continues booking seamlessly after restart
    _booking_sessions.clear()  # wipe again to ensure POST also restores from DB
    r4 = ask(client, "tomorrow", token)
    assert r4["booking_flow"]["step"] == "slot"
    assert len(r4["suggestions"]) > 0


def test_session_recovery_at_contact_steps(client, org):
    """Verify session recovers accurately at contact collection steps (visitor_name, visitor_phone, visitor_email)."""
    r1 = ask(client, "I want to book an appointment with Dr. Ravi in Admissions tomorrow")
    token = r1["session_token"]
    assert r1["booking_flow"]["step"] == "slot"
    slot_label = r1["suggestions"][0]

    # Select slot -> transitions to visitor_name
    r2 = ask(client, slot_label, token)
    assert r2["booking_flow"]["step"] == "visitor_name"

    # Wipe memory
    _booking_sessions.clear()

    # GET /chat restores visitor_name step
    rec_name = get_state(client, token)
    assert rec_name["booking_flow"]["step"] == "visitor_name"
    assert "full name" in rec_name["reply"].lower()

    # Enter name -> transitions to visitor_phone
    _booking_sessions.clear()
    r3 = ask(client, "Vikram Malhotra", token)
    assert r3["booking_flow"]["step"] == "visitor_phone"

    # Wipe memory and check GET /chat restores visitor_phone step
    _booking_sessions.clear()
    rec_phone = get_state(client, token)
    assert rec_phone["booking_flow"]["step"] == "visitor_phone"
    assert "phone number" in rec_phone["reply"].lower()


# ---------------------------------------------------------------------------
# 2. Expired and abandoned sessions
# ---------------------------------------------------------------------------

def test_expired_session_handling_on_get(client, org):
    """When a session has expired (expires_at in past), get_state resets booking state and informs user."""
    r = ask(client, "I want to book an appointment in Admissions")
    token = r["session_token"]
    assert r["booking_flow"]["step"] == "staff"

    # Manually expire the session in the database
    with SessionLocal() as db:
        convo = db.execute(select(Conversation).where(Conversation.session_token == token)).scalar_one()
        convo.expires_at = now_local() - timedelta(minutes=10)
        db.commit()

    _booking_sessions.clear()

    # Visitor returns after expiration
    recovered = get_state(client, token)
    assert recovered["booking_flow"] is None
    assert "expired" in recovered["reply"].lower()

    # Verify DB was cleaned up
    with SessionLocal() as db:
        convo = db.execute(select(Conversation).where(Conversation.session_token == token)).scalar_one()
        assert convo.booking_state is None
        assert convo.booking_step == "idle"
        assert convo.expires_at is None


def test_expired_session_handling_on_post(client, org):
    """When a session has expired and visitor attempts to submit a step input, it resets safely with a polite message."""
    r = ask(client, "I want to book an appointment with Dr. Ravi in Admissions tomorrow")
    token = r["session_token"]
    assert r["booking_flow"]["step"] == "slot"

    # Expire session in DB
    with SessionLocal() as db:
        convo = db.execute(select(Conversation).where(Conversation.session_token == token)).scalar_one()
        convo.expires_at = now_local() - timedelta(minutes=5)
        db.commit()

    _booking_sessions.clear()

    # User attempts to continue expired session
    r2 = ask(client, "10:00 AM", token)
    assert "expired" in r2["reply"].lower()
    assert r2["booking_flow"] is None


def test_invalid_and_unknown_session_tokens(client, org):
    """Invalid or nonexistent session tokens return a safe greeting and never crash or leak data."""
    # GET with bogus token
    r_get = get_state(client, "totally_nonexistent_token_99999999999")
    assert r_get["intent"] == "greeting"
    assert r_get["booking_flow"] is None

    # POST with bogus token -> creates new session
    r_post = ask(client, "Hello there", "nonexistent_token_88888888888")
    assert r_post["session_token"]
    assert r_post["intent"] == "greeting"


# ---------------------------------------------------------------------------
# 3. Duplicate submission prevention & Retries
# ---------------------------------------------------------------------------

def test_duplicate_submission_prevention_on_retries(client, org):
    """Once an appointment is booked (status=pending), retrying 'confirm' or resuming the session
    returns the existing confirmation and reference code without creating a duplicate."""
    # Complete a full booking
    r1 = ask(client, "I want to book an appointment with Dr. Ravi in Admissions tomorrow")
    token = r1["session_token"]
    slot_label = r1["suggestions"][0]

    ask(client, slot_label, token)
    ask(client, "Deepak Rao", token)
    ask(client, "+919876543299", token)
    ask(client, "deepak@example.com", token)
    ask(client, "General consultation", token)

    # Confirmation
    r_confirm = ask(client, "Confirm", token)
    ref_code = r_confirm["booking_flow"]["reference_code"]
    assert ref_code.startswith("APT-")

    # Verify only 1 appointment exists
    with SessionLocal() as db:
        count = db.execute(select(func.count()).select_from(Appointment).where(Appointment.reference_code == ref_code)).scalar_one()
        assert count == 1

    # SIMULATE SERVER RESTART
    _booking_sessions.clear()

    # Visitor repeats "Confirm" or refreshes and retries
    r_repeat = ask(client, "Confirm", token)
    assert r_repeat["booking_flow"]["reference_code"] == ref_code
    assert "already recorded" in r_repeat["reply"].lower()

    # Verify STILL only 1 appointment exists
    with SessionLocal() as db:
        count = db.execute(select(func.count()).select_from(Appointment).where(Appointment.reference_code == ref_code)).scalar_one()
        assert count == 1

    # GET /chat also returns completed confirmation
    _booking_sessions.clear()
    r_get = get_state(client, token)
    assert r_get["booking_flow"]["reference_code"] == ref_code
    assert "recorded" in r_get["reply"].lower()


# ---------------------------------------------------------------------------
# 4. Slot availability recheck & Concurrency
# ---------------------------------------------------------------------------

def test_slot_recheck_on_session_restore_when_slot_taken(client, org):
    """If visitor paused booking after picking a slot, and someone else books that slot before they resume,
    the system detects the conflict on restore, notifies the visitor, and presents fresh slots."""
    # Visitor A picks slot
    r1 = ask(client, "I want to book an appointment with Dr. Ravi in Admissions tomorrow")
    token_a = r1["session_token"]
    slot_label = r1["suggestions"][0]
    ask(client, slot_label, token_a)  # Visitor A picked slot, now at visitor_name

    # Visitor B books that EXACT same slot directly via API
    with SessionLocal() as db:
        convo_a = db.execute(select(Conversation).where(Conversation.session_token == token_a)).scalar_one()
        data_a = json.loads(convo_a.booking_state)
        slot_start = datetime.fromisoformat(data_a["slot_start"])
        appts.create_appointment(
            db,
            full_name="Competitor Booker",
            phone="+919876543111",
            email="competitor@example.com",
            staff_id=data_a["staff_id"],
            start_at=slot_start,
            purpose="Urgent meeting",
        )

    # SIMULATE RESTART for Visitor A
    _booking_sessions.clear()

    # Visitor A returns to resume
    resumed = get_state(client, token_a)
    assert resumed["booking_flow"]["step"] == "slot"
    assert "no longer available" in resumed["reply"].lower()
    # Conflicted slot must not be in suggestions
    assert slot_label not in resumed["suggestions"]


def test_slot_expired_lead_time_handling_on_confirm(client, org):
    """If a visitor waited so long at the confirmation step that the slot falls within the minimum lead time,
    the system rejects booking, steps back to 'slot', and asks for a new time."""
    r1 = ask(client, "I want to book an appointment with Dr. Ravi in Admissions tomorrow")
    token = r1["session_token"]
    slot_label = r1["suggestions"][0]
    ask(client, slot_label, token)
    ask(client, "Sunita Rao", token)
    ask(client, "+919876543222", token)
    ask(client, "skip", token)
    ask(client, "Discussion", token)  # Now at confirmation

    # Tamper slot_start to be inside lead time (e.g. 5 minutes from now)
    now = now_local()
    with SessionLocal() as db:
        convo = db.execute(select(Conversation).where(Conversation.session_token == token)).scalar_one()
        state = json.loads(convo.booking_state)
        state["slot_start"] = (now + timedelta(minutes=5)).isoformat()
        state["slot_end"] = (now + timedelta(minutes=35)).isoformat()
        convo.booking_state = json.dumps(state)
        db.commit()

    _booking_sessions.clear()

    # Visitor clicks "Confirm"
    r_confirm = ask(client, "Confirm", token)
    assert "expired due to minimum booking lead time" in r_confirm["reply"]
    assert r_confirm["booking_flow"]["step"] == "slot"


# ---------------------------------------------------------------------------
# 5. Cancellation cleans database state
# ---------------------------------------------------------------------------

def test_cancellation_cleans_database_state(client, org):
    """When a visitor cancels an in-progress booking, both memory and database state are cleared."""
    r1 = ask(client, "I want to book an appointment with Dr. Ravi in Admissions tomorrow")
    token = r1["session_token"]
    assert r1["booking_flow"]["step"] == "slot"

    # User cancels
    r_cancel = ask(client, "cancel", token)
    assert "cancelled the appointment booking" in r_cancel["reply"].lower()

    # Check database
    with SessionLocal() as db:
        convo = db.execute(select(Conversation).where(Conversation.session_token == token)).scalar_one()
        assert convo.booking_state is None
        assert convo.booking_step == "idle"
        assert convo.expires_at is None
    assert token not in _booking_sessions


# ---------------------------------------------------------------------------
# 6. Privacy: Visitor PII stays local and bypasses Gemini
# ---------------------------------------------------------------------------

def test_visitor_pii_strictly_bypasses_gemini_api(client, org):
    """Ensure that visitor name, phone, email, purpose, and final confirmation are handled
    strictly by the local state machine and NEVER forwarded to Google Gemini."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.is_configured = True
    responder = HybridGeminiResponder(gemini_service=mock_gemini)

    with SessionLocal() as db:
        slot_dt = future_slot(days_ahead=2, hour=10, minute=0)
        # Step: visitor_name
        sess = BookingSession(
            session_token="test-pii-token",
            step="visitor_name",
            department_id=org["dept_id"],
            department_name="Admissions",
            staff_id=org["staff_ids"][0],
            staff_name="Dr. Ravi",
            date=slot_dt.date(),
            slot_start=slot_dt,
            slot_end=slot_dt + timedelta(minutes=30),
        )
        _booking_sessions["test-pii-token"] = sess

        reply = responder.respond(db, "Aarav Sharma", [], session_token="test-pii-token")
        assert "contact phone number" in reply.text.lower()
        mock_gemini.interpret.assert_not_called()

        # Step: visitor_phone
        reply = responder.respond(db, "+919876543000", [], session_token="test-pii-token")
        assert "email address" in reply.text.lower()
        mock_gemini.interpret.assert_not_called()

        # Step: visitor_email
        reply = responder.respond(db, "aarav@example.com", [], session_token="test-pii-token")
        assert "purpose" in reply.text.lower()
        mock_gemini.interpret.assert_not_called()

        # Step: visitor_purpose
        reply = responder.respond(db, "College admission documents", [], session_token="test-pii-token")
        assert "review your appointment" in reply.text.lower()
        mock_gemini.interpret.assert_not_called()

        # Step: confirmation
        reply = responder.respond(db, "Confirm", [], session_token="test-pii-token")
        assert "recorded" in reply.text.lower()
        mock_gemini.interpret.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Gemini Fallback on timeout or API error
# ---------------------------------------------------------------------------

def test_gemini_failure_fallback_preserves_booking_flow(client, org):
    """When Gemini returns None (e.g. timeout, quota, network error), the hybrid responder
    falls back cleanly to the rule-based engine and booking proceeds without interruption."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.is_configured = True
    mock_gemini.interpret.return_value = None  # simulate failure/timeout

    responder = HybridGeminiResponder(gemini_service=mock_gemini)
    with SessionLocal() as db:
        reply = responder.respond(db, "I want to book an appointment with Dr. Ravi", [], session_token="test-fallback")
        assert reply.booking_flow is not None
        assert reply.booking_flow["step"] == "date"
        assert "Dr. Ravi" in reply.text
