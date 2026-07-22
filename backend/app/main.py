import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

from app.db import Base, engine
import app.models.job  # noqa: F401 — registers models with SQLAlchemy
from app.routers import jobs

app = FastAPI(title="LMS Management System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Columns added after initial schema creation.
# ALTER TABLE … ADD COLUMN IF NOT EXISTS is idempotent — safe to run on every startup.
_MIGRATIONS = [
    "ALTER TABLE extracted_data ADD COLUMN IF NOT EXISTS instructions_text TEXT",
    "ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS error_message TEXT",
]

@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for stmt in _MIGRATIONS:
            conn.execute(text(stmt))
        conn.commit()

app.include_router(jobs.router, prefix="/api")
