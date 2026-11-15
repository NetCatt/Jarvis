import glob
import json
import os
import subprocess

from memory.store import log_workflow

# Fas-facing name -> actual Claude Code CLI --agent value. "architect" has no literal agent
# in this account's setup; the closest fit is "Plan" (software architect / implementation planning).
_AGENT_MAP = {"ml-engineer": "ml-engineer", "architect": "Plan", "": ""}
_CLI_PATH = None


def _find_claude_cli() -> str:
    """Locate the claude.exe bundled with the VS Code extension (not on PATH by default)."""
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


def dispatch_coding_agent(task: str, agent: str = "", repo_path: str = "") -> str:
    """Dispatch a real engineering/architecture task to the Claude Code CLI headlessly.

    agent: 'ml-engineer' for data/model/training work, 'architect' for design/structure/planning
    work (maps to the CLI's 'Plan' agent — there is no literal 'architect' agent), or empty for
    general coding. Falls back to general if an unrecognized agent is given. Costs real API
    dollars per call (unlike Mike's own Gemini-based routing) — bounded by
    AGENT_DISPATCH_MAX_BUDGET_USD and AGENT_DISPATCH_TIMEOUT_SEC.
    """
    requested = agent.strip().lower()
    cli_agent = _AGENT_MAP.get(requested, "")
    target = repo_path.strip() or os.getenv("DEFAULT_REPO_PATH", os.getcwd())
    try:
        cli = _find_claude_cli()
    except FileNotFoundError as exc:
        return str(exc)

    cmd = [
        cli, "-p", task,
        "--output-format", "json",
        "--permission-mode", os.getenv("AGENT_DISPATCH_PERMISSION_MODE", "acceptEdits"),
        "--max-budget-usd", os.getenv("AGENT_DISPATCH_MAX_BUDGET_USD", "1.00"),
    ]
    if cli_agent:
        cmd += ["--agent", cli_agent]

    label = requested or "general"
    timeout = int(os.getenv("AGENT_DISPATCH_TIMEOUT_SEC", "180"))
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
