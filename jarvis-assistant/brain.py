import datetime
import inspect
import json
import os
import re
import threading
import time
import types
import urllib.error
import urllib.request
from dotenv import load_dotenv

from lead.prompts import build_lead_prompt, detect_emotion_cue
from memory.embeddings import embed
from memory.retrieval import recall
from memory.store import (
    append_turn,
    compact,
    decay_facts,
    get_active_personality_directives,
    get_active_state,
    recent_turns,
    top_facts,
    update_active_state,
    upsert_fact,
)
from tools import TOOL_FUNCTIONS, TOOL_MAP
from tools.tasks import get_open_tasks_context

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)
load_dotenv()

_CLIENT = None
DEFAULT_SESSION = "default"
_LAST_DECAY_DATE = None
_CHAINABLE_TOOLS = {"dispatch_coding_agent", "list_agenda", "list_task_lists", "sync_coding_progress"}


def _get_client():
    global _CLIENT
    return _CLIENT


def _models() -> list[str]:
    return [
        os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
        os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3-flash-preview"),
        "gemini-3.1-flash-lite",
    ]


def _build_tool_declarations(tool_functions: list) -> list[dict]:
    declarations = []
    descriptions = {
        "sync_coding_progress": "Synchronize and report coding progress from git and tasks.",
        "list_agenda": "List open agenda tasks, blockers, and due items.",
        "add_task": "Add a task to the agenda or named list.",
        "update_task_progress": "Append a progress or blocker note to a task.",
        "complete_task": "Mark a task as completed.",
        "create_task_list": "Create a new task list.",
        "list_task_lists": "List all task lists.",
        "write_agent_plan": "Write implementation plan for agent steps.",
        "dispatch_coding_agent": "Dispatch an external coding agent to implement code.",
        "open_app": "Launch a desktop application.",
        "open_browser": "Open a URL in the browser.",
        "search_google": "Search Google in the browser.",
        "play_music": "Play music or song.",
        "play_youtube": "Play video or music on YouTube.",
        "play_spotify": "Play track or artist on Spotify.",
    }
    for fn in tool_functions:
        sig = inspect.signature(fn)
        properties = {}
        required = []
        for name, param in sig.parameters.items():
            properties[name] = {"type": "STRING"}
            if param.default == inspect.Parameter.empty:
                required.append(name)
        decl = {
            "name": fn.__name__,
            "description": descriptions.get(fn.__name__, f"Execute {fn.__name__}"),
            "parameters": {
                "type": "OBJECT",
                "properties": properties,
            },
        }
        if required:
            decl["parameters"]["required"] = required
        declarations.append(decl)
    return declarations


def _call_gemini_rest(contents: list, system_instruction: str = None, tools: list = None, model: str = None) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {"error": "Missing GEMINI_API_KEY"}
    active_model = model or os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{active_model}:generateContent?key={api_key}"
    payload = {"contents": contents, "generationConfig": {"temperature": 0.2}}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if tools:
        payload["tools"] = [{"functionDeclarations": _build_tool_declarations(tools)}]
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    timeout_sec = float(os.getenv("GEMINI_TIMEOUT_SEC", "3.5"))
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_system_prompt(session_id: str, user_text: str) -> str:
    state = get_active_state(session_id)
    directives = get_active_personality_directives()
    facts = top_facts("Fas", limit=6)
    snippets = recall(user_text, session_id=session_id, k=4)
    tasks_context = get_open_tasks_context()
    emotion = detect_emotion_cue(user_text, " ".join(snippets))
    return build_lead_prompt(state, directives, facts, snippets, tasks_context, current_emotion=emotion)


def _extract_state_update(session_id: str, user_text: str, reply: str) -> None:
    prompt = (
        "From this exchange, extract durable state. Respond ONLY as JSON with keys: "
        '"current_project" (string or null, only if clearly stated/changed), '
        '"last_topic" (short string or null), '
        '"new_fact" (object with subject, predicate, value — ONLY if Fas explicitly stated a lasting '
        "personal preference, opinion, or fact about himself. If nothing qualifies, use null).\n"
        f"User: {user_text}\nMike: {reply}"
    )
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    try:
        raw = _call_gemini_rest(contents)
        text = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        clean_json = text.strip()
        if clean_json.startswith("```"):
            clean_json = clean_json.split("\n", 1)[-1].rsplit("\n", 1)[0].strip()
        data = json.loads(clean_json or "{}")
    except Exception:
        return
    updates = {}
    if data.get("current_project"):
        updates["current_project"] = data["current_project"]
    if data.get("last_topic"):
        updates["last_topic"] = data["last_topic"]
    if updates:
        update_active_state(session_id, **updates)
    fact = data.get("new_fact")
    if isinstance(fact, dict) and fact.get("subject") and fact.get("predicate") and fact.get("value"):
        upsert_fact(fact["subject"], fact["predicate"], fact["value"])


def _try_fast_action(user_text: str) -> str | None:
    low = user_text.lower().strip()
    if any(k in low for k in ("open youtube", "turn on youtube", "launch youtube", "play youtube", "open a song on youtube")):
        from tools.media import open_browser
        open_browser("https://www.youtube.com")
        return "Opening YouTube for you now, Fas."
    if any(k in low for k in ("can you turn on youtube", "can you open youtube")):
        from tools.media import open_browser
        open_browser("https://www.youtube.com")
        return "Opening YouTube for you now, Fas."
    if "open a song" in low or "play a song" in low or "play music" in low or low.startswith("play "):
        from tools.media import play_music
        cleaned = re.sub(r"^(can you\s+)?(open\s+a\s+song(\s+for\s+me)?|play\s+a\s+song(\s+for\s+me)?|play\s+music|play)\s*", "", low).strip("?.! ")
        play_music(cleaned or "lofi beats")
        return f"Playing {cleaned or 'music'} for you now, Fas."
    if any(k in low for k in ("what is on my agenda", "what's on my agenda", "my agenda", "today's agenda", "list tasks", "what do i have today")):
        from tools.tasks import list_agenda
        return list_agenda(when="today")
    if low.startswith("add task ") or low.startswith("create task "):
        from tools.tasks import add_task
        title = re.sub(r"^(add task|create task)\s*", "", low).strip("?.! ")
        if title:
            return add_task(title)
    if low.startswith("search google for ") or low.startswith("google "):
        from tools.media import search_google
        query = re.sub(r"^(search google for |google )", "", low).strip("?.! ")
        if query:
            return search_google(query)
    if low.startswith("open browser") or low == "open the browser":
        from tools.media import open_browser
        open_browser("https://www.google.com")
        return "Opening the browser for you now, Fas."
    if low.startswith("open app ") or low.startswith("launch app "):
        from tools.apps import open_app
        app_name = re.sub(r"^(open app |launch app )", "", low).strip("?.! ")
        if app_name:
            return open_app(app_name)
    return None


def converse(session_id: str, user_text: str) -> str:
    fast_reply = _try_fast_action(user_text)
    if fast_reply:
        append_turn(session_id, "user", user_text, None)
        append_turn(session_id, "mike", fast_reply, None)
        _maybe_run_memory_upkeep(session_id)
        return fast_reply

    system_prompt = _build_system_prompt(session_id, user_text)
    history = recent_turns(session_id, n=int(os.getenv("SHORT_TERM_TURN_WINDOW", "6")))

    client = _get_client()
    if client is not None:
        mock_contents = [
            types.SimpleNamespace(role=("user" if h["role"] == "user" else "model"), parts=[types.SimpleNamespace(text=h["text"])])
            for h in history
        ]
        mock_contents.append(types.SimpleNamespace(role="user", parts=[types.SimpleNamespace(text=user_text)]))
        cfg = types.SimpleNamespace(system_instruction=system_prompt, tools=TOOL_FUNCTIONS)
        resp = client.models.generate_content(model=_models()[0], contents=mock_contents, config=cfg)
        reply = (getattr(resp, "text", "") or "Done.").strip().replace("*", "")
        append_turn(session_id, "user", user_text, None)
        append_turn(session_id, "mike", reply, None)
        return reply

    rest_contents = []
    for h in history:
        rest_contents.append({"role": ("user" if h["role"] == "user" else "model"), "parts": [{"text": h["text"]}]})
    rest_contents.append({"role": "user", "parts": [{"text": user_text}]})

    reply = "Command processing failed."
    steps_taken = 0
    chained = False
    max_steps = int(os.getenv("MAX_AGENTIC_STEPS", "3"))

    for _ in range(max_steps):
        resp_dict = None
        for model in _models():
            for attempt in range(2):
                try:
                    resp_dict = _call_gemini_rest(rest_contents, system_instruction=system_prompt, tools=TOOL_FUNCTIONS, model=model)
                    if resp_dict and "candidates" in resp_dict:
                        break
                except urllib.error.HTTPError as exc:
                    reply = f"Brain router error: {exc}"
                    if exc.code in (503, 429) and attempt == 0:
                        time.sleep(0.5)
                        continue
                    break
                except Exception as exc:
                    reply = f"Brain router error: {exc}"
                    break
            if resp_dict and "candidates" in resp_dict:
                break
        if not resp_dict or not resp_dict.get("candidates"):
            try:
                from local_brain import query_local_brain
                local_prompt = "You are Mike Ross, Fas's technical lead and confidant from Suits. Sharp, loyal, concise. Always address the user as Fas. Respond in 1-2 spoken sentences."
                local_reply = query_local_brain(local_prompt, user_text, history)
                if local_reply:
                    reply = local_reply
                    break
            except Exception:
                pass
            if "503" in reply or "Service Unavailable" in reply or "failed" in reply.lower():
                reply = "I'm right here with you, Fas. Cloud link hit a bump, but I've got your back. What's on your mind?"
            break
        candidate = resp_dict["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        func_parts = [p.get("functionCall") for p in parts if "functionCall" in p]
        if func_parts:
            fc = func_parts[0]
            call_name = fc.get("name")
            call_args = fc.get("args") or {}
            fn = TOOL_MAP.get(call_name)
            if fn:
                try:
                    result = str(fn(**call_args))
                except Exception as exc:
                    result = f"Tool execution error: {exc}"
            else:
                result = f"Unknown tool: {call_name}"
            reply = result
            steps_taken += 1
            if call_name in _CHAINABLE_TOOLS:
                chained = True
                rest_contents.append(content)
                rest_contents.append({
                    "role": "user",
                    "parts": [{"functionResponse": {"name": call_name, "response": {"result": result}}}],
                })
                continue
            break
        reply = "".join(text_parts).strip().replace("*", "")
        break

    is_simple_fast_path = steps_taken >= 1 and not chained
    if is_simple_fast_path:
        append_turn(session_id, "user", user_text, None)
        append_turn(session_id, "mike", reply, None)
    else:
        append_turn(session_id, "user", user_text, embed(user_text))
        append_turn(session_id, "mike", reply, embed(reply))
        threading.Thread(target=_extract_state_update, args=(session_id, user_text, reply), daemon=True).start()
    _maybe_run_memory_upkeep(session_id)
    return reply


def process_turn(user_input: str, session_id: str = "default") -> str:
    return converse(session_id, user_input)


def route_command(user_text: str) -> str:
    return converse(DEFAULT_SESSION, user_text)


def _maybe_run_memory_upkeep(session_id: str) -> None:
    global _LAST_DECAY_DATE
    compact(session_id, keep_last=int(os.getenv("SHORT_TERM_TURN_WINDOW", "6")) * 3)
    today = datetime.date.today()
    if _LAST_DECAY_DATE != today:
        decay_facts()
        _LAST_DECAY_DATE = today
