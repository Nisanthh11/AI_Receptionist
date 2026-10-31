"""Test configuration. Tests run against a temporary SQLite file (the sandbox has no MySQL).

Environment variables are set BEFORE the app is imported so settings never touch a real .env/MySQL.
"""
import os
import tempfile
from datetime import date, datetime, time, timedelta

_tmp = tempfile.mkdtemp(prefix="receptionist_tests_")
# Default: temporary SQLite file. To run the same suite on MySQL, set TEST_DATABASE_URL to a database whose
# name contains "test" (the suite drops and recreates every table, so this guard protects real data).
_test_url = os.environ.get("TEST_DATABASE_URL")
if _test_url:
    if "test" not in _test_url.rsplit("/", 1)[-1].split("?")[0].lower():
        raise RuntimeError("TEST_DATABASE_URL must point to a database whose name contains 'test'.")
    os.environ["DATABASE_URL"] = _test_url
else:
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db').replace(os.sep, '/')}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-definitely-longer-than-32-chars"
os.environ["TIMEZONE"] = "Asia/Kolkata"
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["TWILIO_ACCOUNT_SID"] = ""
os.environ["SMS_GATEWAY_URL"] = ""
os.environ["GEMINI_ENABLED"] = "false"
os.environ["GEMINI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.timeutils import now_local  # noqa: E402
from app.main import app  # noqa: E402
from app.models import FAQ, Department, OrganizationInfo, Staff, StaffAvailability  # noqa: E402
from app.models.user import ROLE_ADMIN, ROLE_RECEPTIONIST  # noqa: E402
from app.services import auth_service  # noqa: E402

ADMIN = ("admin@test.example", "AdminPass123!")
RECEPTION = ("desk@test.example", "DeskPass123!")


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        auth_service.ensure_roles(db)
        auth_service.create_user(db, email=ADMIN[0], full_name="Test Admin", password=ADMIN[1], role=ROLE_ADMIN, phone="+919876543200")
        auth_service.create_user(db, email=RECEPTION[0], full_name="Test Desk", password=RECEPTION[1], role=ROLE_RECEPTIONIST)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, creds):
    r = client.post("/api/auth/login", json={"email": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin_h(client):
    return _login(client, ADMIN)


@pytest.fixture
def desk_h(client):
    return _login(client, RECEPTION)


@pytest.fixture
def org():
    """One department with two staff members available 09:00-17:00 every day, plus org info and FAQs."""
    with SessionLocal() as db:
        dept = Department(name="Admissions", description="Admission help", location="Block A", phone="+910000000002", working_hours="Mon-Fri 9-5")
        for n in ("Dr. Ravi", "Ms. Priya"):
            s = Staff(full_name=n, designation="Officer")
            s.availability = [StaffAvailability(weekday=d, start_time=time(9, 0), end_time=time(17, 0)) for d in range(7)]
            dept.staff.append(s)
        db.add(dept)
        db.add(OrganizationInfo(key="working_hours", value="Monday to Friday, 9 AM to 5 PM"))
        db.add(FAQ(question="Where can I park my vehicle?", answer="Park near the main gate.", keywords="parking park vehicle", category="General"))
        db.commit()
        return {"dept_id": dept.id, "staff_ids": [s.id for s in dept.staff]}


def future_slot(days_ahead: int = 3, hour: int = 10, minute: int = 0) -> datetime:
    d = now_local().date() + timedelta(days=days_ahead)
    return datetime.combine(d, time(hour, minute))


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def booking_payload(staff_id: int, start: datetime, name="Anita Kumar", phone="+919876543210", **kw):
    p = {"full_name": name, "phone": phone, "staff_id": staff_id, "start_at": iso(start), "purpose": "Admission enquiry"}
    p.update(kw)
    return p
