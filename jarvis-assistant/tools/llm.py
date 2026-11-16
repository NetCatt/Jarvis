import os
from google import genai
from google.genai import types

_CLIENT = None


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _CLIENT


def _models() -> list[str]:
    # No third hardcoded fallback here on purpose: "gemini-2.5-flash" used to be one and is now a
    # confirmed 404 (deprecated for new users) — a dead fallback just adds a failing attempt before
    # the real error surfaces. If both configured models are exhausted/unavailable, that should
    # fail loudly rather than silently eat latency probing a model that no longer exists.
    return [
        os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash"),
    ]


def generate(prompt: str, system: str = "", json_mode: bool = False, temperature: float = 0.0, tools=None):
    """Shared Gemini call with model fallback. Returns the raw response object."""
    client = _get_client()
    cfg_kwargs = {"temperature": temperature}
    if system:
        cfg_kwargs["system_instruction"] = system
    if json_mode:
        cfg_kwargs["response_mime_type"] = "application/json"
    if tools:
        cfg_kwargs["tools"] = tools
        cfg_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
    cfg = types.GenerateContentConfig(**cfg_kwargs)

    last_exc = None
    for model in _models():
        try:
            return client.models.generate_content(model=model, contents=prompt, config=cfg)
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"All Gemini models failed: {last_exc}")


def generate_text(prompt: str, system: str = "", temperature: float = 0.0) -> str:
    """Convenience wrapper returning plain text, with a safe fallback message on total failure."""
    try:
        resp = generate(prompt, system=system, temperature=temperature)
        return (resp.text or "").strip()
    except Exception as exc:
        return f"LLM error: {exc}"
