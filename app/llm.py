"""Swappable LLM layer. Any OpenAI-compatible provider (default: Groq free tier)."""
import json
import os

import httpx


class LLMError(Exception):
    pass


def config():
    return {
        "key": os.environ.get("LLM_API_KEY", ""),
        "base": os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        "model": os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile"),
    }


def enabled() -> bool:
    return bool(config()["key"])


def public_status():
    c = config()
    host = c["base"].split("//")[-1].split("/")[0]
    return {"enabled": enabled(), "provider_host": host, "model": c["model"]}


def chat_json(system: str, user: str) -> dict:
    c = config()
    try:
        r = httpx.post(
            c["base"].rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + c["key"]},
            json={
                "model": c["model"],
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.1,
                "max_tokens": 1800,
                "response_format": {"type": "json_object"},
            },
            timeout=40,
        )
    except httpx.HTTPError:
        raise LLMError("The AI service could not be reached. Rule checks still ran.")
    if r.status_code == 429:
        raise LLMError("The AI service is rate-limited right now. Rule checks still ran; try again in a minute.")
    if r.status_code >= 400:
        raise LLMError(f"The AI service returned an error ({r.status_code}). Rule checks still ran.")
    try:
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception:
        raise LLMError("The AI service returned an unreadable answer. Rule checks still ran.")
