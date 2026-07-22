import asyncio
import logging
import threading
import uuid
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.models.job import ExtractedData, UploadJob
from app.services.classifier import classify_document_type
from app.services.consistency import check_with_retry
from app.services.converter import extract_document, parse_points_per_question
from app.services.storage import download_file, generate_presigned_url
from app.schemas.question import validate_questions

logger = logging.getLogger(__name__)
router = APIRouter()

# Serialises the actual dual-model extraction call across concurrently
# uploaded files — download/convert can still happen in parallel, but only
# one file's Model A + Model B calls hit Bedrock at a time. Suspected fix
# for Model B (nova-2-lite) intermittently duplicating its question output
# under concurrent load (e.g. 17 questions coming back as 34).
_extraction_lock = threading.Lock()


class PresignRequest(BaseModel):
    filename: str

class EditRequest(BaseModel):
    questions: list


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


@router.patch("/jobs/{job_id}/questions")
def save_edits(job_id: str, body: EditRequest, db: Session = Depends(get_db)):
    job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.extracted_data:
        raise HTTPException(status_code=404, detail="No extracted data for this job")
    job.extracted_data.edited_json = body.questions
    db.commit()
    return {"status": "saved", "job_id": job_id}


@router.get("/jobs/{job_id}/detail")
def job_detail(job_id: str, db: Session = Depends(get_db)):
    job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data      = job.extracted_data
    questions = []
    has_edits = False
    if data:
        questions = data.edited_json or data.json_output or []
        has_edits = data.edited_json is not None

    return {
        "job_id":             job.id,
        "filename":           job.filename,
        "status":             job.status,
        "consistent":         job.status == "passed",
        "consistency_score":  job.consistency_score or 0,
        "total_points":       job.total_points or 0,
        "attempt":            job.retry_count or 1,
        "has_edits":          has_edits,
        "file_type":          data.file_type if data else None,
        "questions":          questions,
        "original_questions": data.json_output or [] if data else [],
        "error_message":      job.error_message,
    }


@router.get("/jobs/recent")
def recent_jobs(limit: int = 10, db: Session = Depends(get_db)):
    jobs = (
        db.query(UploadJob)
        .order_by(UploadJob.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for job in jobs:
        flag_count = 0
        if job.extracted_data and job.extracted_data.json_output:
            flag_count = sum(
                1 for q in job.extracted_data.json_output
                if (q.get("consistency_score") or 1.0) < 0.90
            )
        item = {
            "job_id":          job.id,
            "filename":        job.filename,
            "status":          job.status,
            "total_questions": None,
            "file_type":       None,
            "flag_count":      flag_count,
            "created_at":      job.created_at.isoformat() if job.created_at else None,
            "error_message":   job.error_message,
        }
        if job.extracted_data:
            item["total_questions"] = job.extracted_data.total_questions
            item["file_type"]       = job.extracted_data.file_type
        result.append(item)
    return result


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
        "error_message":     job.error_message,
    }

    if job.status in ("passed", "flagged") and job.extracted_data:
        response["questions"] = job.extracted_data.json_output or []

    return response


# ---------------------------------------------------------------------------
# Background task — runs in a thread pool (not async)
# ---------------------------------------------------------------------------

def _process_job(job_id: str, s3_key: str, filename: str):
    db = SessionLocal()
    try:
        file_bytes             = download_file(s3_key)
        text, instructions     = extract_document(file_bytes, filename)
        file_type              = classify_document_type(filename)

        with _extraction_lock:
            result = asyncio.run(check_with_retry(text, filename))

        consistency  = result.get("consistency", {})
        questions    = result["normalised_a"].get("questions", [])

        # Points: the instructions block ("Each question is graded out of N
        # mark(s)") is the authoritative source when present — apply it to
        # every question, overriding whatever either model guessed. If no
        # such statement exists, keep each question's own AI-extracted value
        # (which may itself be None — never invent a number here).
        rubric_points = parse_points_per_question(instructions)
        if rubric_points is not None:
            questions = [{**q, "points": rubric_points} for q in questions]

        total_points = sum(q.get("points") or 0 for q in questions)
        per_question = consistency.get("details", {}).get("per_question", [])
        consistent   = consistency.get("consistent", False)

        # When no per-question data is available (all retries had extraction
        # errors), default to 0.0 on a failed job so questions show as needing
        # review rather than falsely appearing as fully consistent (1.0).
        missing_score_default = 1.0 if consistent else 0.0

        annotated = []
        for i, q in enumerate(questions):
            pq = per_question[i] if i < len(per_question) else {}
            q_score = pq.get("score", missing_score_default)
            annotated.append({
                **q,
                "flagged":           q_score < 0.75,
                "consistency_score": q_score,
                "conflicts":         pq.get("conflicts", {}),
            })

        # JSON Schema Validation — reject/flag questions whose shape doesn't
        # match the expected Question schema (bad type enum, blank text,
        # negative points, etc.) before they're persisted or synced to Canvas.
        annotated = validate_questions(annotated)
        for q in annotated:
            if not q["schema_valid"]:
                q["flagged"] = True
                logger.warning(
                    f"[Schema] Job {job_id} question {q.get('id')} failed validation: "
                    f"{'; '.join(q['schema_errors'])}"
                )

        consistent = consistency.get("consistent", False) and all(q["schema_valid"] for q in annotated)
        attempt    = result.get("attempt", 1)

        db.add(ExtractedData(
            job_id            = job_id,
            filename          = filename,
            file_type         = file_type,
            s3_key            = s3_key,
            raw_text          = text,
            instructions_text = instructions or None,
            json_output       = annotated,
            consistent        = consistent,
            consistency_score = consistency.get("score", 0),
            total_questions   = len(annotated),
            total_points      = total_points,
            attempt           = attempt,
        ))

        job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
        job.status            = "passed" if consistent else "flagged"
        job.consistency_score = consistency.get("score", 0)
        job.total_points      = total_points
        job.retry_count       = attempt
        db.commit()

    except Exception as exc:
        db.rollback()
        job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
        if job:
            job.status        = "error"
            job.error_message = str(exc)[:500]
            db.commit()
        raise exc
    finally:
        db.close()
