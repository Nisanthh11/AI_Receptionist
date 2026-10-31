import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (admin_appointments, admin_dashboard, admin_directory,
                     admin_visitors, auth, public, telephony, user_appointments, voice)
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.errors import register_error_handlers
from app.services.reminder_service import process_due_reminders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


async def reminder_worker_loop():
    """Persistent background task that polls for due appointment reminders."""
    if not settings.reminders_enabled:
        logger.info("Appointment reminder worker disabled by configuration.")
        return

    logger.info("Starting appointment reminder worker (interval: %ss)...", settings.reminder_poll_interval_seconds)
    while True:
        try:
            def _run():
                with SessionLocal() as db:
                    return process_due_reminders(db)

            count = await asyncio.to_thread(_run)
            if count > 0:
                logger.info("Appointment reminder worker delivered %d reminder(s).", count)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in reminder background worker loop: %s", str(e))

        try:
            await asyncio.sleep(settings.reminder_poll_interval_seconds)
        except asyncio.CancelledError:
            break
    logger.info("Appointment reminder worker stopped.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(reminder_worker_loop())
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Virtual reception and visitor management. Admin endpoints require a Bearer JWT.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
register_error_handlers(app)


@app.get("/api/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unreachable"})
    return {"status": "ok", "database": "ok"}


for _r in (auth.router, public.router, voice.router, telephony.router, user_appointments.router, admin_appointments.router,
           admin_visitors.router, admin_directory.router, admin_dashboard.router):
    app.include_router(_r)
