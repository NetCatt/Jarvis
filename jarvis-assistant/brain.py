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
_CHAINABLE_TOOLS = {"dispatch_coding_agent", "list_agenda", "list_task_lists", "sync_coding_progress", "os_context", "run_terminal"}


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
        "open_folder": "Open a folder or directory in Windows Explorer (e.g. models, downloads, desktop, code, or path).",
        "search_files": "Search for files by name or keyword across workspace or directories.",
        "open_browser": "Open a URL in the browser.",
        "search_google": "Search Google in the browser.",
        "play_music": "Play song verbatim (keep words like 'Again' in track titles, e.g. 'Goodbye To A Lover Again').",
        "play_youtube": "Play track/video on YouTube verbatim (keep words like 'Again' in title).",
        "play_spotify": "Play track verbatim on Spotify (keep words like 'Again' in title).",
        "pause_music": "Pause, resume, or toggle music or media playback.",
        "next_track": "Skip to the next music or media track.",
        "prev_track": "Skip to the previous music or media track.",
        "run_terminal": "Execute Windows PowerShell terminal command with safety bounds.",
        "get_volume": "Get current master audio volume percentage.",
        "set_volume": "Set master audio volume level percentage (0 to 100).",
        "change_volume": "Adjust system audio volume by delta (e.g. +10 or -10 percent).",
        "os_input": "Send hardware media keys, window hotkeys, or type unicode text into the active window.",
        "os_launch": "Launch application, URI protocol, or system target.",
        "web_dispatch": "Dispatch search query or URL to browser across search engines.",
        "os_context": "Inspect system context including active window title, clipboard content, or RAM stats.",
        "set_timer": "Set a countdown timer in seconds or natural duration like '5 minutes' with an optional label.",
        "list_timers": "List currently running countdown timers and remaining seconds.",
        "cancel_timer": "Cancel an active timer by label or cancel all timers.",
        "quick_answer": "Get an immediate spoken answer for math calculations, current time/date, live weather, or factual web lookups.",
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


_ORIG_CALL_GEMINI_REST = _call_gemini_rest


def _build_openai_tools(tool_functions: list) -> list[dict]:
    decls = _build_tool_declarations(tool_functions)
    out = []
    for d in decls:
        params = dict(d.get("parameters") or {})
        props = {k: {"type": v.get("type", "STRING").lower()} for k, v in (params.get("properties") or {}).items()}
        schema = {"type": "object", "properties": props}
        if params.get("required"):
            schema["required"] = params["required"]
        out.append({
            "type": "function",
            "function": {"name": d["name"], "description": d["description"][:96], "parameters": schema},
        })
    return out


def _call_groq_chat(messages: list, tools: list = None, model: str = None, max_tokens: int = 1024) -> dict | None:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    active_model = model or os.getenv("GROQ_BRAIN_MODEL", "qwen/qwen3.8-27b")
    payload = {
        "model": active_model,
        "messages": messages,
        "temperature": 0.25,
        "max_tokens": max_tokens,
    }
    effort = os.getenv("GROQ_REASONING_EFFORT", "high").strip().lower()
    if effort and ("qwen3" in active_model or "gpt-oss" in active_model):
        payload["reasoning_effort"] = effort
    if tools:
        payload["tools"] = _build_openai_tools(tools)
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Jarvis/1.0",
        },
    )
    timeout_sec = float(os.getenv("GROQ_BRAIN_TIMEOUT_SEC", "6.0"))
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


_ORIG_CALL_GROQ_CHAT = _call_groq_chat


def _groq_converse_loop(system_prompt: str, history: list, user_text: str, max_steps: int) -> tuple[str | None, int, bool]:
    msgs = [{"role": "system", "content": system_prompt}]
    for h in history:
        msgs.append({"role": ("user" if h["role"] == "user" else "assistant"), "content": h["text"]})
    msgs.append({"role": "user", "content": user_text})
    models = [
        os.getenv("GROQ_BRAIN_MODEL", "qwen/qwen3.8-27b"),
        os.getenv("GROQ_BRAIN_FALLBACK", "openai/gpt-oss-20b"),
    ]
    steps_taken = 0
    chained = False
    last_reply = None
    for _ in range(max_steps):
        resp = None
        for m in models:
            try:
                resp = _call_groq_chat(msgs, tools=TOOL_FUNCTIONS, model=m)
                if resp and resp.get("choices"):
                    break
            except Exception:
                continue
        if not resp or not resp.get("choices"):
            return None, steps_taken, chained
        msg = resp["choices"][0].get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            tc = tool_calls[0]
            fn_info = tc.get("function") or {}
            call_name = fn_info.get("name", "")
            raw_args = fn_info.get("arguments") or "{}"
            try:
                call_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception:
                call_args = {}
            fn = TOOL_MAP.get(call_name)
            if fn:
                try:
                    result = str(fn(**call_args))
                except Exception as exc:
                    result = f"Tool execution error: {exc}"
            else:
                result = f"Unknown tool: {call_name}"
            last_reply = result
            steps_taken += 1
            if call_name in _CHAINABLE_TOOLS:
                chained = True
                msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": [tc]})
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", "call_0"), "content": result})
                continue
            return result, steps_taken, chained
        raw_content = re.sub(r"<think>.*?(?:</think>|$)", "", msg.get("content") or "", flags=re.DOTALL)
        if raw_content.strip():
            return _sanitize_spoken_reply(raw_content), steps_taken, chained
        return last_reply, steps_taken, chained
    return last_reply, steps_taken, chained


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
    text = ""
    try:
        if _call_gemini_rest == _ORIG_CALL_GEMINI_REST and os.getenv("GROQ_API_KEY", "").strip():
            raw_g = _call_groq_chat([{"role": "user", "content": prompt}], max_tokens=160)
            text = (raw_g or {}).get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        if not text:
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
    timer_m = re.search(r"(?:set|start)\s+(?:a\s+)?(?:timer|alarm)\s+(?:for\s+)?(.+?)(?:\s+(?:called|named|for)\s+([a-zA-Z0-9 ]+))?$", low)
    if timer_m and re.search(r"\d+\s*(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)", timer_m.group(1)):
        from tools.daily import set_timer
        return set_timer(timer_m.group(1).strip(" .!?"), label=(timer_m.group(2) or "").strip(" .!?"))
    if any(k in low for k in ("cancel timer", "stop timer", "clear timers", "cancel all timers")):
        from tools.daily import cancel_timer
        return cancel_timer()
    if any(k in low for k in ("list timers", "active timers", "how much time left")):
        from tools.daily import list_timers
        return list_timers()
    vol_match = re.search(r"(?:turn\s+(?:up\s+|down\s+)?|set\s+|put\s+)?(?:the\s+)?volume\s+(?:to\s+|up\s+to\s+|at\s+)?(\d{1,3})\s*(?:%|percent)?", low)
    if vol_match and any(k in low for k in ("volume", "vol")):
        from tools.media import set_volume
        lvl = int(vol_match.group(1))
        return set_volume(lvl)
    if any(k in low for k in ("volume up", "turn up the volume", "turn up volume", "crank up the volume", "increase volume", "louder")):
        from tools.media import change_volume
        return change_volume(10)
    if any(k in low for k in ("volume down", "turn down the volume", "turn down volume", "decrease volume", "lower the volume", "softer", "quieter")):
        from tools.media import change_volume
        return change_volume(-10)
    if any(k in low for k in ("what is the volume", "what's the volume", "current volume", "check volume", "check the volume")):
        from tools.media import get_volume
        return get_volume()
    if low.startswith("open folder ") or low.startswith("open directory ") or low.startswith("open the folder "):
        from tools.apps import open_folder
        target = re.sub(r"^(open folder|open directory|open the folder)\s*", "", low).strip("?.! ")
        return open_folder(target)
    if low.startswith("search files for ") or low.startswith("find files with ") or low.startswith("search files "):
        from tools.apps import search_files
        query = re.sub(r"^(search files for|find files with|search files)\s*", "", low).strip("?.! ")
        return search_files(query)
    if any(k in low for k in ("open youtube", "turn on youtube", "launch youtube", "can you turn on youtube", "can you open youtube")) and len(low.split()) <= 5:
        from tools.media import open_browser
        open_browser("https://www.youtube.com")
        return "Opening YouTube for you now, Fas."
    if any(k in low for k in (
        "which song", "what song", "what's playing", "what is playing",
        "what am i listening", "what was i playing", "song is playing",
        "song i was playing", "song is going on", "look at my spotify",
        "check spotify", "now playing"
    )):
        from tools.os_context import os_context
        return os_context("now_playing")
    if any(k in low for k in (
        "didn't start playing", "didnt start playing",
        "pause music", "pause the music", "stop the music", "stop music",
        "resume music", "resume the music", "toggle music", "pause playback",
        "pause my music", "stop playback"
    )) or low.rstrip(".!? ") in ("not playing", "start playing"):
        from tools.media import pause_music
        return pause_music()
    if "open a song" in low or "play a song" in low or "play music" in low or low.startswith(("play ", "can you play ", "could you play ", "please play ", "start playing ")):
        from tools.media import play_music
        cleaned = re.sub(r"^(?:can you\s+|could you\s+|please\s+)?(?:open\s+a\s+song(?:\s+for\s+me)?(?:\s+on\s+(?:spotify|youtube))?|play\s+a\s+song(?:\s+for\s+me)?|play\s+music|start\s+playing|play)\s*", "", low).strip("?.! ")
        if "youtube" in low and "youtube" not in cleaned:
            return play_music(cleaned or "lofi beats", platform="youtube")
        if "spotify" in low and "spotify" not in cleaned:
            return play_music(cleaned or "lofi beats", platform="spotify")
        return play_music(cleaned or "lofi beats")
    if any(k in low for k in ("next track", "next song", "skip song", "skip track", "skip this song")):
        from tools.media import next_track
        return next_track()
    if any(k in low for k in ("previous track", "previous song", "prev track", "last track")):
        from tools.media import prev_track
        return prev_track()
    if any(k in low for k in ("what is on my agenda", "what's on my agenda", "my agenda", "today's agenda", "list tasks", "what do i have today")):
        from tools.tasks import list_agenda
        return list_agenda(when="today")
    if any(k in low for k in ("what did we complete", "tasks completed", "which tasks that we complete", "which tasks did we complete", "completed tasks")):
        from tools.tasks import list_agenda
        return list_agenda(when="completed")
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


def _is_system_intent(text: str) -> bool:
    low = text.lower()
    system_keywords = (
        "volume", "sound", "louder", "quieter", "softer", "mute",
        "open folder", "directory", "folder",
        "search file", "find file", "look for file", "search for file",
        "open app", "launch app", "open application",
        "browser", "youtube", "spotify", "play music", "play song",
        "pause", "resume", "stop music", "next track", "prev track", "skip track", "skip song",
        "terminal", "powershell", "run command", "command", "process", "disk space", "kill",
        "open vscode", "open terminal", "open chrome",
        "close tab", "close window", "active window", "clipboard", "system stats", "keys", "hotkey"
    )
    return any(k in low for k in system_keywords)


def _sanitize_spoken_reply(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return "Done."
    filtered = []
    stage_regex = re.compile(
        r"^(?:mike\s+(?:is|calls|says|thinks|refers|notes|replies|agrees|laughs)|"
        r"mike's\s+tone|the\s+system\s+is|fas\s+(?:is|requests|asks|mentions)).*",
        re.IGNORECASE
    )
    for line in lines:
        cleaned = re.sub(r"\(.*?\)", "", line).strip()
        if not cleaned:
            continue
        low = cleaned.lower()
        if stage_regex.match(low):
            continue
        if any(low.startswith(p) for p in (
            "mike refers to",
            "the user and mike",
            "accountability is",
            "known about",
            "relevant past context",
            "current working state",
            "evolving personality",
            "open project tasks",
            "notes:",
            "[project lead directive]",
            "spoken output directive",
        )):
            continue
        filtered.append(cleaned)
    text = " ".join(filtered).strip().replace("*", "")
    return text or "Done."


def converse(session_id: str, user_text: str) -> str:
    from tools.safety_gate import handle_pending_confirmation
    handled, pending_reply = handle_pending_confirmation(user_text)
    if handled and pending_reply:
        append_turn(session_id, "user", user_text, None)
        append_turn(session_id, "mike", pending_reply, None)
        return pending_reply

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
        reply = _sanitize_spoken_reply(reply)
        append_turn(session_id, "user", user_text, None)
        append_turn(session_id, "mike", reply, None)
        return reply

    mode = os.getenv("ROUTING_MODE", os.getenv("LOCAL_BRAIN_FIRST", "groq_hybrid")).lower()
    if mode in ("groq", "groq_hybrid", "hybrid", "auto") and os.getenv("GROQ_API_KEY", "").strip() and (_call_gemini_rest == _ORIG_CALL_GEMINI_REST or _call_groq_chat != _ORIG_CALL_GROQ_CHAT):
        groq_reply, groq_steps, groq_chained = _groq_converse_loop(
            system_prompt, history, user_text, int(os.getenv("MAX_AGENTIC_STEPS", "3"))
        )
        if groq_reply:
            if groq_steps >= 1 and not groq_chained:
                append_turn(session_id, "user", user_text, None)
                append_turn(session_id, "mike", groq_reply, None)
            else:
                append_turn(session_id, "user", user_text, embed(user_text))
                append_turn(session_id, "mike", groq_reply, embed(groq_reply))
                threading.Thread(target=_extract_state_update, args=(session_id, user_text, groq_reply), daemon=True).start()
            _maybe_run_memory_upkeep(session_id)
            return groq_reply

    local_target = (mode in ("true", "1", "local")) or (mode in ("hybrid", "auto") and _is_system_intent(user_text))
    if local_target and _call_gemini_rest == _ORIG_CALL_GEMINI_REST:
        try:
            from local_brain import execute_local_turn
            local_reply = execute_local_turn(user_text, history)
            if local_reply:
                reply = _sanitize_spoken_reply(local_reply)
                append_turn(session_id, "user", user_text, embed(user_text))
                append_turn(session_id, "mike", reply, embed(reply))
                threading.Thread(target=_extract_state_update, args=(session_id, user_text, reply), daemon=True).start()
                _maybe_run_memory_upkeep(session_id)
                return reply
        except Exception:
            pass

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
                from local_brain import execute_local_turn
                local_reply = execute_local_turn(user_text, history)
                if local_reply:
                    reply = _sanitize_spoken_reply(local_reply)
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
        reply = _sanitize_spoken_reply("".join(text_parts))
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
