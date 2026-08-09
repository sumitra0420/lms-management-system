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


def add_mcq_question(course_id: int, quiz_id: int, question_text: str, options: list[str], correct_indices: list[int], points: float = 1) -> dict:
    """
    Adds one multiple-choice question to an existing quiz. options[i] with
    i in correct_indices gets full marks (answer_weight=100), every other
    option gets 0 — that's how Canvas represents "which option(s) are right."

    question_type switches automatically on how many correct answers there
    are: "multiple_choice_question" (radio buttons, exactly one correct)
    for a single correct index, "multiple_answers_question" (checkboxes,
    student must select ALL correct options for credit) when there's more
    than one — that's the actual "command" that tells Canvas a question
    accepts multiple answers, not something set on individual options.

    Canvas's answers list is a Rails-style nested array, normally written
    as repeated "question[answers][][answer_text]" keys — but a plain dict
    can't hold the same key twice (a later option would just overwrite an
    earlier one). Using an explicit index per option instead
    ("question[answers][0][answer_text]", "...[1]...", ...) keeps every
    key unique, so a plain dict works and Canvas still parses it as the
    same nested array.
    """
    question_type = "multiple_answers_question" if len(correct_indices) > 1 else "multiple_choice_question"
    url = f"{_base_url()}/api/v1/courses/{course_id}/quizzes/{quiz_id}/questions"
    body = {
        "question[question_name]": question_text[:100],
        "question[question_text]": question_text,
        "question[question_type]": question_type,
        "question[points_possible]": str(points),
    }
    for i, opt in enumerate(options):
        body[f"question[answers][{i}][answer_text]"] = opt
        body[f"question[answers][{i}][answer_weight]"] = "100" if i in correct_indices else "0"

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

    multiple_choice (single or multi-select — see add_mcq_question) and
    short_answer are handled. true_false has zero real occurrences across
    your whole dataset (checked before building this), so it's not wired
    up — not worth the code until it actually shows up in a document.
    """
    q_type = question.get("type")
    points = question.get("points") or 1

    if q_type == "multiple_choice":
        choices = question.get("choices") or []
        options = [c.get("text", "") for c in choices]
        correct_indices = [i for i, c in enumerate(choices) if c.get("correct")]
        return add_mcq_question(course_id, quiz_id, question["text"], options, correct_indices, points)

    if q_type == "short_answer":
        return add_essay_question(course_id, quiz_id, question["text"], question.get("correct_answer", ""), points)

    raise ValueError(f"Unsupported question type for Canvas sync yet: {q_type!r}")


if __name__ == "__main__":
    # Smoke test against REAL extracted data (not hardcoded examples), to
    # prove sync_question() actually bridges your pipeline's real output —
    # temporary, pulls straight from a tests/ result file; will go away
    # once this is wired up behind a real API endpoint.
    #
    # This run syncs EVERY question from one full file (22 MCQ questions),
    # not just one — the earlier step proved single-question mapping,
    # this proves the whole-quiz pattern before wiring a real endpoint.
    #     python app/services/canvas.py
    import json

    result_dir = "tests/output/test_results/integration/result_oldprompt_v2"
    mcq_file = f"{result_dir}/SIRXCEG008 Knowledge Test 2 - Assessor Guide_MC.json"

    with open(mcq_file, encoding="utf-8") as f:
        record = json.load(f)
        mcq_questions = record["questions"]

    quiz = create_quiz(course_id=3412, title=f"LMS Sync Test — {record['filename']}")
    print("Created quiz id:", quiz["id"])
    print("URL:", quiz["html_url"])
    print(f"Syncing {len(mcq_questions)} questions...")

    failures = []
    for q in mcq_questions:
        try:
            created = sync_question(course_id=3412, quiz_id=quiz["id"], question=q)
            print(f"  {q['id']} -> Canvas question id {created['id']}")
        except Exception as e:
            print(f"  {q['id']} -> FAILED: {e}")
            failures.append(q["id"])

    print(f"\nDone: {len(mcq_questions) - len(failures)}/{len(mcq_questions)} synced")
    if failures:
        print("Failed:", failures)
