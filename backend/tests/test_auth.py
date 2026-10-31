from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import User
from tests.conftest import ADMIN, RECEPTION


def test_login_success_returns_token_and_role(client):
    r = client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin" and body["access_token"]


def test_login_wrong_password_and_unknown_user_same_message(client):
    a = client.post("/api/auth/login", json={"email": ADMIN[0], "password": "wrong-password"})
    b = client.post("/api/auth/login", json={"email": "nobody@test.example", "password": "whatever123"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_passwords_are_hashed_with_bcrypt(client):
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.email == ADMIN[0])).scalar_one()
        assert u.hashed_password != ADMIN[1]
        assert u.hashed_password.startswith("$2")


def test_me_requires_valid_token(client, admin_h):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    r = client.get("/api/auth/me", headers=admin_h)
    assert r.status_code == 200 and r.json()["email"] == ADMIN[0]


def test_disabled_user_cannot_login_or_use_token(client, admin_h):
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.email == ADMIN[0])).scalar_one()
        u.is_active = False
        db.commit()
    assert client.get("/api/auth/me", headers=admin_h).status_code == 401
    assert client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}).status_code == 401


def test_validation_errors_do_not_echo_password(client):
    r = client.post("/api/auth/login", json={"email": "not-an-email", "password": "SuperSecret!!"})
    assert r.status_code == 422
    assert "SuperSecret" not in r.text


def test_health_checks_database(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"
