from tests.conftest import booking_payload, future_slot

ADMIN_ONLY_WRITES = [
    ("post", "/api/admin/departments", {"name": "Library"}),
    ("post", "/api/admin/faqs", {"question": "Q?", "answer": "A"}),
    ("put", "/api/admin/organization", {"values": {"address": "x"}}),
    ("post", "/api/admin/users", {"email": "x@test.example", "full_name": "Xy", "password": "Password123", "role": "receptionist"}),
    ("get", "/api/admin/users", None),
]


def test_receptionist_cannot_use_admin_only_endpoints(client, org, desk_h):
    for method, path, body in ADMIN_ONLY_WRITES:
        r = getattr(client, method)(path, headers=desk_h, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (method, path, r.status_code)


def test_anonymous_cannot_use_any_admin_endpoint(client, org):
    for method, path, body in ADMIN_ONLY_WRITES + [("get", "/api/admin/appointments", None), ("get", "/api/admin/departments", None)]:
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 401, (method, path)


def test_receptionist_can_read_directory(client, org, desk_h):
    assert client.get("/api/admin/departments", headers=desk_h).status_code == 200
    assert client.get("/api/admin/staff", headers=desk_h).status_code == 200


def test_department_staff_crud_and_soft_delete(client, org, admin_h):
    r = client.post("/api/admin/departments", json={"name": "Library", "location": "Block C"}, headers=admin_h)
    assert r.status_code == 201
    did = r.json()["id"]
    assert client.post("/api/admin/departments", json={"name": "Library"}, headers=admin_h).status_code == 409
    s = client.post("/api/admin/staff", json={"department_id": did, "full_name": "Mr Librarian"}, headers=admin_h)
    assert s.status_code == 201
    sid = s.json()["id"]
    assert client.post("/api/admin/staff", json={"department_id": 9999, "full_name": "Ghost Person"}, headers=admin_h).status_code == 404
    av = client.put(f"/api/admin/staff/{sid}/availability", json={"windows": [{"weekday": 0, "start_time": "09:00:00", "end_time": "12:00:00"}]}, headers=admin_h)
    assert av.status_code == 200 and len(av.json()["availability"]) == 1
    overlap = client.put(f"/api/admin/staff/{sid}/availability", json={"windows": [
        {"weekday": 0, "start_time": "09:00:00", "end_time": "12:00:00"}, {"weekday": 0, "start_time": "11:00:00", "end_time": "13:00:00"}]}, headers=admin_h)
    assert overlap.status_code == 422
    bad = client.put(f"/api/admin/staff/{sid}/availability", json={"windows": [{"weekday": 1, "start_time": "12:00:00", "end_time": "09:00:00"}]}, headers=admin_h)
    assert bad.status_code == 422
    assert client.delete(f"/api/admin/departments/{did}", headers=admin_h).json()["is_active"] is False
    names = [d["name"] for d in client.get("/api/public/departments").json()]
    assert "Library" not in names


def test_public_directory_lists_only_active_staff(client, org, admin_h):
    client.delete(f"/api/admin/staff/{org['staff_ids'][0]}", headers=admin_h)
    dept = client.get("/api/public/departments").json()[0]
    assert [s["id"] for s in dept["staff"]] == [org["staff_ids"][1]]
    # the in-memory filtering must not have deleted/deactivated anything permanently
    assert len(client.get("/api/admin/staff", headers=admin_h).json()) == 2


def test_public_directory_never_exposes_staff_email(client, org, admin_h):
    client.put(f"/api/admin/staff/{org['staff_ids'][0]}", json={"department_id": org["dept_id"], "full_name": "Dr. Ravi", "email": "ravi@private.example"}, headers=admin_h)
    assert "private.example" not in client.get("/api/public/departments").text


def test_faq_crud_changes_chat_answers(client, org, admin_h):
    r = client.post("/api/admin/faqs", json={"question": "Is Wi-Fi available for guests?", "answer": "Guest Wi-Fi is available in the lobby.", "keywords": "wifi internet"}, headers=admin_h)
    assert r.status_code == 201
    fid = r.json()["id"]
    reply = client.post("/api/public/chat", json={"message": "do you have wifi"}).json()
    assert "lobby" in reply["reply"]
    client.put(f"/api/admin/faqs/{fid}", json={"question": "Is Wi-Fi available for guests?", "answer": "Ask at reception.", "keywords": "wifi", "is_active": False}, headers=admin_h)
    assert client.post("/api/public/chat", json={"message": "do you have wifi"}).json()["intent"] == "unknown"
    assert client.delete(f"/api/admin/faqs/{fid}", headers=admin_h).status_code == 204
    assert client.delete(f"/api/admin/faqs/{fid}", headers=admin_h).status_code == 404


def test_org_info_update_and_unknown_key_rejected(client, org, admin_h):
    r = client.put("/api/admin/organization", json={"values": {"address": "12 Main Road", "working_hours": "Mon-Sat 8-4"}}, headers=admin_h)
    assert r.status_code == 200
    assert client.get("/api/public/organization").json()["address"] == "12 Main Road"
    assert client.put("/api/admin/organization", json={"values": {"admin_password": "x"}}, headers=admin_h).status_code == 422


def test_user_management_rules(client, org, admin_h):
    r = client.post("/api/admin/users", json={"email": "New.Desk@test.example", "full_name": "New Desk", "password": "Password123", "role": "receptionist"}, headers=admin_h)
    assert r.status_code == 201 and r.json()["email"] == "new.desk@test.example" and "password" not in r.text
    assert client.post("/api/admin/users", json={"email": "new.desk@test.example", "full_name": "Dup Desk", "password": "Password123", "role": "receptionist"}, headers=admin_h).status_code == 409
    assert client.post("/api/admin/users", json={"email": "z@test.example", "full_name": "Zed Zed", "password": "short", "role": "receptionist"}, headers=admin_h).status_code == 422
    assert client.post("/api/admin/users", json={"email": "z@test.example", "full_name": "Zed Zed", "password": "Password123", "role": "superuser"}, headers=admin_h).status_code == 422
    me = client.get("/api/auth/me", headers=admin_h).json()
    assert client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False}, headers=admin_h).status_code == 409
    assert client.post("/api/auth/login", json={"email": "new.desk@test.example", "password": "Password123"}).status_code == 200


def test_dashboard_and_analytics_use_real_records(client, org, admin_h, desk_h):
    sid = org["staff_ids"][0]
    client.post("/api/public/appointments", json=booking_payload(sid, future_slot(3, 10)))
    client.post("/api/public/appointments", json=booking_payload(org["staff_ids"][1], future_slot(3, 11), name="Second Person", phone="+919000000008"))
    client.post("/api/public/visitors/register", json={"full_name": "Walk In", "phone": "+919111122223", "purpose": "Enquiry"})
    visit_id = client.get("/api/admin/visits", headers=desk_h).json()["items"][0]["id"]
    client.post(f"/api/admin/visits/{visit_id}/check-in", headers=desk_h)

    d = client.get("/api/admin/dashboard", headers=desk_h).json()
    assert d["pending_appointments"] == 2 and d["total_visitors"] == 3
    assert d["visitors_on_site"] == 1 and d["visitors_waiting_check_in"] == 0
    assert len(d["recent_activity"]) >= 3 and d["today_count"] == 0

    a = client.get("/api/admin/analytics", headers=admin_h).json()
    assert a["appointments_by_status"]["pending"] == 2
    assert a["appointments_by_department"] == [{"department": "Admissions", "appointments": 2}]
    assert len(a["daily"]) == 14 and sum(x["visits"] for x in a["daily"]) == 1
    assert client.get("/api/admin/analytics", params={"days": 3}, headers=admin_h).status_code == 422


def test_unhandled_errors_do_not_leak_details(org):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import get_db

    def broken():
        raise RuntimeError("password=hunter2 at /srv/app.py")

    app.dependency_overrides[get_db] = broken
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/public/faqs")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500 and "hunter2" not in r.text and "Traceback" not in r.text
