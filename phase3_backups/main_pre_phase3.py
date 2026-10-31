import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (admin_appointments, admin_dashboard, admin_directory,
                     admin_visitors, auth, public, user_appointments)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import register_error_handlers

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Virtual reception and visitor management. Admin endpoints require a Bearer JWT.",
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


for _r in (auth.router, public.router, user_appointments.router, admin_appointments.router, admin_visitors.router,
           admin_directory.router, admin_dashboard.router):
    app.include_router(_r)
