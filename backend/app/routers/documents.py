from fastapi import APIRouter, UploadFile, File, HTTPException

from app.services.converter import docx_to_text
from app.services.consistency import check_with_retry

router = APIRouter()


@router.post("/documents/process")
async def process_document(file: UploadFile = File(...)):
    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    contents = await file.read()

    try:
        text   = docx_to_text(contents, file.filename)
        result = await check_with_retry(text)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not extract quiz content: {exc}")

    consistency  = result.get("consistency", {})
    questions    = result["normalised_a"].get("questions", [])
    total_points = sum(float(q.get("points", 0)) for q in questions)

    return {
        "filename":            file.filename,
        "consistent":          consistency.get("consistent", False),
        "consistency_score":   consistency.get("score", 0),
        "attempt":             result.get("attempt", 1),
        "total_points":        total_points,
        "questions":           questions,
        "consistency_details": consistency.get("details", {}),
    }
