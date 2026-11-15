import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tools import TOOL_FUNCTIONS, TOOL_MAP

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)
load_dotenv()
_CLIENT = None
PROMPT = (
    "You are Mike Ross (nickname Mike), an AI Technical Project Lead and Windows 10 orchestrator for Fas. "
    "Always address the user as Fas when speaking. "
    "Sync repo progress via sync_coding_progress. Manage Google Tasks via add_task, update_task_progress, "
    "complete_task, list_agenda. Plan next agent steps via write_agent_plan. "
    "When asked to play a song or music, use play_music(song, platform). If platform is not specified, leave platform empty so Mike asks whether Spotify or YouTube. "
    "If Fas answers 'Spotify', 'YouTube', 'on Spotify', or 'on YouTube', always route to play_music(song='', platform=...) instead of open_app. "
    "When asked to search something on Google or browser, use search_google(query). "
    "When asked to open the browser or a website, use open_browser(url). Launch desktop apps via open_app. "
    "Return crisp, spoken replies (max 2 sentences, ∅ markdown symbols)."
)


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _CLIENT


def route_command(user_text: str) -> str:
    """Route natural language to deterministic tools in single RTT."""
    client = _get_client()
    cfg = types.GenerateContentConfig(
        system_instruction=PROMPT, temperature=0.0, tools=TOOL_FUNCTIONS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )
    for model in (os.getenv("GEMINI_MODEL", "gemini-3.5-flash"), os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")):
        try:
            resp = client.models.generate_content(model=model, contents=user_text, config=cfg)
            if resp.function_calls:
                call = resp.function_calls[0]
                fn = TOOL_MAP.get(call.name)
                if fn:
                    return str(fn(**(call.args or {})))
            return (resp.text or "Done.").strip().replace("*", "")
        except Exception as exc:
            if model == os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"):
                return f"Brain router error: {exc}"
    return "Command processing failed."
