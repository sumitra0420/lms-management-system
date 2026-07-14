import asyncio
import uuid
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.models.job import ExtractedQuestion, UploadJob
from app.services.consistency import check_with_retry
from app.services.converter import docx_to_text
from app.services.storage import download_file, generate_presigned_url

router = APIRouter()


class PresignRequest(BaseModel):
    filename: str


@router.post("/jobs/presign")
def presign(req: PresignRequest, db: Session = Depends(get_db)):
    if not req.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{job_id}/{req.filename}"

    job = UploadJob(id=job_id, filename=req.filename, s3_key=s3_key, status="pending")
    db.add(job)
    db.commit()

    presigned_url = generate_presigned_url(s3_key)
    return {"job_id": job_id, "presigned_url": presigned_url, "s3_key": s3_key}


@router.post("/jobs/{job_id}/start")
def start_job(job_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "pending":
        raise HTTPException(status_code=409, detail=f"Job already {job.status}")

    job.status = "processing"
    db.commit()

    background_tasks.add_task(_process_job, job_id, job.s3_key, job.filename)
    return {"job_id": job_id, "status": "processing"}


@router.get("/jobs/{job_id}/status")
def job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response: dict = {
        "job_id":            job.id,
        "filename":          job.filename,
        "status":            job.status,
        "consistency_score": job.consistency_score,
        "total_points":      job.total_points,
        "attempt":           job.retry_count,
    }

    if job.status in ("passed", "flagged"):
        response["questions"] = [
            {
                "id":                str(q.question_id),
                "type":              q.type,
                "text":              q.text,
                "choices":           q.choices or [],
                "correct_answer":    q.correct_answer,
                "points":            q.points,
                "feedback":          q.feedback,
                "flagged":           q.flagged,
                "consistency_score": q.consistency_score,
            }
            for q in job.questions
        ]

    return response


# ---------------------------------------------------------------------------
# Background task — runs in a thread pool (not async)
# ---------------------------------------------------------------------------

def _process_job(job_id: str, s3_key: str, filename: str):
    db = SessionLocal()
    try:
        file_bytes = download_file(s3_key)
        text       = docx_to_text(file_bytes, filename)
        result     = asyncio.run(check_with_retry(text))

        consistency  = result.get("consistency", {})
        questions    = result["normalised_a"].get("questions", [])
        total_points = sum(float(q.get("points", 0)) for q in questions)
        per_question = consistency.get("details", {}).get("per_question", [])

        for i, q in enumerate(questions):
            q_score = per_question[i]["score"] if i < len(per_question) else 1.0
            db.add(ExtractedQuestion(
                job_id         = job_id,
                question_id    = str(q.get("id", i + 1)),
                type           = q.get("type", ""),
                text           = q.get("text", ""),
                choices        = q.get("choices", []),
                correct_answer = q.get("correct_answer", ""),
                points         = float(q.get("points", 0)),
                feedback       = q.get("feedback") or "",
                flagged        = q_score < 0.75,
                consistency_score = q_score,
            ))

        job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
        job.status            = "passed" if consistency.get("consistent") else "flagged"
        job.consistency_score = consistency.get("score", 0)
        job.total_points      = total_points
        job.retry_count       = result.get("attempt", 1)
        db.commit()

    except Exception as exc:
        db.rollback()
        job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
        if job:
            job.status = "error"
            db.commit()
        raise exc
    finally:
        db.close()
