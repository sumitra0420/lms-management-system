def classify_document_type(filename: str) -> str:
    name = filename.lower()
    if "assessor" in name:
        return "assessor_guide"
    if "multiplechoice" in name or "multiple_choice" in name or "multiple choice" in name:
        return "quiz_multiple_choice"
    if "shortanswer" in name or "short_answer" in name or "short answer" in name or "_sa." in name:
        return "quiz_short_answer"
    return "unknown"
