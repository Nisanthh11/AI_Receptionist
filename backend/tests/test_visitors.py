from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import VisitLog

REG = {"full_name": "Walk In Visitor", "phone": "+919111122223", "purpose": "Collect certificate"}


def test_public_registration_creates_unchecked_visit_and_hides_details(client, org):
    r = client.post("/api/public/visitors/register", json={**REG, "email": "walkin@example.com"})
    assert r.status_code == 201
    assert set(r.json()) == {"reference_code", "message"}
    assert "Walk In" not in r.text and "9111122223" not in r.text
    with SessionLocal() as db:
        v = db.execute(select(VisitLog)).scalar_one()
        assert v.status == "registered" and v.check_in_at is None


def test_check_in_and_out_flow(client, org, desk_h):
    client.post("/api/public/visitors/register", json=REG)
    visit = client.get("/api/admin/visits", headers=desk_h).json()["items"][0]
    vid = visit["id"]
    assert client.post(f"/api/admin/visits/{vid}/check-out", headers=desk_h).status_code == 409  # not checked in
    r = client.post(f"/api/admin/visits/{vid}/check-in", headers=desk_h)
    assert r.status_code == 200 and r.json()["status"] == "checked_in" and r.json()["check_in_at"]
    assert client.post(f"/api/admin/visits/{vid}/check-in", headers=desk_h).status_code == 409
    r = client.post(f"/api/admin/visits/{vid}/check-out", headers=desk_h)
    assert r.json()["status"] == "checked_out"
    assert client.post(f"/api/admin/visits/{vid}/check-out", headers=desk_h).status_code == 409


def test_visits_filter_by_status(client, org, desk_h):
    client.post("/api/public/visitors/register", json=REG)
    client.post("/api/admin/visits", json={"full_name": "Staff Entered", "phone": "+919222233334", "purpose": "Meeting"}, headers=desk_h)
    assert client.get("/api/admin/visits", params={"status": "registered"}, headers=desk_h).json()["total"] == 1
    assert client.get("/api/admin/visits", params={"status": "checked_in"}, headers=desk_h).json()["total"] == 1
    assert client.get("/api/admin/visits", params={"status": "oops"}, headers=desk_h).status_code == 422


def test_visitor_data_requires_authentication(client, org):
    client.post("/api/public/visitors/register", json=REG)
    for path in ("/api/admin/visitors", "/api/admin/visitors/1", "/api/admin/visits", "/api/admin/dashboard", "/api/admin/analytics"):
        assert client.get(path).status_code == 401, path
    for path in ("/api/public/visitors", "/api/public/visits"):
        assert client.get(path).status_code in (404, 405)
    pub = client.get("/api/public/departments").text + client.get("/api/public/organization").text + client.get("/api/public/faqs").text
    assert "Walk In" not in pub and "9111122223" not in pub


def test_visitor_history_for_staff(client, org, desk_h):
    client.post("/api/public/visitors/register", json=REG)
    vid = client.get("/api/admin/visitors", params={"q": "walk in"}, headers=desk_h).json()["items"][0]["id"]
    d = client.get(f"/api/admin/visitors/{vid}", headers=desk_h).json()
    assert d["visitor"]["phone"] == "+919111122223" and len(d["visits"]) == 1
    assert client.get("/api/admin/visitors/9999", headers=desk_h).status_code == 404


def test_same_phone_different_name_does_not_overwrite_existing_record(client, org, desk_h):
    client.post("/api/public/visitors/register", json={**REG, "email": "orig@example.com"})
    client.post("/api/public/visitors/register", json={**REG, "full_name": "Different Person", "email": "other@example.com"})
    items = client.get("/api/admin/visitors", headers=desk_h).json()["items"]
    assert len(items) == 2
    assert {i["email"] for i in items} == {"orig@example.com", "other@example.com"}
