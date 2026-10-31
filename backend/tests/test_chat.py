from app.core.database import SessionLocal
from app.models import Department
from app.services.chat_service import NOT_FOUND_REPLY


def ask(client, msg, token=None):
    r = client.post("/api/public/chat", json={"message": msg, **({"session_token": token} if token else {})})
    assert r.status_code == 200, r.text
    return r.json()


def test_greeting(client, org):
    r = ask(client, "Hello there")
    assert r["intent"] == "greeting" and r["session_token"]


def test_working_hours_from_stored_org_info(client, org):
    r = ask(client, "What are your working hours?")
    assert r["intent"] == "working_hours" and "Monday to Friday, 9 AM to 5 PM" in r["reply"]


def test_hours_not_invented_when_not_stored(client):
    r = ask(client, "What are your opening hours?")
    assert r["intent"] == "unknown" and r["reply"] == NOT_FOUND_REPLY and r["answered_from_records"] is False


def test_department_enquiry_uses_stored_record(client, org):
    r = ask(client, "Tell me about the admissions department")
    assert r["intent"] == "department_enquiry" and "Block A" in r["reply"] and r["action"] == "book_appointment"


def test_department_list_and_inactive_hidden(client, org):
    assert "Admissions" in ask(client, "Which departments do you have?")["reply"]
    with SessionLocal() as db:
        db.query(Department).update({"is_active": False})
        db.commit()
    assert "Admissions" not in ask(client, "Which departments do you have?")["reply"]


def test_appointment_intent_points_to_booking(client, org):
    r = ask(client, "I want to book an appointment")
    assert r["intent"] == "appointment_request" and r["action"] == "book_appointment"


def test_faq_answer_and_unknown_question(client, org):
    assert "main gate" in ask(client, "where is parking?")["reply"]
    r = ask(client, "What is the airspeed velocity of a swallow?")
    assert r["reply"] == NOT_FOUND_REPLY and r["intent"] == "unknown"


def test_session_continues_and_messages_are_stored(client, org):
    t = ask(client, "hi")["session_token"]
    assert ask(client, "thanks", t)["session_token"] == t
    from app.models import Message
    with SessionLocal() as db:
        assert db.query(Message).count() == 4


def test_chat_input_validation(client, org):
    assert client.post("/api/public/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/public/chat", json={"message": "x" * 501}).status_code == 422
    assert client.post("/api/public/chat", json={"message": "<script>alert(1)</script>"}).status_code == 422
