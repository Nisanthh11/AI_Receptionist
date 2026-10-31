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

## 8. Chat architecture & Google Gemini AI Integration (Phase 4)

The chat system utilizes a **Hybrid AI Architecture** (`app/services/chat_service.py` and `app/services/gemini_service.py`):
1. **Intelligent Natural Language Understanding (Google Gemini API):** Powered by the official `google-genai` SDK, Gemini interprets complex user messages (e.g., "I need to meet someone from Admissions tomorrow morning", "Actually, switch to Friday afternoon", "Show earliest slot") into strictly validated structured data (`GeminiInterpretation`).
2. **Automatic Deterministic Fallback (`RuleBasedResponder`):** The proven rule-based responder remains fully active as an immediate fallback whenever Gemini is disabled, times out, encounters a network issue, exceeds rate limits (HTTP 429), or returns invalid output. The visitor's booking session state is completely preserved across fallbacks.
3. **Strict Separation of Concerns:** Gemini acts solely as an interpreter. The FastAPI backend remains the **exclusive authority** responsible for:
   - Slot availability and grid computation
   - Concurrency locking and database transactions
   - Staff assignment and approval workflows
   - Visitor privacy verification
   - Automatic Gmail SMTP email notifications and persistent reminders
   Gemini **never** executes SQL, modifies database state, confirms appointments directly, or bypasses server rules.

### 8.1 Obtaining a Gemini API Key
You can obtain an API key using Google AI Studio's free tier:
1. Visit [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. Click **Get API key** and create a new key.
4. Copy the key and add it to `backend/.env`.

### 8.2 Configuring the Backend Environment
Add the following variables to `backend/.env`:
```env
# Google Gemini API Settings (Phase 4)
GEMINI_ENABLED=true
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=10
GEMINI_MAX_RETRIES=2
GEMINI_MAX_OUTPUT_TOKENS=800
```
- **Disabling Gemini:** Set `GEMINI_ENABLED=false` (or leave `GEMINI_API_KEY` blank). The backend automatically starts in rule-based fallback mode.
- **Frontend Security:** The API key remains strictly on the backend. It is never exposed in Vite bundles, public API responses, or server logs.

### 8.3 Privacy and Security Safeguards
- **Visitor PII Protection:** Visitor contact details (`visitor_name`, `visitor_phone`, `visitor_email`, `visitor_purpose`, `confirmation`) bypass external API calls entirely and are processed strictly on the local backend.
- **Adversarial Prompt Defense:** System instructions instruct the model to reject prompt injections attempting to bypass rules or force confirmation.
- **Database Grounding:** FAQs and directory questions are retrieved strictly from real database records (`FAQ`, `OrganizationInfo`, `Department`). The model never hallucinates organization policies or contact numbers.

### 8.4 Running Automated Tests Without Real API Calls
All automated tests mock Gemini responses using FastAPI dependency overrides and `unittest.mock`:
```powershell
cd ai-receptionist\backend
.\.venv\Scripts\Activate.ps1
pytest -v tests/test_gemini_integration.py   # Run Gemini integration suite (18 tests)
pytest -v                                    # Run full suite (136 tests: 135 passed, 1 skipped)
```
No live API calls are made and no quota or expense is incurred during testing.

### 8.5 Current Limitations and Usage Costs
- Free tier quotas on Google AI Studio apply (e.g. Requests Per Minute). The system handles rate limits gracefully with immediate fallback.
- In-memory conversation cache is synced directly with MySQL for draft persistence across server restarts.

## 9. Phase 5: Production Readiness and Persistent Conversation Recovery

Phase 5 introduces robust persistence for in-progress conversational booking drafts, automated session recovery, and hardened booking concurrency safeguards:

### 9.1 Persistent Conversation Recovery Architecture
- **Draft Session Storage in MySQL:** Unfinished conversational booking states are saved to MySQL table `conversations` via Alembic migration `0005_persistent_booking_sessions.py` (`booking_state`, `booking_step`, `expires_at`).
- **Resilience to Restarts:** When the backend server restarts or workers recycle, visitors returning with a valid `session_token` have their draft conversation, selected department, staff, and date/slot restored seamlessly.
- **Session Expiry Management:** Inactive booking drafts expire automatically after 30 minutes (`SESSION_TTL_MINUTES = 30`). Expired drafts are cleanly purged and reset to `idle`, notifying visitors courteously without crashes or 500 errors.
- **Invalid Token Isolation:** Bogus or unknown tokens receive an isolated fresh conversation without leaking any other visitor's data.

### 9.2 Concurrency & Booking Reliability
- **Real-Time Slot Recheck:** Restored sessions verify slot availability and lead times against the live database before resuming. If a slot was booked by someone else during user absence, the system immediately alerts the visitor and provides refreshed slots.
- **Lead Time Verification on Confirmation:** If a visitor delays at the confirmation prompt past the minimum booking lead time, the system prevents booking and prompts for a fresh upcoming time slot.
- **Duplicate Booking Prevention:** Once an appointment is booked (`step="completed"`), retrying or refreshing returns the existing confirmation and reference code without creating duplicate database records.
- **InnoDB Row Locking:** Concurrent appointment attempts for the same staff member are serialized using `with_for_update()`, eliminating race conditions.

### 9.3 Security, Privacy & LLM Containment
- **Visitor PII Containment:** Steps collecting visitor name, phone, email, purpose, and final confirmation are strictly handled by local backend rule engines. Visitor PII is never included in prompts or transmitted to Google Gemini.
- **Zero Secret Leaks:** API keys, database credentials, JWT secrets, and stack traces are never exposed in public endpoints, responses, or client bundles.
- **Automated Offline Testing:** Test suites run completely offline with mocked providers, ensuring deterministic execution without consuming API quota.

## 10. Known limitations
- No login lockout (public booking/registration/lookup and `/api/auth/login` can be brute-forced without an external WAF).
- JWT is kept in `sessionStorage` (cleared when the tab closes) with no refresh tokens or server-side revocation.
- Visitors cannot cancel/reschedule their own appointment online; only staff can.
- Fixed-length slots only (`SLOT_MINUTES`); no breaks/holidays/leave calendar.
- Naive local times: single-timezone organisation (`Asia/Kolkata`), no DST handling.
- Admin lists load without server-side sorting options beyond the defaults.

## 10. Prioritised next features
1. Rate limiting + login lockout + audit log (security hardening).
2. Visitor self-service cancel/reschedule with reference code + phone.
3. Browser click-through / Playwright tests and Vitest component tests; CI pipeline.
4. Voice: speech-to-text input and text-to-speech replies (kiosk mode).
5. Leave/holiday calendar and variable appointment duration.
6. Privacy tooling: retention policy, export/delete visitor data, consent text.
7. Docker Compose (MySQL + backend + frontend) and production deployment guide.
8. Multi-language chat and accessibility audit.

## 11. Continuing in Google Antigravity
Open the repository root. Everything needed is in this README; business rules live in `backend/app/services/`, tests in
`backend/tests/`. Run `pytest` after each change (SQLite needs no setup). Add schema changes as new Alembic revisions
(`alembic revision --autogenerate -m "..."`, then `alembic upgrade head` and `alembic check`). Keep new logic in services,
keep routers thin, and never report success to a visitor before the database commit.
