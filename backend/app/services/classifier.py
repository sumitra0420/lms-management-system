def classify_document_type(filename: str) -> str:
    name = filename.lower()

    is_multiple_choice = "multiplechoice" in name or "multiple_choice" in name or "multiple choice" in name or "_mc." in name
    is_short_answer     = "shortanswer" in name or "short_answer" in name or "short answer" in name or "_sa." in name
    is_knowledge_test   = "knowledge test" in name

    # "Knowledge Test" / SA / MC filenames are quizzes even when "assessor"
    # also appears in the name (e.g. "... Knowledge Test 1 - Assessor Guide_SA.docx").
    if is_multiple_choice:
        return "quiz_multiple_choice"
    if is_short_answer:
        return "quiz_short_answer"
    if is_knowledge_test:
        return "quiz_short_answer"

    if "assessor" in name:
        return "assessor_guide"
    return "unknown"
