# AI Receptionist — Virtual Reception & Visitor Management System

A working full-stack foundation: visitors chat with a rule-based receptionist, register, and book appointments;
staff manage appointments, visitors, departments, FAQs and see analytics.
**Stack:** React + Vite + Tailwind CSS · FastAPI · SQLAlchemy 2 · MySQL 8 · JWT auth with roles · Alembic migrations.

> **Honest status:** there is **no LLM, speech-to-text, text-to-speech, e-mail or SMS integration**. The chat is a
> rule-based responder that answers only from stored FAQs, departments and organisation info, and says so when it
> cannot find an answer. Notifications are in-app dashboard records only — nothing is sent to anyone.

## 1. What is implemented

**Visitor side (no login):** welcome page · text chat · visitor registration · appointment booking with live free-slot
list from the server · appointment status lookup (reference code **and** phone number) · department directory & FAQ ·
responsive layout (desktop/tablet/mobile).

**Admin dashboard (JWT, roles `admin` / `receptionist`):** dashboard (today's appointments, total visitors, pending,
on-site, recent activity) · appointment list with search/filters/pagination, confirm/complete/cancel/reschedule ·
visitors: walk-in entry, check-in/check-out, per-visitor history · departments, staff and weekly availability ·
FAQs and organisation info · analytics from real records · user accounts (admin only).

**Server-enforced rules**
- Slots are generated from each staff member's weekly availability; the server rejects times that are in the past, inside the
  minimum lead time (default 30 min), beyond the booking horizon (60 days), off the slot grid or outside availability.
- No double booking: (1) row lock on the staff member (`SELECT … FOR UPDATE`) while checking and inserting, (2) overlap query,
  (3) a database `UNIQUE` on `appointments.slot_key` (set only while an appointment is pending/confirmed) as a final backstop.
  A visitor also cannot hold two overlapping appointments.
- A booking is reported as successful **only after `COMMIT`**. Any failure rolls back and returns an error; the visitor
  record created for that attempt is rolled back too.
- Status workflow: `pending → confirmed → completed`, and `pending/confirmed → cancelled`. Completed/cancelled are final. Future
  appointments cannot be marked completed. Cancelling/completing frees the slot.
- Privacy: public endpoints never return visitor names, phones or e-mails (booking responses contain only reference code, time,
  staff and department). Lookup requires reference code + matching phone and returns the same 404 for "wrong phone" and "no such code".
  A public request can never overwrite an existing visitor record. Only name, phone, optional e-mail and purpose are collected.
- Security: bcrypt password hashing, JWT (HS256) with expiry, role checks on every admin route, validation that rejects `<`/`>`
  and control characters, parameterised queries via SQLAlchemy, validation errors never echo submitted values, unexpected
  errors return a generic message (details only in server logs), secrets only from environment variables.

## 2. Test results (real runs, October 2026)

| Run | Command | Result |
|---|---|---|
| **SQLite** (default, what the sandbox used) | `pytest` | **61 passed, 1 skipped** (the skipped one needs a real server) |
| **MariaDB 10.11** (real server, sandbox only) | `pytest` with `TEST_DATABASE_URL` | **62 passed** (includes 10 simultaneous bookings for one slot → exactly 1 success, 9 × 409) |
| Alembic on SQLite | `upgrade head`, `check`, `downgrade base`, `upgrade head` | OK, no schema drift |
| Alembic on MariaDB | `upgrade head`, `check` | OK, no schema drift |
| Seed script | run twice (idempotent), placeholder password refused | OK |
| Live API smoke test (uvicorn + curl, incl. via Vite proxy) | health, login, slots, booking, double booking 409, admin 401 without token, chat, CORS, Swagger | OK, no server tracebacks |
| Frontend | `npm run build` | OK (108 modules) |
| Frontend ↔ backend contract | all 38 `api.*` calls matched against OpenAPI | 37 matched; 1 is the dynamic `/visits/{id}/{check-in|check-out}` URL, both targets exist and are tested |

Tests by file: auth 7 · appointments 26 · visitors 6 · chat 9 · admin/RBAC/dashboard 11 · MySQL DDL compile 2 · real-DB concurrency 1.

### What was NOT verified (please check on your machine)
- **MySQL 8 itself.** The sandbox could not run MySQL 8; MariaDB 10.11 was used as the real-server check instead. The DDL also compiles
  for the MySQL dialect (`tests/test_schema_compat.py`, `docs/schema_mysql.sql`). Still unverified on genuine MySQL 8: `caching_sha2_password`
  login through PyMySQL on your install, `CHECK` constraint enforcement (MySQL ≥ 8.0.16 enforces them, MariaDB does too), InnoDB lock timeouts under load.
- **The UI was not exercised in a browser.** It compiles, every API call it makes matches a backend route, and the same calls were run over
  HTTP through the Vite proxy. Layout, mobile menu, modals and the booking flow still need a manual click-through.
- **Windows.** Commands below follow standard PowerShell/Windows behaviour but were run on Linux.
- SQLite tests cannot prove row-locking; that behaviour was only observed on MariaDB (`tests/test_concurrency_realdb.py`).

## 3. Setup on Windows (PowerShell)

Prerequisites: Python 3.11+ (3.12 used), Node.js 20+, MySQL 8 running locally.

### 3.1 Create the MySQL database and user
```powershell
mysql -u root -p
```
```sql
CREATE DATABASE ai_receptionist CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'receptionist'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON ai_receptionist.* TO 'receptionist'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```
(Optional, for running the MySQL test suite: also create `ai_receptionist_test` and grant the same user access to it.)

### 3.2 Backend
```powershell
cd ai-receptionist\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste the output as JWT_SECRET_KEY
notepad .env                           # set DATABASE_URL, JWT_SECRET_KEY, SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD
```
In `.env`, URL-encode special characters in the DB password (e.g. `@` → `%40`).

Create the tables with Alembic, then seed the roles and first admin (add `--demo` for sample departments/staff/FAQs):
```powershell
alembic upgrade head
python -m app.seed --demo
uvicorn app.main:app --reload --port 8000
```
- API docs (Swagger UI): http://127.0.0.1:8000/docs · health check: http://127.0.0.1:8000/api/health
- *Alternative without Alembic:* run `docs\schema_mysql.sql` in MySQL (generated from the migration), but then use Alembic for any future changes.

### 3.3 Frontend (new PowerShell window)
```powershell
cd ai-receptionist\frontend
npm install
npm run dev
```
Open http://localhost:5173. Staff sign in at http://localhost:5173/admin with the seeded admin e-mail/password.
The dev server proxies `/api` to `http://127.0.0.1:8000`. For production builds set `VITE_API_BASE_URL` and add that origin to `CORS_ORIGINS`.

### 3.4 Run the tests
```powershell
cd ai-receptionist\backend
.\.venv\Scripts\Activate.ps1
pytest                                   # SQLite, no setup needed

# Same suite on your MySQL (database name MUST contain "test"; every table in it is dropped and recreated):
$env:TEST_DATABASE_URL = "mysql+pymysql://receptionist:YOUR_PASSWORD@localhost:3306/ai_receptionist_test?charset=utf8mb4"
pytest
Remove-Item Env:TEST_DATABASE_URL

cd ..\frontend
npm run build
```

## 4. Configuration (`backend/.env`)

| Variable | Purpose | Default / note |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL, e.g. `mysql+pymysql://user:pass@localhost:3306/ai_receptionist?charset=utf8mb4` | required |
| `JWT_SECRET_KEY` | token signing secret (≥ 32 chars, app refuses to start otherwise) | required |
| `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT settings | `HS256`, `60` |
| `CORS_ORIGINS` | comma-separated allowed frontend origins | `http://localhost:5173` |
| `TIMEZONE` | organisation timezone; all stored times are naive local times in it | `Asia/Kolkata` |
| `SLOT_MINUTES`, `MIN_BOOKING_LEAD_MINUTES`, `MAX_BOOKING_DAYS_AHEAD` | booking rules | `30`, `30`, `60` |
| `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_ADMIN_NAME` | first admin created by `python -m app.seed` (placeholder password refused) | — |
| `SEED_RECEPTIONIST_EMAIL`, `SEED_RECEPTIONIST_PASSWORD` | optional receptionist account | — |
| `TEST_DATABASE_URL` | (tests only, not in `.env`) run the suite on a real server | database name must contain `test` |

Frontend: `VITE_API_BASE_URL` (empty in development).

## 5. Project structure
```
ai-receptionist/
  backend/
    app/
      api/        thin routers: auth, public, admin_appointments, admin_visitors, admin_directory, admin_dashboard
      core/       config (env), database, security (bcrypt/JWT), deps (role checks), errors, timeutils
      models/     SQLAlchemy models (user, department/staff/availability, visitor/visit_log, appointment, content)
      schemas/    Pydantic request/response models and validated field types
      services/   ALL business logic: appointment_service, visitor_service, chat_service, auth_service, analytics_service
      seed.py     roles, first admin, optional demo data
      main.py     app factory, CORS, error handlers, /api/health
    alembic/      migrations (0001_initial_schema)
    tests/        pytest suite
    requirements.txt, requirements-dev.txt, .env.example, pytest.ini, alembic.ini
  frontend/       Vite + React + Tailwind (src/pages/public, src/pages/admin, src/components, src/api)
  docs/schema_mysql.sql   MySQL DDL generated from the migration
  README.md, .gitignore
```

## 6. Database schema
13 tables, InnoDB/utf8mb4, named constraints, all datetimes naive in `TIMEZONE`.

| Table | Purpose / key constraints |
|---|---|
| `roles`, `users` | login accounts; `users.email` unique, `role_id` FK (RESTRICT), bcrypt `hashed_password` |
| `departments` | unique `name`; soft-deleted via `is_active` so history stays valid |
| `staff` | people visitors meet (separate from login users); FK → departments |
| `staff_availability` | weekly windows; `weekday 0–6` CHECK, `end_time > start_time` CHECK, unique (staff, weekday, start) |
| `visitors` | name, phone, optional e-mail (minimal data); index (phone, name) |
| `appointments` | unique `reference_code`; FKs to visitor/staff/department (RESTRICT); CHECK status ∈ pending/confirmed/completed/cancelled; CHECK `end_at > start_at`; **unique `slot_key`** (`staff_id\|YYYYMMDDHHMM` while active, NULL when cancelled/completed) |
| `visit_logs` | one physical visit: `registered_at`, `check_in_at`, `check_out_at`, who checked in/out; optional links to staff & appointment; unique `reference_code` |
| `faqs`, `organization_info` | approved content the chat may answer from |
| `conversations`, `messages` | chat history (no visitor identity attached); CHECK sender |
| `notifications` | in-app activity records only (`channel = in_app`) |

## 7. API routes
Interactive docs at `/docs`. "Staff" = admin or receptionist JWT; "Admin only" = admin role.

| Method | Path | Access | Summary |
|---|---|---|---|
| GET | `/api/admin/analytics` | Staff | Analytics |
| GET | `/api/admin/appointments` | Staff | List Appointments |
| GET | `/api/admin/appointments/{appointment_id}` | Staff | Get Appointment |
| POST | `/api/admin/appointments/{appointment_id}/cancel` | Staff | Cancel |
| POST | `/api/admin/appointments/{appointment_id}/reschedule` | Staff | Reschedule |
| PATCH | `/api/admin/appointments/{appointment_id}/status` | Staff | Set Status |
| GET | `/api/admin/dashboard` | Staff | Dashboard |
| GET | `/api/admin/departments` | Staff | List Departments |
| POST | `/api/admin/departments` | Admin only | Create Department |
| PUT | `/api/admin/departments/{dept_id}` | Admin only | Update Department |
| DELETE | `/api/admin/departments/{dept_id}` | Admin only | Deactivate Department |
| GET | `/api/admin/faqs` | Staff | List Faqs |
| POST | `/api/admin/faqs` | Admin only | Create Faq |
| PUT | `/api/admin/faqs/{faq_id}` | Admin only | Update Faq |
| DELETE | `/api/admin/faqs/{faq_id}` | Admin only | Delete Faq |
| GET | `/api/admin/organization` | Staff | Get Org |
| PUT | `/api/admin/organization` | Admin only | Update Org |
| GET | `/api/admin/staff` | Staff | List Staff |
| POST | `/api/admin/staff` | Admin only | Create Staff |
| PUT | `/api/admin/staff/{staff_id}` | Admin only | Update Staff |
| DELETE | `/api/admin/staff/{staff_id}` | Admin only | Deactivate Staff |
| PUT | `/api/admin/staff/{staff_id}/availability` | Admin only | Set Availability |
| GET | `/api/admin/users` | Admin only | List Users |
| POST | `/api/admin/users` | Admin only | Create User |
| PATCH | `/api/admin/users/{user_id}` | Admin only | Update User |
| GET | `/api/admin/visitors` | Staff | Visitors |
| GET | `/api/admin/visitors/{visitor_id}` | Staff | Visitor History |
| GET | `/api/admin/visits` | Staff | Visits |
| POST | `/api/admin/visits` | Staff | Create Visit |
| POST | `/api/admin/visits/{visit_id}/check-in` | Staff | Check In |
| POST | `/api/admin/visits/{visit_id}/check-out` | Staff | Check Out |
| POST | `/api/auth/login` | Public | Login |
| GET | `/api/auth/me` | Any signed-in user | Me |
| GET | `/api/health` | Public | Health |
| POST | `/api/public/appointments` | Public | Book |
| POST | `/api/public/appointments/lookup` | Public | Lookup |
| POST | `/api/public/chat` | Public | Chat |
| GET | `/api/public/departments` | Public | Departments |
| GET | `/api/public/faqs` | Public | Faqs |
| GET | `/api/public/organization` | Public | Organization |
| GET | `/api/public/slots` | Public | Slots |
| POST | `/api/public/visitors/register` | Public | Register Visitor |

## 8. Chat architecture & how to add AI later
`services/chat_service.py` defines `ResponderProvider` (abstract) and `ChatService`, which owns persistence and limits
(500 characters per message, 200 messages per conversation). The only provider today is `RuleBasedResponder`
(greeting/thanks/goodbye, department enquiries, working hours, appointment requests, FAQ keyword matching, honest fallback).
To add an LLM or retrieval system, implement `ResponderProvider.respond(db, message, history)` and return it from
`get_chat_service()` in `app/api/public.py` — routes, database and frontend stay unchanged. Voice input/TTS can be added in the
frontend (e.g. browser Web Speech API) or as providers that feed the same `/api/public/chat` endpoint.

## 9. Known limitations
- No rate limiting or login lockout (public booking/registration/lookup and `/api/auth/login` can be spammed or brute-forced).
- JWT is kept in `sessionStorage` (cleared when the tab closes) with no refresh tokens or server-side revocation.
- Visitors cannot cancel/reschedule their own appointment online; only staff can.
- Changing a staff member's availability does not re-validate already-booked appointments.
- Fixed-length slots only (`SLOT_MINUTES`); no breaks/holidays/leave calendar.
- Naive local times: fine for a single-timezone organisation, no DST handling.
- Chat is keyword-based English only; it will not understand paraphrases or other languages.
- No e-mail/SMS/push, no file uploads, no visitor photo/ID capture, no data-retention or deletion tooling.
- No automated frontend tests; the UI has not been clicked through in a browser.
- Admin lists load without server-side sorting options beyond the defaults.

## 10. Prioritised next features
1. Rate limiting + login lockout + audit log (security hardening).
2. Visitor self-service cancel/reschedule with reference code + phone.
3. Browser click-through / Playwright tests and Vitest component tests; CI pipeline.
4. Real notification provider (e-mail first) behind an interface, with delivery status.
5. LLM/retrieval `ResponderProvider` grounded in FAQs + directory, keeping the "not found" behaviour.
6. Voice: speech-to-text input and text-to-speech replies (kiosk mode).
7. Leave/holiday calendar and variable appointment duration.
8. Privacy tooling: retention policy, export/delete visitor data, consent text.
9. Docker Compose (MySQL + backend + frontend) and production deployment guide.
10. Multi-language chat and accessibility audit.

## 11. Continuing in Google Antigravity
Open the repository root. Everything needed is in this README; business rules live in `backend/app/services/`, tests in
`backend/tests/`. Run `pytest` after each change (SQLite needs no setup). Add schema changes as new Alembic revisions
(`alembic revision --autogenerate -m "..."`, then `alembic upgrade head` and `alembic check`). Keep new logic in services,
keep routers thin, and never report success to a visitor before the database commit.
