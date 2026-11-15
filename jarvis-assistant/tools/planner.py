import os
import subprocess
from dotenv import load_dotenv
from google import genai

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(env_path)
load_dotenv()


def get_repo_files(repo_path: str, cap: int = 150) -> list[str]:
    """Fast bounded list of repository tracked files."""
    try:
        out = subprocess.check_output(["git", "-C", repo_path, "ls-files"], stderr=subprocess.DEVNULL, timeout=3.0, text=True, errors="ignore")
        return [f for f in out.splitlines() if f.strip()][:cap]
    except Exception:
        return []


def write_agent_plan(task_query: str, repo_path: str = "") -> str:
    """Generate NEXT_PLAN.md for coding agents via Gemini 3.8 Flash."""
    target = repo_path.strip() or os.getenv("DEFAULT_REPO_PATH", os.getcwd())
    files = get_repo_files(target)
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        f"You are a Lead ML Architect. Write a compact, step-by-step NEXT_PLAN.md for a coding agent.\n"
        f"Goal: {task_query}\nRepo Files: {files}\n"
        f"Format: Strict Markdown. List files to edit, exact function specs, and test command."
    )
    resp = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), contents=prompt)
    plan_text = (resp.text or "").strip()
    if plan_text and os.path.isdir(target):
        with open(os.path.join(target, "NEXT_PLAN.md"), "w", encoding="utf-8") as f:
            f.write(plan_text + "\n")
        return f"Generated NEXT_PLAN.md in {os.path.basename(target)} for '{task_query}'."
    return "Failed to generate agent plan."
