from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

QuestionType = Literal["multiple_choice", "short_answer", "true_false"]


class Choice(BaseModel):
    text: str
    correct: bool = False


class Question(BaseModel):
    id: str
    type: QuestionType
    text: str
    choices: list[Choice] = []
    correct_answer: str = ""
    points: float | None = Field(default=None, ge=0)
    feedback: str = ""

    @field_validator("id", "text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


def validate_questions(questions: list[dict]) -> list[dict]:
    """
    Validate each extracted question against the Question schema.

    Extra keys already present on the dict (e.g. flagged, consistency_score,
    conflicts) are preserved untouched. On failure the question is kept as-is
    so nothing is silently dropped, but annotated with schema_valid=False and
    schema_errors so the UI can flag it for review.
    """
    validated = []
    for q in questions:
        try:
            Question.model_validate(q)
            validated.append({**q, "schema_valid": True, "schema_errors": []})
        except ValidationError as e:
            errors = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
            validated.append({**q, "schema_valid": False, "schema_errors": errors})
    return validated
