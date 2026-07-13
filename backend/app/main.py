from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import documents

app = FastAPI(title="LMS Management System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api")
