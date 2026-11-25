import atexit
import json
import os
import re
import subprocess
import time
import urllib.request

_SERVER_PROC = None

LOCAL_SYSTEM_PROMPT = (
    "You are Mike Ross from Suits: Fas's personal confidant, closest brother-in-arms, and elite technical lead. "
    "You possess photographic memory, street smarts, razor-sharp wit, and fierce loyalty to Fas. "
    "Always address the user as Fas. Speak naturally, authentically, and confidently in 1-2 spoken sentences.\n"
    "CRITICAL VOICE DIRECTIVES:\n"
    "- Respond directly and concisely in spoken English without thinking tags (<think>), inner reasoning, stage directions, or character names.\n"
    "- Speak directly to Fas in the first person ('I', 'we').\n"
    "- Banter warmly when Fas is chatting; stay crisp, razor-sharp, and proactive when executing tasks.\n"
    "- If Fas asks to perform system actions, you MUST emit a tool call on its own line:\n"
    "TOOL_CALL: tool_name({\"param\": \"value\"})\n"
    "Universal OS primitives:\n"
    "- os_input({\"keys\": [\"playpause\"]}) or os_input({\"keys\": [\"ctrl\", \"w\"], \"hotkey\": true}) or os_input({\"text\": str})\n"
    "- os_launch({\"target\": str})  (e.g. 'spotify:', 'ms-settings:', 'notepad', app path)\n"
    "- web_dispatch({\"query\": str, \"engine\": 'google'|'youtube'|'spotify'|'github', \"url\": str})\n"
    "- os_context({\"query_type\": 'now_playing'|'active_window'|'clipboard'|'system_stats'})\n"
    "Core tools:\n"
    "- set_volume({\"level\": int}), change_volume({\"delta\": int}), get_volume({})\n"
    "- open_folder({\"target\": str}), search_files({\"query\": str})\n"
    "- run_terminal({\"command\": str})\n"
    "- list_agenda({\"when\": 'today'|'all'|'completed'}), add_task({\"title\": str})\n"
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
    default_model = os.path.join(base_dir, "models", "Qwen_Qwen3-1.7B-Q4_K_M.gguf")
    model_path = os.getenv("LOCAL_BRAIN_MODEL_PATH", default_model)
    if not os.path.exists(model_path):
        return False
    runner_path = os.path.join(base_dir, "tools", "bin", "llama-server.exe")
    if not os.path.exists(runner_path):
        return False
    port = get_server_port()
    cmd = [
        runner_path,
        "-m", model_path,
        "-c", "1024",
        "-b", "512",
        "-ub", "256",
        "-t", "2",
        "-fa", "on",
        "--parallel", "1",
        "--reasoning", "off",
        "--reasoning-budget", "0",
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
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data["choices"][0]["message"]["content"]
            cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
            return cleaned.strip().replace("*", "")
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
            from tools.safety_gate import evaluate_tool_safety
            status, safety_msg = evaluate_tool_safety(call_name, args)
            if status == "BLOCKED":
                return safety_msg, f"I can't do that, Fas. {safety_msg}"
            if status == "CONFIRM":
                return safety_msg, safety_msg
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
                clean_arg = raw_args.strip("'\"")
                param_name = "command" if call_name == "run_terminal" else "target"
                args = {param_name: clean_arg}
    from tools.safety_gate import evaluate_tool_safety
    status, safety_msg = evaluate_tool_safety(call_name, args)
    if status == "BLOCKED":
        return safety_msg, f"I can't do that, Fas. {safety_msg}"
    if status == "CONFIRM":
        return safety_msg, safety_msg
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
    from tools.safety_gate import handle_pending_confirmation
    handled, reply = handle_pending_confirmation(user_text)
    if handled and reply:
        return reply
    prompt = f"{system_prompt}\n\n{LOCAL_SYSTEM_PROMPT}" if system_prompt else LOCAL_SYSTEM_PROMPT
    try:
        from memory.retrieval import recall
        from memory.store import top_facts
        fact_rows = top_facts("Fas", limit=5)
        facts_str = "; ".join(f"{r['predicate']}={r['value']}" for r in fact_rows if "predicate" in r and "value" in r)
        snippets = recall(user_text, k=3)
        mem_parts = []
        if facts_str:
            mem_parts.append(f"Known facts: {facts_str}")
        if snippets:
            mem_parts.extend(f"- {s}" for s in snippets if s)
        if mem_parts:
            prompt = f"{prompt}\n\nRECALLED MEMORY OF FAS:\n" + "\n".join(mem_parts)
    except Exception:
        pass
    raw = query_local_brain(prompt, user_text, history)
    if not raw:
        return None
    tool_res, spoken = parse_and_execute_local_action(raw)
    if tool_res and (not spoken or len(spoken.strip()) <= 3 or any(p in spoken.lower() for p in ("let me check", "pull that", "checking", "one sec", "hang on"))):
        return tool_res.strip()
    if spoken and len(spoken.strip()) > 3:
        return spoken.strip()
    if tool_res:
        return tool_res.strip()
    return raw.strip()
