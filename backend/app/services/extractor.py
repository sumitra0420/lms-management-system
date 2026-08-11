import asyncio
import json
import logging
import os

import boto3
import httpx
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# botocore's default read_timeout (60s) is too short for slower models
# generating up to maxTokens=8192 against a long document — Claude/Nova
# happened to always finish inside that window, which is why this never
# surfaced until testing a slower model (Mistral Large hit a hard Read
# timeout mid-response on a ~20K-character document).
_BEDROCK_CLIENT_CONFIG = Config(read_timeout=300, connect_timeout=10)

SYSTEM_PROMPT = """You are an expert assessment-question parser for vocational education documents.

Extract every learner-facing question and return STRICT valid JSON only.

━━━ GOLDEN RULES ━━━
- NO HALLUCINATIONS: Use the exact source text. Do not invent, rephrase, summarise, or correct anything.
- LEARNER-FACING ONLY: Extract questions students must answer. Ignore cover pages, global instructions,
  policies, assessor signatures, date fields, result boxes, and feedback sections.
- EXACT SCHEMA: Output must match the JSON structure below exactly. No extra fields, no markdown fences.

━━━ SPECIAL LABEL RULES ━━━

ASSESSOR KEY:
  Marks the correct answer(s). A single question may have MULTIPLE "ASSESSOR KEY:" lines —
  each is one accepted answer bullet. Concatenate ALL of them into correct_answer, separated by " | ".
  Strip the "ASSESSOR KEY:" prefix from the value.
  Example: two bullets → correct_answer = "Product releases or launches | Promotional events to draw attention to the company"

  CRITICAL — do not truncate based on the question wording: when the question text asks the
  LEARNER for a specific count (e.g. "What are three (3) examples of…"), that number is how many
  the learner must give — it is NOT a cap on how many ASSESSOR KEY bullets you extract. The source
  document's marking guide often lists MORE acceptable answers than the question asks for, so any
  of them can count as correct. You MUST include every single ASSESSOR KEY bullet found for that
  question, even if there are 6, 9, or more of them for a "three (3) examples" question. Never stop
  early because you've reached the number mentioned in the question.

ANSWER GUIDANCE:
  A marking instruction that describes how many answers are needed and whether the list is flexible
  ("Answer may address, but is not limited to…") or strict ("Answer must address:").
  Store this line verbatim in the feedback field.
  Do NOT include it in correct_answer. Do NOT include it in question text.

OPTION:
  Marks a selectable multiple-choice option that is NOT the correct answer (an incorrect
  distractor). Combined with any ASSESSOR KEY lines for the same question, OPTION lines make up
  the complete choices[] list — OPTION lines are incorrect options, ASSESSOR KEY lines are correct
  options. Never drop OPTION lines and never fold them into correct_answer.

━━━ QUESTION TYPE RULES ━━━

STRUCTURAL SIGNAL OVERRIDES WORDING — read this first:
  If a question is followed by ANY "OPTION:" line(s) before the next question, it IS a
  multiple_choice question — full stop, regardless of how the question is phrased. Include every
  "OPTION:" line AND every "ASSESSOR KEY:" line for that question in choices[]. This applies even
  when the question reads like an open recall prompt, e.g. "What are three (3) possible actions…"
  or "What are four (4) examples of…" — that wording does NOT make it short_answer if OPTION
  lines are present. Only classify a question as short_answer when it has NO "OPTION:" lines at
  all for it — just ASSESSOR KEY / ANSWER GUIDANCE lines and nothing else listed alongside them.

multiple_choice — SINGLE correct answer:
  Question has selectable options and exactly one is correct.
  List ALL options in choices[]. Set "correct": true on the one correct option only.
  Put the correct option text in correct_answer as well.

  META-OPTION TRAP — "All of the above" / "None of the above": if the ASSESSOR KEY option's
  text IS a meta-option like "All of the above" or "None of the above", that meta-option is
  ITSELF the single correct choice — include it verbatim in choices[] with "correct": true, and
  correct_answer set to its literal text ("All of the above"). Do NOT interpret its meaning by
  marking the other listed OPTION lines "correct": true instead — they stay "correct": false, and
  the meta-option's own text must not be dropped from choices[].

multiple_choice — MULTIPLE correct answers:
  Question asks to select N options (e.g. "Select THREE", "select all that apply"),
  or multiple options are marked with ASSESSOR KEY, or (per the structural rule above) it has
  OPTION lines with more than one ASSESSOR KEY line among them.
  List ALL options (OPTION + ASSESSOR KEY lines) in choices[]. Set "correct": true on every
  ASSESSOR KEY option. Put all correct option texts in correct_answer joined by " | ".

short_answer:
  Open-ended question followed ONLY by ASSESSOR KEY lines or ANSWER GUIDANCE — no OPTION lines.
  Set choices to []. Concatenate all ASSESSOR KEY lines into correct_answer.
  Put the ANSWER GUIDANCE line in feedback.

true_false:
  Question answered with True or False.
  Set choices to [{"text":"True","correct":<bool>},{"text":"False","correct":<bool>}].

━━━ POINTS RULES ━━━
- Use the explicit mark/point value stated near the question (e.g. "3 marks" → points: 3).
- If no value is stated anywhere near the question, set points to null. Do NOT invent
  or assume a default value — a global mark-per-question value, if one exists, is applied
  separately from the assessment's instructions block, not guessed here.

━━━ OUTPUT FORMAT ━━━
Return ONLY this JSON structure with no explanation outside the JSON:
{
  "questions": [
    {
      "id": "Q1",
      "type": "short_answer",
      "text": "exact learner-facing question text here",
      "choices": [],
      "correct_answer": "answer one | answer two | answer three",
      "points": 1,
      "feedback": "Answer may address, but is not limited to, three of the following"
    }
  ]
}"""


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _extract_json_from_text(text: str) -> str:
    text = text.strip()
    if text.startswith("{"):
        return text
    for fence in ("```json", "```"):
        if fence in text:
            start = text.index(fence) + len(fence)
            try:
                end = text.index("```", start)
                return text[start:end].strip()
            except ValueError:
                pass  # no closing fence — fall through to brace scan
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _recover_partial_json(text: str) -> dict | None:
    """
    Try to salvage complete question objects from a truncated or malformed
    JSON string.  Scans backwards from the end for the last position where
    a complete question object closes ('}'), rebuilds a valid JSON envelope,
    and returns the parsed dict — or None if nothing could be recovered.
    """
    import re
    match = re.search(r'"questions"\s*:\s*\[', text)
    if not match:
        return None

    prefix  = text[:match.end()]   # everything up to and including '['
    content = text[match.end():]   # everything after '['

    # Scan backwards: each '}' could be the end of the last complete question.
    for m in reversed(list(re.finditer(r'\}', content))):
        candidate = prefix + content[:m.end()].rstrip(',').rstrip() + ']}'
        try:
            data = json.loads(candidate)
            if data.get('questions'):
                return data
        except json.JSONDecodeError:
            continue

    return None


def _normalise(raw_json: str, source: str, filename: str = "") -> dict:
    json_text = _extract_json_from_text(raw_json)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        # Primary parse failed — attempt partial recovery before giving up.
        # Handles cases where the model truncates mid-response or emits an
        # unescaped character inside a long JSON string.
        recovered = _recover_partial_json(json_text)
        if recovered and recovered.get("questions"):
            logger.warning(
                f"[Extractor] [{filename}] Partial JSON recovery for {source}: "
                f"salvaged {len(recovered['questions'])} questions (original error: {e})"
            )
            data = recovered
        else:
            return {"error": f"JSON parse failed ({source}): {e}", "questions": []}

    normalised_questions = []
    for q in data.get("questions", []):
        choices = []
        for c in q.get("choices") or []:
            choices.append({
                "text":    str(c.get("text") or ""),
                "correct": bool(c.get("correct") or False),
            })
        raw_points = q.get("points")
        normalised_questions.append({
            "id":             str(q.get("id") or ""),
            "type":           str(q.get("type") or "short_answer"),
            "text":           str(q.get("text") or ""),
            "choices":        choices,
            "correct_answer": str(q.get("correct_answer") or ""),
            "points":         float(raw_points) if raw_points is not None else None,
            "feedback":       str(q.get("feedback") or ""),
        })

    return {"questions": normalised_questions}


# ---------------------------------------------------------------------------
# OpenAI-compatible models (openai.*) — uses /v1/responses via httpx
# ---------------------------------------------------------------------------

async def _extract_openai(text: str, api_key: str, base_url: str, model_id: str, system_prompt: str) -> str:
    url = f"{base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model_id,
        "input": f"{system_prompt}\n\n{text}",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers=headers, json=body)

    if r.status_code >= 400:
        raise RuntimeError(f"Bedrock error {r.status_code} ({model_id}): {r.text}")

    data = r.json()

    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                t = content.get("text", "")
                if t.strip():
                    return t
            if content.get("type") == "output_json":
                return json.dumps(content.get("json", {}))

    raise RuntimeError(f"No text found in response from {model_id}: {json.dumps(data)[:300]}")


# ---------------------------------------------------------------------------
# Anthropic Claude models (anthropic.*) — uses AnthropicBedrockMantle
# ---------------------------------------------------------------------------

async def _extract_bedrock_iam(text: str, region: str, model_id: str, system_prompt: str) -> str:
    # Converse API works for ALL Bedrock models (Claude, OpenAI, etc.)
    # boto3 reads AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from environment
    def _invoke():
        client = boto3.client("bedrock-runtime", region_name=region, config=_BEDROCK_CLIENT_CONFIG)
        response = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": text}]}],
            inferenceConfig={"maxTokens": 8192},
        )
        return response["output"]["message"]["content"][0]["text"]

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _invoke)


# ---------------------------------------------------------------------------
# Dispatcher — picks the right client based on model ID prefix
# ---------------------------------------------------------------------------

async def _extract_model(text: str, api_key_env: str, base_url_env: str, model_id_env: str, region_env: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    api_key  = os.getenv(api_key_env, "")
    base_url = os.getenv(base_url_env, "")
    model_id = os.getenv(model_id_env, "")
    # Per-model region override — some Bedrock cross-region inference
    # profiles (e.g. Llama's "us." profiles) only resolve when the client
    # is pointed at a region within that profile's group, not the account's
    # default region. Falls back to the shared AWS_REGION when no override
    # is set, so existing single-region setups are unaffected.
    region   = os.getenv(region_env) or os.getenv("AWS_REGION", "ap-southeast-2")

    if base_url:
        # bedrock-mantle Quickstart bearer token via httpx
        return await _extract_openai(text, api_key, base_url, model_id, system_prompt)
    else:
        # IAM-based via Converse API — works for Claude, OpenAI, and any Bedrock model
        return await _extract_bedrock_iam(text, region, model_id, system_prompt)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract(text: str, filename: str = "") -> dict:
    """
    Run Model A and Model B in parallel.
    Routes to the correct client based on model ID prefix.
    """
    model_a_id = os.getenv("MODEL_A_ID", "")
    model_b_id = os.getenv("MODEL_B_ID", "")
    logger.info(f"[Extractor] [{filename}] Starting dual extraction | Model A: {model_a_id} | Model B: {model_b_id}")

    raw_a, raw_b = await asyncio.gather(
        _extract_model(text, "MODEL_A_API_KEY", "MODEL_A_BASE_URL", "MODEL_A_ID", "MODEL_A_REGION"),
        _extract_model(text, "MODEL_B_API_KEY", "MODEL_B_BASE_URL", "MODEL_B_ID", "MODEL_B_REGION"),
    )

    norm_a = _normalise(raw_a, "model_a", filename)
    norm_b = _normalise(raw_b, "model_b", filename)

    logger.info(f"[Extractor] [{filename}] Model A → {len(norm_a.get('questions', []))} questions | error: {norm_a.get('error')}")
    logger.info(f"[Extractor] [{filename}] Model B → {len(norm_b.get('questions', []))} questions | error: {norm_b.get('error')}")
    logger.debug(f"[Extractor] [{filename}] Raw A (first 800 chars):\n{raw_a[:800]}")
    logger.debug(f"[Extractor] [{filename}] Raw B (first 800 chars):\n{raw_b[:800]}")

    return {
        "raw_a": raw_a,
        "raw_b": raw_b,
        "normalised_a": norm_a,
        "normalised_b": norm_b,
    }


async def extract_a_only(text: str, filename: str = "") -> dict:
    """
    Run Model A alone — the extractor half of the verify-and-retry flow,
    where Model B's job is checking A's output (see verify_extraction)
    instead of independently re-extracting the whole document.
    """
    model_a_id = os.getenv("MODEL_A_ID", "")
    logger.info(f"[Extractor] [{filename}] Starting Model A extraction | Model A: {model_a_id}")

    raw_a = await _extract_model(text, "MODEL_A_API_KEY", "MODEL_A_BASE_URL", "MODEL_A_ID", "MODEL_A_REGION")
    norm_a = _normalise(raw_a, "model_a", filename)

    logger.info(f"[Extractor] [{filename}] Model A → {len(norm_a.get('questions', []))} questions | error: {norm_a.get('error')}")
    logger.debug(f"[Extractor] [{filename}] Raw A (first 800 chars):\n{raw_a[:800]}")

    return {"raw_a": raw_a, "normalised_a": norm_a}


# ---------------------------------------------------------------------------
# Verification (Model B checks Model A's candidate JSON against the source
# text, instead of independently re-extracting from scratch)
# ---------------------------------------------------------------------------

VERIFY_SYSTEM_PROMPT = """You are a strict fact-checker for an AI-extracted vocational assessment quiz.

You are given SOURCE TEXT (the original document) and a CANDIDATE EXTRACTION (JSON produced by
another AI from that text). Your only job is to check whether the candidate is a faithful,
complete extraction of the source — you do NOT re-extract or invent an alternative version.

Check every question in the candidate against these rules:

QUESTION COUNT:
  Every numbered/lettered question in the source text must appear exactly once in the candidate.
  Do not count multi-part sub-questions as merged into one, and do not count any question twice.

TEXT FIDELITY:
  Each question's "text" must match the source verbatim (not paraphrased, summarised, or truncated).

TYPE CLASSIFICATION:
  If a question is followed by any "OPTION:" line(s) in the source, it MUST be classified
  "multiple_choice" (or "true_false" for a True/False option pair) — regardless of question wording.
  Only "short_answer" when there are NO "OPTION:" lines, just ASSESSOR KEY / ANSWER GUIDANCE lines.

ANSWER COMPLETENESS:
  "correct_answer" must include EVERY "ASSESSOR KEY:" bullet from the source for that question,
  verbatim, joined by " | " — never fewer than the source lists, even if the question wording
  asks for a smaller number than the source's marking guide provides.

CHOICES COMPLETENESS (multiple_choice only):
  "choices" must include every "OPTION:" line AND every "ASSESSOR KEY:" line as one combined list,
  each marked "correct": true only for ASSESSOR KEY entries.

NO HALLUCINATION:
  Every field's content must actually appear in the source text — nothing invented or corrected.

━━━ OUTPUT FORMAT ━━━
Return ONLY this JSON with no explanation outside it:
{
  "valid": true,
  "source_question_count": 0,
  "candidate_question_count": 0,
  "issues": [
    {"question_id": "Q5", "field": "type", "problem": "Has OPTION lines in source but classified as short_answer"}
  ]
}
"valid" is true only when "issues" is empty. Be specific in "problem" — it is used verbatim to
tell the extracting model what to fix, so name the exact question and what's wrong with it."""


def _normalise_verification(raw_json: str) -> dict:
    json_text = _extract_json_from_text(raw_json)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        # Fail closed: if the verifier's own output can't be parsed, treat the
        # candidate as unverified rather than silently trusting it.
        return {
            "valid": False,
            "source_question_count": None,
            "candidate_question_count": None,
            "issues": [{"question_id": "", "field": "", "problem": f"Verifier response was not valid JSON: {e}"}],
        }

    return {
        "valid":                     bool(data.get("valid", False)),
        "source_question_count":     data.get("source_question_count"),
        "candidate_question_count":  data.get("candidate_question_count"),
        "issues": [
            {
                "question_id": str(i.get("question_id") or ""),
                "field":       str(i.get("field") or ""),
                "problem":     str(i.get("problem") or ""),
            }
            for i in (data.get("issues") or [])
        ],
    }


async def verify_extraction(text: str, candidate_json: dict, filename: str = "") -> dict:
    """
    Model B checks Model A's candidate JSON against the source text and
    reports whether it's faithful/complete — a narrower, easier task than
    independently re-extracting the whole document, so it isn't sunk by
    Model B's weaker performance on the harder task.
    """
    model_b_id = os.getenv("MODEL_B_ID", "")
    verify_input = (
        f"SOURCE TEXT:\n{text}\n\n"
        f"CANDIDATE EXTRACTION (JSON):\n{json.dumps(candidate_json, indent=2)}"
    )

    raw = await _extract_model(
        verify_input, "MODEL_B_API_KEY", "MODEL_B_BASE_URL", "MODEL_B_ID", "MODEL_B_REGION",
        system_prompt=VERIFY_SYSTEM_PROMPT,
    )
    result = _normalise_verification(raw)

    logger.info(
        f"[Verifier] [{filename}] Model B ({model_b_id}) → valid={result['valid']} "
        f"issues={len(result['issues'])} "
        f"(source_count={result['source_question_count']}, candidate_count={result['candidate_question_count']})"
    )
    if result["issues"]:
        # Only the compact summary line above shows during normal server runs —
        # this prints the actual problem text per question so you don't need
        # to open the job-detail JSON just to see what Model B flagged.
        logger.info(f"[Verifier] [{filename}] Issues:\n{json.dumps(result['issues'], indent=2)}")
    logger.debug(f"[Verifier] [{filename}] Raw verify response (first 800 chars):\n{raw[:800]}")

    return result


if __name__ == "__main__":
    # Standalone smoke test for the new extract-then-verify pair, run before
    # wiring it into consistency.py's retry loop. Usage:
    #   python app/services/extractor.py "tests/input/Quiz/<some file>.docx"
    import sys
    from app.services.converter import extract_document

    path = sys.argv[1] if len(sys.argv) > 1 else "tests/input/Quiz/SITHCCC029_Knowledge_Test_ShortAnswer.docx"
    with open(path, "rb") as f:
        file_bytes = f.read()
    doc_text, _ = extract_document(file_bytes, path)

    async def _run():
        print(f"--- Extracting with Model A from {path} ---")
        a_result = await extract_a_only(doc_text, path)
        questions = a_result["normalised_a"].get("questions", [])
        print(f"Model A extracted {len(questions)} questions "
              f"(error: {a_result['normalised_a'].get('error')})\n")

        print("--- Verifying with Model B ---")
        verification = await verify_extraction(doc_text, a_result["normalised_a"], path)
        print(json.dumps(verification, indent=2))

    asyncio.run(_run())
