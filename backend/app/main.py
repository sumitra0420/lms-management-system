import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

from app.db import Base, engine
import app.models.job  # noqa: F401 — registers models with SQLAlchemy
from app.routers import documents, jobs

app = FastAPI(title="LMS Management System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)

app.include_router(documents.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
