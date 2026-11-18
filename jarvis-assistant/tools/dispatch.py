import glob
import json
import os
import subprocess
from lead.prompts import build_dispatch_directive, map_task_to_skills
from memory.store import log_workflow

_AGENT_MAP = {"ml-engineer": "ml-engineer", "architect": "Plan", "claude": "", "gemini": "gemini", "antigravity": "antigravity", "auto": "", "": ""}
_CLI_PATH = None


def _find_claude_cli() -> str:
    global _CLI_PATH
    if _CLI_PATH:
        return _CLI_PATH
    configured = os.getenv("CLAUDE_CLI_PATH", "").strip()
    if configured and os.path.exists(configured):
        _CLI_PATH = configured
        return _CLI_PATH
    pattern = os.path.expandvars(r"%USERPROFILE%\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe")
    matches = sorted(glob.glob(pattern), reverse=True)
    if matches:
        _CLI_PATH = matches[0]
        return _CLI_PATH
    raise FileNotFoundError("claude.exe not found; set CLAUDE_CLI_PATH in .env")


def _dispatch_gemini_agent(prompt: str, target: str, timeout: int) -> tuple[str, str, float]:
    cli = os.getenv("GEMINI_CLI_PATH", "").strip() or os.getenv("ANTIGRAVITY_CLI_PATH", "").strip()
    if cli and os.path.exists(cli):
        proc = subprocess.run([cli, "-p", prompt], cwd=target, capture_output=True, text=True, timeout=timeout, errors="ignore")
        return proc.stdout.strip() or proc.stderr[:500], ("success" if proc.returncode == 0 else "error"), 0.0
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key:
        import urllib.request
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return text.strip() or "Antigravity subagent completed with no output.", "success", 0.0
    return "Gemini/Antigravity backend not configured (missing GEMINI_API_KEY or CLI).", "error", 0.0


def dispatch_coding_agent(task: str, agent: str = "auto", repo_path: str = ".", skills: list[str] = None) -> str:
    requested = agent.strip().lower()
    cli_agent = _AGENT_MAP.get(requested, "")
    target = repo_path.strip() or os.getenv("DEFAULT_REPO_PATH", os.getcwd())
    if skills is None:
        skills = map_task_to_skills(task)
    directive = build_dispatch_directive(skills)
    enriched_task = f"{directive}\n\nTask: {task}"
    label = requested or "general"
    timeout = int(os.getenv("AGENT_DISPATCH_TIMEOUT_SEC", "180"))

    if requested in ("gemini", "antigravity"):
        try:
            result_text, status, cost = _dispatch_gemini_agent(enriched_task, target, timeout)
        except Exception as exc:
            log_workflow(target, task, label, "error", str(exc))
            return f"Dispatch failed: {exc}"
        log_workflow(target, task, label, status, f"(${cost:.3f}) {result_text}")
        if status == "error":
            return f"The {label} agent hit an error: {result_text[:300]}"
        return result_text[:400] if result_text else f"{label.capitalize()} agent finished with no output."

    claude_cli = None
    try:
        claude_cli = _find_claude_cli()
    except FileNotFoundError as exc:
        if requested in ("auto", ""):
            try:
                result_text, status, cost = _dispatch_gemini_agent(enriched_task, target, timeout)
            except Exception as inner_exc:
                log_workflow(target, task, label, "error", str(inner_exc))
                return f"Dispatch failed: {inner_exc}"
            log_workflow(target, task, label, status, f"(${cost:.3f}) {result_text}")
            if status == "error":
                return f"The {label} agent hit an error: {result_text[:300]}"
            return result_text[:400] if result_text else f"{label.capitalize()} agent finished with no output."
        return str(exc)

    cmd = [
        claude_cli, "-p", enriched_task,
        "--output-format", "json",
        "--permission-mode", os.getenv("AGENT_DISPATCH_PERMISSION_MODE", "acceptEdits"),
        "--max-budget-usd", os.getenv("AGENT_DISPATCH_MAX_BUDGET_USD", "1.00"),
    ]
    if cli_agent:
        cmd += ["--agent", cli_agent]

    try:
        proc = subprocess.run(cmd, cwd=target, capture_output=True, text=True, timeout=timeout, errors="ignore")
        data = json.loads(proc.stdout or "{}")
    except subprocess.TimeoutExpired:
        log_workflow(target, task, label, "timeout", f"Exceeded {timeout}s")
        return f"Dispatch to {label} agent timed out after {timeout}s."
    except Exception as exc:
        log_workflow(target, task, label, "error", str(exc))
        return f"Dispatch failed: {exc}"

    result_text = data.get("result", "") or proc.stderr[:500]
    status = "error" if data.get("is_error") else "success"
    cost = data.get("total_cost_usd", 0.0)
    log_workflow(target, task, label, status, f"(${cost:.3f}) {result_text}")
    if status == "error":
        return f"The {label} agent hit an error: {result_text[:300]}"
    return result_text[:400] if result_text else f"{label.capitalize()} agent finished with no output."
