"""Seed roles, the first admin account and (optionally) demo content.

    python -m app.seed            # roles + admin (+ receptionist if configured)
    python -m app.seed --demo     # also sample departments, staff, availability, FAQs, org info

Credentials come from environment variables only. Re-running is safe (idempotent).
"""
import argparse
from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import FAQ, Department, OrganizationInfo, Staff, StaffAvailability, User
from app.models.user import ROLE_ADMIN, ROLE_RECEPTIONIST
from app.services import auth_service


def _require_real_password(pw: str | None, label: str) -> str:
    if not pw or pw.startswith("change-me") or len(pw) < 8:
        raise SystemExit(f"{label} must be set in .env to a real password (min 8 chars, not the placeholder).")
    return pw


def seed_accounts(db: Session) -> list[str]:
    s = get_settings()
    auth_service.ensure_roles(db)
    created = []
    if s.seed_admin_email:
        if not db.execute(select(User).where(User.email == s.seed_admin_email.lower())).scalar_one_or_none():
            auth_service.create_user(
                db, email=s.seed_admin_email, full_name=s.seed_admin_name,
                password=_require_real_password(s.seed_admin_password, "SEED_ADMIN_PASSWORD"), role=ROLE_ADMIN,
            )
            created.append(f"admin {s.seed_admin_email}")
    else:
        raise SystemExit("SEED_ADMIN_EMAIL is not set in .env")
    if s.seed_receptionist_email:
        if not db.execute(select(User).where(User.email == s.seed_receptionist_email.lower())).scalar_one_or_none():
            auth_service.create_user(
                db, email=s.seed_receptionist_email, full_name="Reception Desk",
                password=_require_real_password(s.seed_receptionist_password, "SEED_RECEPTIONIST_PASSWORD"),
                role=ROLE_RECEPTIONIST,
            )
            created.append(f"receptionist {s.seed_receptionist_email}")
    return created


DEMO_ORG = {
    "organization_name": "Sample Organization (edit in admin)",
    "working_hours": "Monday to Friday, 9:00 AM to 5:00 PM",
    "address": "Sample address - replace with your organization's address",
    "contact_phone": "+910000000000",
    "contact_email": "reception@example.com",
}
DEMO_DEPARTMENTS = [
    ("Administration", "General enquiries, certificates and records.", "Ground floor, Block A", "+910000000001", "Mon-Fri 9:00-17:00",
     [("Ms. Asha Rao", "Administrative Officer")]),
    ("Admissions", "Admission enquiries and counselling.", "First floor, Block A", "+910000000002", "Mon-Fri 9:30-16:30",
     [("Mr. Karthik S", "Admissions Coordinator")]),
    ("Accounts", "Fee payment and receipts.", "Ground floor, Block B", "+910000000003", "Mon-Fri 10:00-16:00",
     [("Mrs. Meera Nair", "Accounts Officer")]),
]
DEMO_FAQS = [
    ("What are your working hours?", "We are open Monday to Friday, 9:00 AM to 5:00 PM.", "hours timing open close schedule", "General"),
    ("Where can I park my vehicle?", "Visitor parking is available near the main gate. Please register at reception first.", "parking park vehicle car bike", "General"),
    ("What documents should I bring for admission?", "Please carry your identity proof, previous mark sheets and passport-size photographs.", "documents admission bring certificates", "Admissions"),
    ("How do I pay fees?", "Fees can be paid at the Accounts department counter during working hours.", "fee fees payment pay receipt", "Accounts"),
]


def seed_demo(db: Session) -> None:
    for k, v in DEMO_ORG.items():
        if db.get(OrganizationInfo, k) is None:
            db.add(OrganizationInfo(key=k, value=v))
    for name, desc, loc, phone, hours, staff in DEMO_DEPARTMENTS:
        if db.execute(select(Department).where(Department.name == name)).scalar_one_or_none():
            continue
        dept = Department(name=name, description=desc, location=loc, phone=phone, working_hours=hours)
        for full_name, designation in staff:
            member = Staff(full_name=full_name, designation=designation)
            member.availability = [
                StaffAvailability(weekday=d, start_time=time(10, 0), end_time=time(13, 0)) for d in range(5)
            ] + [StaffAvailability(weekday=d, start_time=time(14, 0), end_time=time(16, 30)) for d in range(5)]
            dept.staff.append(member)
        db.add(dept)
    for q, a, kw, cat in DEMO_FAQS:
        if db.execute(select(FAQ).where(FAQ.question == q)).scalar_one_or_none() is None:
            db.add(FAQ(question=q, answer=a, keywords=kw, category=cat))
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="also insert sample departments, staff, FAQs")
    args = parser.parse_args()
    with SessionLocal() as db:
        created = seed_accounts(db)
        print("Created accounts:", ", ".join(created) if created else "none (already present)")
        if args.demo:
            seed_demo(db)
            print("Demo data ready (sample content - edit or delete it in the admin dashboard).")


if __name__ == "__main__":
    main()
