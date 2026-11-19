import atexit
import json
import os
import subprocess
import time
import urllib.request

_SERVER_PROC = None


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
