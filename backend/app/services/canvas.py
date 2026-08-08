import os

import httpx
from dotenv import load_dotenv

load_dotenv()


def _headers() -> dict:
    token = os.getenv("CANVAS_TOKEN", "").strip().strip('"')
    return {"Authorization": f"Bearer {token}"}


def _base_url() -> str:
    return os.getenv("CANVAS_BASE_URL", "").strip().strip('"').rstrip("/")


def create_quiz(course_id: int, title: str) -> dict:
    """
    Creates an empty, unpublished quiz in the given Canvas course. Returns
    Canvas's quiz object (we need its "id" to attach questions next).
    Unpublished so it never shows to students until someone in Canvas
    explicitly publishes it.
    """
    url = f"{_base_url()}/api/v1/courses/{course_id}/quizzes"
    body = {
        "quiz[title]": title,
        "quiz[quiz_type]": "assignment",
        "quiz[published]": "false",
    }
    response = httpx.post(url, headers=_headers(), data=body, timeout=30)
    response.raise_for_status()
    return response.json()


def add_mcq_question(course_id: int, quiz_id: int, question_text: str, options: list[str], correct_index: int, points: float = 1) -> dict:
    """
    Adds one multiple-choice question to an existing quiz. options[i] with
    i == correct_index gets full marks (answer_weight=100), every other
    option gets 0 — that's how Canvas represents "which option is right."

    Canvas's answers list is a Rails-style nested array, normally written
    as repeated "question[answers][][answer_text]" keys — but a plain dict
    can't hold the same key twice (a later option would just overwrite an
    earlier one). Using an explicit index per option instead
    ("question[answers][0][answer_text]", "...[1]...", ...) keeps every
    key unique, so a plain dict works and Canvas still parses it as the
    same nested array.
    """
    url = f"{_base_url()}/api/v1/courses/{course_id}/quizzes/{quiz_id}/questions"
    body = {
        "question[question_name]": question_text[:100],
        "question[question_text]": question_text,
        "question[question_type]": "multiple_choice_question",
        "question[points_possible]": str(points),
    }
    for i, opt in enumerate(options):
        body[f"question[answers][{i}][answer_text]"] = opt
        body[f"question[answers][{i}][answer_weight]"] = "100" if i == correct_index else "0"

    response = httpx.post(url, headers=_headers(), data=body, timeout=30)
    response.raise_for_status()
    return response.json()


def add_essay_question(course_id: int, quiz_id: int, question_text: str, expected_answer: str, points: float = 1) -> dict:
    """
    Adds one short-answer question to an existing quiz, as Canvas's
    "essay_question" type — Canvas doesn't auto-grade essay questions, so
    there's no answers[] array like MCQ has. expected_answer goes into
    neutral_comments, shown to whoever grades it manually as the marking
    guide, not compared against the student's response automatically.
    """
    url = f"{_base_url()}/api/v1/courses/{course_id}/quizzes/{quiz_id}/questions"
    body = {
        "question[question_name]": question_text[:100],
        "question[question_text]": question_text,
        "question[question_type]": "essay_question",
        "question[points_possible]": str(points),
        "question[neutral_comments]": expected_answer,
    }
    response = httpx.post(url, headers=_headers(), data=body, timeout=30)
    response.raise_for_status()
    return response.json()


def sync_question(course_id: int, quiz_id: int, question: dict) -> dict:
    """
    Bridges your pipeline's extracted-question schema (id/type/text/
    choices/correct_answer/points/feedback — see app/schemas/question.py)
    to the raw Canvas calls above. Dispatches on `type`.

    Only multiple_choice (single correct answer) and short_answer are
    handled so far — true_false and multi-select MCQ (more than one
    choice marked correct) aren't wired up yet, that's the next step
    after this one's confirmed working against real extracted data.
    """
    q_type = question.get("type")
    points = question.get("points") or 1

    if q_type == "multiple_choice":
        choices = question.get("choices") or []
        options = [c.get("text", "") for c in choices]
        correct_index = next((i for i, c in enumerate(choices) if c.get("correct")), 0)
        return add_mcq_question(course_id, quiz_id, question["text"], options, correct_index, points)

    if q_type == "short_answer":
        return add_essay_question(course_id, quiz_id, question["text"], question.get("correct_answer", ""), points)

    raise ValueError(f"Unsupported question type for Canvas sync yet: {q_type!r}")


if __name__ == "__main__":
    # Quick manual smoke test — run from inside backend/:
    #     python app/services/canvas.py
    quiz = create_quiz(course_id=3412, title="LMS Sync Test Quiz (test 1)")
    print("Created quiz id:", quiz["id"])
    print("URL:", quiz["html_url"])

    question = add_mcq_question(
        course_id=3412,
        quiz_id=quiz["id"],
        question_text="What is 2 + 2?",
        options=["3", "4", "5"],
        correct_index=1,
    )
    print("Added question id:", question["id"])

    essay_question = add_essay_question(
        course_id=3412,
        quiz_id=quiz["id"],
        question_text="Explain the Maillard reaction and why it matters in cooking.",
        expected_answer="A chemical browning reaction between amino acids and reducing sugars under dry heat, producing flavour/aroma compounds and a browned crust.",
    )
    print("Added essay question id:", essay_question["id"])
