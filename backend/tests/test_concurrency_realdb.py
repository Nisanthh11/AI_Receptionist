"""Concurrent booking race. Only meaningful on a real server (MySQL/MariaDB), so it is skipped on SQLite.
Run with:  $env:TEST_DATABASE_URL = "mysql+pymysql://user:pass@localhost:3306/ai_receptionist_test"
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models import Appointment
from tests.conftest import booking_payload, future_slot

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs a real MySQL/MariaDB server (set TEST_DATABASE_URL)")


def test_ten_simultaneous_bookings_for_one_slot_yield_exactly_one_success(org):
    sid, start = org["staff_ids"][0], future_slot(3, 10)

    def attempt(i: int) -> int:
        with TestClient(app, raise_server_exceptions=False) as c:
            return c.post("/api/public/appointments",
                          json=booking_payload(sid, start, name=f"Racer Number {i}", phone=f"+9190000000{i:02d}")).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(attempt, range(10)))
    assert codes.count(201) == 1, codes
    assert all(c == 409 for c in codes if c != 201), codes
    with SessionLocal() as db:
        assert len(db.execute(select(Appointment)).scalars().all()) == 1
