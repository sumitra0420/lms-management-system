import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


def _now():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class UploadJob(Base):
    __tablename__ = "upload_jobs"

    id               = Column(String, primary_key=True, default=_uuid)
    filename         = Column(String, nullable=False)
    s3_key           = Column(String, nullable=False)
    status           = Column(String, default="pending")   # pending | processing | passed | flagged | error
    retry_count      = Column(Integer, default=0)
    consistency_score = Column(Float, nullable=True)
    total_points     = Column(Float, nullable=True)
    created_at       = Column(DateTime(timezone=True), default=_now)
    updated_at       = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    extracted_data = relationship("ExtractedData", back_populates="job", uselist=False, cascade="all, delete-orphan")


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id                = Column(String, primary_key=True, default=_uuid)
    job_id            = Column(String, ForeignKey("upload_jobs.id"), nullable=False)
    filename          = Column(String, nullable=False)
    file_type         = Column(String, nullable=True)     # assessor_guide | quiz_short_answer | quiz_multiple_choice | unknown
    s3_key            = Column(String, nullable=False)
    raw_text          = Column(String)
    json_output       = Column(JSON)          # immutable AI extraction
    edited_json       = Column(JSON, nullable=True)  # user-edited version
    consistent        = Column(Boolean, default=False)
    consistency_score = Column(Float, nullable=True)
    total_questions   = Column(Integer, nullable=True)
    total_points      = Column(Float, nullable=True)
    attempt           = Column(Integer, default=1)
    created_at        = Column(DateTime(timezone=True), default=_now)

    job = relationship("UploadJob", back_populates="extracted_data")
