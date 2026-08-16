"""
Runs the full production extraction pipeline (same steps as
app/routers/jobs.py::_process_job) against every .docx file in
tests/input/Quiz, WITHOUT touching the database. Saves one JSON per
file to tests/output/test_results/integration/, plus a _summary.json.

Compare this output against tests/output/test_results/groundtruth/
(see generate_ground_truth.py) to check the full pipeline's field-level
accuracy against the hand-reviewed answer key.

Run from inside backend/:
    python tests/run_integration_test.py

Or point at a custom docx folder:
    python tests/run_integration_test.py /path/to/docx/folder

Or run a different model pair (see .env's MODEL_A_ID/MODEL_B_ID options)
into its OWN output folder, so it doesn't overwrite a previous run's
results — pass a second argument naming the output subfolder:
    python tests/run_integration_test.py tests/input/Quiz integration_llama_mistral

Results land in tests/output/test_results/<subfolder>/, defaulting to
"integration" when no subfolder name is given (unchanged behaviour).

To A/B test a prompt change without editing extractor.py or touching git,
pass a third argument naming the prompt variant ("old" or "new", see
tests/prompt_variants.py — currently isolates the ASSESSOR KEY
"CRITICAL — do not truncate..." paragraph added in commit b982274):
    python tests/run_integration_test.py tests/input/Quiz integration/result_oldprompt old
    python tests/run_integration_test.py tests/input/Quiz integration/result_newprompt new

That third argument is only a human-readable label (saved as prompt_label)
— it is NOT what makes two runs comparable. Every record also saves
prompt_fingerprint, a short hash of the exact SYSTEM_PROMPT text that was
actually sent to the model. Two runs used the identical prompt iff their
fingerprints match, regardless of what label (or none) was passed — so
this keeps working as you keep editing the prompt in the future without
having to invent a new label name every time.
"""

import asyncio
import csv
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# app/main.py configures this same logging setup when running under uvicorn,
# which is why [Extractor]/[Verifier]/[Verification] INFO logs are visible
# there. This script never imports app.main, so without this call those
# INFO-level logs (model start, question counts, verification scores, retry
# attempts) would be silently dropped — only WARNING+ would show.
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

import boto3

# Captures real per-call token usage straight from Bedrock's Converse API
# response, the same technique token_usage_probe.py uses — wrapping
# converse() directly means this works regardless of which model pair is
# active in .env, with no changes needed to extractor.py/verification.py.
# Previously token totals only existed as [Tokens] log lines that vanished
# at the end of the run; capturing them here means every future run saves
# its own totals into _summary.json, no separate probe run required.
_token_calls: list[dict] = []
_orig_boto3_client = boto3.client


def _patched_boto3_client(*args, **kwargs):
    client = _orig_boto3_client(*args, **kwargs)
    service = args[0] if args else kwargs.get("service_name")
    if service == "bedrock-runtime":
        orig_converse = client.converse

        def wrapped_converse(*a, **kw):
            resp = orig_converse(*a, **kw)
            usage = resp.get("usage") or {}
            _token_calls.append({
                "model_id":      kw.get("modelId"),
                "input_tokens":  usage.get("inputTokens"),
                "output_tokens": usage.get("outputTokens"),
                "total_tokens":  usage.get("totalTokens"),
            })
            return resp

        client.converse = wrapped_converse
    return client


boto3.client = _patched_boto3_client

from app.services import extractor as extractor_module
from app.services.classifier import classify_document_type
from app.services.verification import extract_and_verify
from app.services.converter import extract_document, parse_points_per_question
from app.services.grounding import check_question_grounding
from app.schemas.question import validate_questions
from tests.prompt_variants import get_prompt

DEFAULT_DOCX_DIR = os.path.join(os.path.dirname(__file__), "input", "Quiz")
DEFAULT_OUTPUT_SUBDIR = "integration"
DEFAULT_PROMPT_VARIANT = "new"


def _token_totals() -> dict:
    """Classifies the calls captured for the file just processed by model
    role (A/B, via MODEL_A_ID/MODEL_B_ID) and sums each into a small dict —
    called right after extract_and_verify() returns, before the next file's
    calls start accumulating in the same list."""
    model_a_id = os.getenv("MODEL_A_ID", "")
    model_b_id = os.getenv("MODEL_B_ID", "")

    def _sum(role_id, field):
        return sum(c[field] or 0 for c in _token_calls if c["model_id"] == role_id)

    return {
        "model_a_calls":      sum(1 for c in _token_calls if c["model_id"] == model_a_id),
        "model_a_input":      _sum(model_a_id, "input_tokens"),
        "model_a_output":     _sum(model_a_id, "output_tokens"),
        "model_a_total":      _sum(model_a_id, "total_tokens"),
        "model_b_calls":      sum(1 for c in _token_calls if c["model_id"] == model_b_id),
        "model_b_input":      _sum(model_b_id, "input_tokens"),
        "model_b_output":     _sum(model_b_id, "output_tokens"),
        "model_b_total":      _sum(model_b_id, "total_tokens"),
        "grand_total_input":  sum(c["input_tokens"]  or 0 for c in _token_calls),
        "grand_total_output": sum(c["output_tokens"] or 0 for c in _token_calls),
        "grand_total_tokens": sum(c["total_tokens"]  or 0 for c in _token_calls),
    }


# Same schema/location as token_usage_probe.py's comparison.csv, so a batch
# run here and a standalone probe run both feed the one file plot_token_usage.py
# reads — no need to run the separate probe just to get a plottable CSV.
TOKEN_CSV_FIELDS = [
    "branch", "arch", "filename", "timestamp", "attempt",
    "model_a_calls", "model_a_input", "model_a_output", "model_a_total",
    "model_b_calls", "model_b_input", "model_b_output", "model_b_total",
    "grand_total_input", "grand_total_output", "grand_total_tokens",
]


def _append_token_csv_row(branch: str, filename: str, attempt: int, tokens: dict):
    out_dir = os.path.join(os.path.dirname(__file__), "output", "test_results", "token_usage")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "comparison.csv")

    row = {
        "branch":    branch,
        "arch":      "run_integration_test.py (extract-then-verify)",
        "filename":  filename,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attempt":   attempt,
        **tokens,
    }

    write_header = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TOKEN_CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _flag_breakdown(annotated: list[dict]) -> dict:
    """
    Counts questions flagged=True (the canonical per-question definition,
    matching app/routers/jobs.py) plus a breakdown of which of the three
    independent signals caused it — flag_count alone can't tell you whether
    a file's flags are mostly A/B disagreement, schema errors, or
    hallucinations, and those call for very different fixes. The three
    reason counts can overlap (one question can trip more than one), so
    they won't necessarily sum to total.
    """
    return {
        "total":            sum(1 for q in annotated if q.get("flagged")),
        "low_consistency":  sum(1 for q in annotated if (q.get("consistency_score") or 1.0) < 0.90),
        "schema_invalid":   sum(1 for q in annotated if not q.get("schema_valid", True)),
        "hallucination":    sum(1 for q in annotated if q.get("hallucination_detected")),
    }


async def _run_one(filename: str, file_bytes: bytes, prompt_label: str, prompt_fingerprint: str) -> dict:
    text, instructions = extract_document(file_bytes, filename)
    file_type = classify_document_type(filename)

    _token_calls.clear()
    result = await extract_and_verify(text, filename)
    tokens = _token_totals()

    verification = result.get("verification", {})
    questions = result["normalised_a"].get("questions", [])

    rubric_points = parse_points_per_question(instructions)
    if rubric_points is not None:
        questions = [{**q, "points": rubric_points} for q in questions]

    total_points = sum(q.get("points") or 0 for q in questions)
    per_question = verification.get("details", {}).get("per_question", [])
    verified = verification.get("verified", False)
    missing_score_default = 1.0 if verified else 0.0

    annotated = []
    for i, q in enumerate(questions):
        pq = per_question[i] if i < len(per_question) else {}
        q_score = pq.get("score", missing_score_default)
        annotated.append({
            **q,
            "flagged": q_score < 0.90,
            "consistency_score": q_score,
            "issues": pq.get("issues", []),
        })

    annotated = validate_questions(annotated)
    for q in annotated:
        if not q["schema_valid"]:
            q["flagged"] = True

    for q in annotated:
        grounding = check_question_grounding(q, text)
        q["grounding_score"] = grounding["grounding_score"]
        q["hallucination_detected"] = grounding["hallucination_detected"]
        q["ungrounded_fields"] = grounding["ungrounded_fields"]
        if grounding["hallucination_detected"]:
            q["flagged"] = True

    verified = (
        verification.get("verified", False)
        and all(q["schema_valid"] for q in annotated)
        and not any(q["hallucination_detected"] for q in annotated)
    )

    flags = _flag_breakdown(annotated)
    details = verification.get("details", {})

    return {
        "filename": filename,
        "file_type": file_type,
        "prompt_label": prompt_label,
        "prompt_fingerprint": prompt_fingerprint,
        "model_a_id": os.getenv("MODEL_A_ID", ""),
        "model_b_id": os.getenv("MODEL_B_ID", ""),
        "verified": verified,
        "verification_score": verification.get("score", 0),
        # Model B's own recount of the source text vs how many questions
        # Model A's candidate has — a mismatch is the highest-priority signal
        # verification.py's retry hint acts on (see _build_retry_hint).
        "source_question_count": details.get("source_question_count"),
        "candidate_question_count": details.get("candidate_question_count"),
        "total_questions": len(annotated),
        "total_points": total_points,
        "attempt": result.get("attempt", 1),
        "flag_count": flags["total"],
        "flag_reasons": {k: v for k, v in flags.items() if k != "total"},
        "model_a_question_count": len(result["normalised_a"].get("questions", [])),
        "model_a_error": result["normalised_a"].get("error"),
        "tokens": tokens,
        "questions": annotated,
    }


async def main(docx_dir: str, output_subdir: str = DEFAULT_OUTPUT_SUBDIR, prompt_variant: str = DEFAULT_PROMPT_VARIANT):
    extractor_module.SYSTEM_PROMPT = get_prompt(prompt_variant)
    prompt_fingerprint = hashlib.sha256(extractor_module.SYSTEM_PROMPT.encode()).hexdigest()[:10]
    print(f"Prompt label       : {prompt_variant}")
    print(f"Prompt fingerprint : {prompt_fingerprint}")
    print(f"Model A            : {os.getenv('MODEL_A_ID', '')}")
    print(f"Model B            : {os.getenv('MODEL_B_ID', '')}")

    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results", output_subdir)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    docx_files = sorted(
        f for f in os.listdir(docx_dir)
        if f.endswith(".docx") and not f.startswith("~$")
    )

    if not docx_files:
        print(f"No DOCX files found in: {docx_dir}")
        return

    print(f"Found {len(docx_files)} files in: {docx_dir}")
    print(f"Output folder : {OUTPUT_DIR}")
    print("-" * 70)

    summary = []
    total_files = len(docx_files)

    for idx, filename in enumerate(docx_files, start=1):
        docx_path = os.path.join(docx_dir, filename)
        base_name = os.path.splitext(filename)[0]
        out_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")

        print(f"[{idx}/{total_files}] Starting {filename} ...")

        t0 = time.time()
        try:
            with open(docx_path, "rb") as f:
                file_bytes = f.read()

            record = await _run_one(filename, file_bytes, prompt_variant, prompt_fingerprint)
            elapsed = time.time() - t0

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)

            _append_token_csv_row(output_subdir, filename, record["attempt"], record["tokens"])

            status = "PASS" if record["verified"] else "FLAG"
            print(
                f"  {status} {filename} — {record['total_questions']}Q, "
                f"verification={record['verification_score']:.4f}, "
                f"flagged={record['flag_count']}, attempt={record['attempt']}, "
                f"tokens={record['tokens']['grand_total_tokens']}, "
                f"{elapsed:.1f}s"
            )
            summary.append({
                "filename": filename,
                "status": status,
                "prompt_label": record["prompt_label"],
                "prompt_fingerprint": record["prompt_fingerprint"],
                "verified": record["verified"],
                "verification_score": record["verification_score"],
                "source_question_count": record["source_question_count"],
                "candidate_question_count": record["candidate_question_count"],
                "total_questions": record["total_questions"],
                "total_points": record["total_points"],
                "flag_count": record["flag_count"],
                "flag_reasons": record["flag_reasons"],
                "attempt": record["attempt"],
                "model_a_question_count": record["model_a_question_count"],
                "model_a_error": record["model_a_error"],
                "tokens": record["tokens"],
                "elapsed_sec": round(elapsed, 1),
            })

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR {filename} → {e}")
            summary.append({
                "filename": filename,
                "status": "ERROR",
                "error": str(e),
                "elapsed_sec": round(elapsed, 1),
            })

    summary_path = os.path.join(OUTPUT_DIR, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("-" * 70)
    passed = sum(1 for s in summary if s.get("status") == "PASS")
    flagged = sum(1 for s in summary if s.get("status") == "FLAG")
    errored = sum(1 for s in summary if s.get("status") == "ERROR")
    print(f"Done: {passed} passed, {flagged} flagged, {errored} errored")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    docx_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOCX_DIR
    output_subdir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT_SUBDIR
    prompt_variant = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PROMPT_VARIANT
    asyncio.run(main(os.path.abspath(docx_dir), output_subdir, prompt_variant))
