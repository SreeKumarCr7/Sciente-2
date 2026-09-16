"""Gemini fallback extraction and configurable token cost accounting."""

import json
import os

from dotenv import load_dotenv

load_dotenv()


class LLMConfigurationError(RuntimeError):
    """Raised when the fallback provider is not configured."""


def _settings() -> tuple[str, str, float, float]:
    provider = os.getenv("LLM_PROVIDER", "Google").strip().lower()
    model = os.getenv("LLM_MODEL", "gemini-2.5-flash").strip()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if provider != "google":
        raise LLMConfigurationError("LLM_PROVIDER must be Google for Gemini fallback.")
    if not api_key:
        raise LLMConfigurationError("GEMINI_API_KEY is missing from the environment.")
    if not model:
        raise LLMConfigurationError("LLM_MODEL is missing from the environment.")
    try:
        input_price = float(os.getenv("LLM_INPUT_COST_PER_1M_TOKENS", ""))
        output_price = float(os.getenv("LLM_OUTPUT_COST_PER_1M_TOKENS", ""))
    except ValueError as error:
        raise LLMConfigurationError("Gemini token pricing must be numeric.") from error
    return api_key, model, input_price, output_price

def empty_cost_log() -> dict[str, object]:
    """Return the cost shape used by the UI and future fallback calls."""
    return {
        "fallback_calls": 0,
        "model": os.getenv("LLM_MODEL", "gemini-2.5-flash"),
        "input_tokens": 0,
        "output_tokens": 0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "total_cost": 0.0,
    }


def llm_fallback(field: str, relevant_content: str) -> tuple[dict[str, object], dict[str, object]]:
    """Ask Gemini for one unresolved field and return its result plus call cost."""
    api_key, model, input_price, output_price = _settings()
    if not relevant_content.strip():
        return {
            "field": field, "value": "not_found", "year": None, "unit": None,
            "evidence": None, "page": None, "status": "not_found",
        }, _call_cost(model, 0, 0, input_price, output_price)

    from google import genai

    prompt = f"""Extract exactly one financial statement field from the supplied document context.
Field required: {field}

Document context:
{relevant_content}

Rules:
- Use only the supplied document context. Never guess or calculate a missing field.
- Preserve the reported value, year, and unit exactly when available.
- Include supporting evidence and page when available.
- Return status \"found\" only when the context supports the field.
- Return status \"not_found\" and value \"not_found\" when it is absent.
- Return only valid JSON matching the requested structure.
"""
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "OBJECT",
                    "properties": {
                        "field": {"type": "STRING"},
                        "value": {"type": "STRING"},
                        "year": {"type": "STRING", "nullable": True},
                        "unit": {"type": "STRING", "nullable": True},
                        "evidence": {"type": "STRING", "nullable": True},
                        "page": {"type": "INTEGER", "nullable": True},
                        "status": {"type": "STRING"},
                    },
                    "required": ["field", "value", "year", "unit", "evidence", "page", "status"],
                },
            },
        )
        raw_json = getattr(response, "text", "") or ""
        result = json.loads(raw_json)
        if result.get("field") != field or result.get("status") not in {"found", "not_found"}:
            raise ValueError("Gemini returned an invalid field result.")
        if result["status"] == "found" and (
            not isinstance(result.get("value"), str)
            or not result["value"].strip()
            or result["value"] == "not_found"
        ):
            raise ValueError("Gemini marked an empty value as found.")
        if result["status"] == "not_found":
            result["value"] = "not_found"
        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        return result, _call_cost(model, input_tokens, output_tokens, input_price, output_price)
    except Exception as error:
        raise RuntimeError(f"Gemini fallback failed for {field}: {error}") from error


def _call_cost(model: str, input_tokens: int, output_tokens: int, input_price: float, output_price: float) -> dict[str, object]:
    input_cost = input_tokens / 1_000_000 * input_price
    output_cost = output_tokens / 1_000_000 * output_price
    return {
        "fallback_calls": 1,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + output_cost,
    }