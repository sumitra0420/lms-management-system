import asyncio
import json
import os

import boto3
import httpx
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """You are an expert at extracting quiz questions from vocational education assessment documents.

Extract every question from the text and return a JSON object.

Rules:
- Lines starting with "ASSESSOR KEY:" contain the correct answers — use them for correct_answer
- Points/marks are usually stated next to the question (e.g. "4 marks")
- For multiple_choice: list all options in choices array, mark the correct one with "correct": true
- For short_answer: put the assessor key text in correct_answer, leave choices as empty array
- For true_false: use choices array with True and False, mark the correct one

Return ONLY this JSON structure with no explanation outside the JSON:
{
  "questions": [
    {
      "id": "Q1",
      "type": "short_answer",
      "text": "full question text here",
      "choices": [],
      "correct_answer": "assessor key answer here",
      "points": 4,
      "feedback": ""
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


def _normalise(raw_json: str, source: str) -> dict:
    try:
        data = json.loads(_extract_json_from_text(raw_json))
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed ({source}): {e}", "questions": []}

    normalised_questions = []
    for q in data.get("questions", []):
        choices = []
        for c in q.get("choices", []):
            choices.append({
                "text": str(c.get("text", "")),
                "correct": bool(c.get("correct", False)),
            })
        normalised_questions.append({
            "id": str(q.get("id", "")),
            "type": str(q.get("type", "short_answer")),
            "text": str(q.get("text", "")),
            "choices": choices,
            "correct_answer": str(q.get("correct_answer", "")),
            "points": float(q.get("points", 0)),
            "feedback": str(q.get("feedback", "")),
        })

    return {"questions": normalised_questions}


# ---------------------------------------------------------------------------
# OpenAI-compatible models (openai.*) — uses /v1/responses via httpx
# ---------------------------------------------------------------------------

async def _extract_openai(text: str, api_key: str, base_url: str, model_id: str) -> str:
    url = f"{base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model_id,
        "input": f"{SYSTEM_PROMPT}\n\n{text}",
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

async def _extract_bedrock_iam(text: str, region: str, model_id: str) -> str:
    # Converse API works for ALL Bedrock models (Claude, OpenAI, etc.)
    # boto3 reads AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from environment
    def _invoke():
        client = boto3.client("bedrock-runtime", region_name=region)
        response = client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": text}]}],
            inferenceConfig={"maxTokens": 4096},
        )
        return response["output"]["message"]["content"][0]["text"]

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _invoke)


# ---------------------------------------------------------------------------
# Dispatcher — picks the right client based on model ID prefix
# ---------------------------------------------------------------------------

async def _extract_model(text: str, api_key_env: str, base_url_env: str, model_id_env: str) -> str:
    api_key  = os.getenv(api_key_env, "")
    base_url = os.getenv(base_url_env, "")
    model_id = os.getenv(model_id_env, "")
    region   = os.getenv("AWS_REGION", "ap-southeast-2")

    if base_url:
        # bedrock-mantle Quickstart bearer token via httpx
        return await _extract_openai(text, api_key, base_url, model_id)
    else:
        # IAM-based via Converse API — works for Claude, OpenAI, and any Bedrock model
        return await _extract_bedrock_iam(text, region, model_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract(text: str) -> dict:
    """
    Run Model A and Model B in parallel.
    Routes to the correct client based on model ID prefix.
    """
    raw_a, raw_b = await asyncio.gather(
        _extract_model(text, "MODEL_A_API_KEY", "MODEL_A_BASE_URL", "MODEL_A_ID"),
        _extract_model(text, "MODEL_B_API_KEY", "MODEL_B_BASE_URL", "MODEL_B_ID"),
    )
    return {
        "raw_a": raw_a,
        "raw_b": raw_b,
        "normalised_a": _normalise(raw_a, "model_a"),
        "normalised_b": _normalise(raw_b, "model_b"),
    }
