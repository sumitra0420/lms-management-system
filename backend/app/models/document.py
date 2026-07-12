from pydantic import BaseModel
from enum import Enum
from typing import Optional


class PipelineStatus(str, Enum):
    UPLOADING = "uploading"
    CONVERTING = "converting"
    EXTRACTING = "extracting"
    CONSISTENCY_CHECK = "consistency_check"
    CONFLICT_RESOLVING = "conflict_resolving"
    VALIDATING = "validating"
    EVALUATING = "evaluating"
    VALIDATED = "validated"
    FLAGGED = "flagged"
    UPLOADED = "uploaded"
    FAILED = "failed"


class Choice(BaseModel):
    text: str
    correct: bool


class Question(BaseModel):
    id: str
    type: str  # MCQ, True/False, Short Answer
    text: str
    choices: list[Choice]
    points: float = 10.0
    feedback: Optional[str] = None
    confidence_score: Optional[float] = None
    flagged: bool = False
    flag_reason: Optional[str] = None


class ExtractionResult(BaseModel):
    questions: list[Question]
    confidence_score: float
    raw: dict


class ConsistencyReport(BaseModel):
    diff_percent: float
    passed: bool
    conflicts: list[dict]


class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: PipelineStatus
    questions: Optional[list[Question]] = None
    confidence_score: Optional[float] = None
    flag_count: int = 0
    message: str = ""
