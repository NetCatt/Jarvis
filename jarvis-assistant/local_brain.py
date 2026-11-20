import atexit
import json
import os
import re
import subprocess
import time
import urllib.request

_SERVER_PROC = None

LOCAL_SYSTEM_PROMPT = (
    "You are Mike Ross, Fas's technical lead, confidant, and desktop orchestrator from Suits. "
    "Sharp, loyal, concise. Always address the user as Fas. Speak concisely in 1-2 spoken sentences.\n"
    "CRITICAL VOICE DIRECTIVES:\n"
    "- You are speaking live through text-to-speech. Speak directly to Fas in the first person ('I', 'we').\n"
    "- NEVER write third-person screenplay descriptions, stage directions, or character names (e.g., 'Mike is...', 'Mike calls Fas...', 'Mike's tone changes...').\n"
    "When Fas asks to perform system actions, you MUST emit a tool call on its own line:\n"
    "TOOL_CALL: tool_name({\"param\": \"value\"})\n"
    "Available tools:\n"
    "- set_volume({\"level\": int})  (0 to 100)\n"
    "- change_volume({\"delta\": int})  (+10 or -10)\n"
    "- get_volume({})\n"
    "- open_folder({\"target\": str})  ('downloads', 'models', 'desktop', 'code', or path)\n"
    "- search_files({\"query\": str})\n"
    "- open_app({\"app_name\": str})\n"
    "- open_browser({\"url\": str})\n"
    "- search_google({\"query\": str})\n"
    "- play_music({\"song\": str, \"platform\": str})\n"
    "- list_agenda({\"when\": 'today'|'all'|'completed'})\n"
    "- add_task({\"title\": str})\n"
    "After emitting TOOL_CALL if needed, respond naturally to Fas. If no tool is needed, converse normally."
)


def get_server_port() -> int:
    return int(os.getenv("LOCAL_BRAIN_PORT", "8088"))


def is_server_running() -> bool:
    port = get_server_port()
    try:
        url = f"http://127.0.0.1:{port}/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_local_server() -> bool:
    global _SERVER_PROC
    if is_server_running():
        return True
    base_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.getenv(
        "LOCAL_BRAIN_MODEL_PATH",
        os.path.join(base_dir, "models", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
    )
    if not os.path.exists(model_path):
        return False
    runner_path = os.path.join(base_dir, "tools", "bin", "llama-server.exe")
    if not os.path.exists(runner_path):
        return False
    port = get_server_port()
    cmd = [
        runner_path,
        "-m", model_path,
        "-c", "2048",
        "-t", "2",
        "--port", str(port),
        "--host", "127.0.0.1",
    ]
    try:
        _SERVER_PROC = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if is_server_running():
                return True
            time.sleep(0.3)
    except Exception:
        return False
    return is_server_running()


def stop_local_server() -> None:
    global _SERVER_PROC
    if _SERVER_PROC:
        try:
            _SERVER_PROC.terminate()
            _SERVER_PROC.wait(timeout=1.0)
        except Exception:
            try:
                _SERVER_PROC.kill()
            except Exception:
                pass
        _SERVER_PROC = None


atexit.register(stop_local_server)


def query_local_brain(system_prompt: str, user_text: str, history: list = None) -> str | None:
    port = get_server_port()
    if not is_server_running():
        if not start_local_server():
            return None
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        for h in history:
            role = "user" if h.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": h.get("text", "")})
    messages.append({"role": "user", "content": user_text})
    payload = json.dumps({
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 150,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip().replace("*", "")
    except Exception:
        return None


def parse_and_execute_local_action(text: str) -> tuple[str | None, str]:
    action_match = re.search(r"(?:ACTION|TOOL_CALL|TOOL):\s*([a-zA-Z0-9_]+)\s*\((.*?)\)", text, re.DOTALL)
    if not action_match:
        json_match = re.search(r"\{\s*\"(?:action|tool)\"\s*:\s*\"([a-zA-Z0-9_]+)\"\s*,\s*\"(?:args|parameters)\"\s*:\s*(\{.*?\})\s*\}", text, re.DOTALL)
        if json_match:
            call_name = json_match.group(1)
            raw_args = json_match.group(2)
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {}
            from tools import TOOL_MAP
            fn = TOOL_MAP.get(call_name)
            tool_res = str(fn(**args)) if fn else None
            spoken = text[:json_match.start()] + text[json_match.end():]
            spoken = re.sub(r"^\s*Spoken:\s*", "", spoken.strip(), flags=re.IGNORECASE)
            return tool_res, spoken or (tool_res or "")
        return None, text

    call_name = action_match.group(1)
    raw_args = action_match.group(2).strip()
    args = {}
    if raw_args:
        try:
            args = json.loads(raw_args)
        except Exception:
            for kv in re.finditer(r"([a-zA-Z0-9_]+)\s*=\s*['\"]?(.*?)['\"]?(?:,|$)", raw_args):
                args[kv.group(1)] = kv.group(2).strip("'\"")
            if not args and "=" not in raw_args and raw_args.strip("'\""):
                args = {"target": raw_args.strip("'\"")}
    from tools import TOOL_MAP
    fn = TOOL_MAP.get(call_name)
    tool_res = None
    if fn:
        try:
            tool_res = str(fn(**args))
        except Exception as exc:
            tool_res = f"Action error: {exc}"
    spoken = text[:action_match.start()] + text[action_match.end():]
    spoken = re.sub(r"^\s*Spoken:\s*", "", spoken.strip(), flags=re.IGNORECASE)
    return tool_res, spoken or (tool_res or "")


def execute_local_turn(user_text: str, history: list = None, system_prompt: str = None) -> str | None:
    prompt = system_prompt if system_prompt else LOCAL_SYSTEM_PROMPT
    raw = query_local_brain(prompt, user_text, history)
    if not raw:
        return None
    tool_res, spoken = parse_and_execute_local_action(raw)
    if spoken and len(spoken.strip()) > 3:
        return spoken.strip()
    if tool_res:
        return tool_res.strip()
    return raw.strip()
