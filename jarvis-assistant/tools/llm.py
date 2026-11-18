import json
import os
import urllib.request
from types import SimpleNamespace

_CLIENT = None


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        _CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _CLIENT


def _models() -> list[str]:
    return [
        os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        os.getenv("GEMINI_FALLBACK_MODEL", "gemini-1.5-flash"),
    ]


def generate(prompt: str, system: str = "", json_mode: bool = False, temperature: float = 0.0, tools=None):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key:
        for model in _models():
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": temperature}}
                if system:
                    payload["systemInstruction"] = {"parts": [{"text": system}]}
                if json_mode:
                    payload["generationConfig"]["responseMimeType"] = "application/json"
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                text = resp_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return SimpleNamespace(text=text)
            except Exception:
                continue
    client = _get_client()
    from google.genai import types
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
    try:
        resp = generate(prompt, system=system, temperature=temperature)
        return (resp.text or "").strip()
    except Exception as exc:
        return f"LLM error: {exc}"
