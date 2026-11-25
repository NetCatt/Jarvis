import datetime
import json
import os
import subprocess
from dotenv import load_dotenv
from tools.llm import generate
from tools.notify import send_summary
from tools.tasks import (
    _default_list_name,
    _has_oauth,
    _read_local_tasks,
    _write_local_tasks,
    add_task,
    get_open_tasks_raw,
    get_service_and_list_id,
)

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(env_path)
load_dotenv()

def _run_git(path: str, args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", "-C", path] + args, stderr=subprocess.DEVNULL, timeout=3.0, text=True, errors="ignore").strip()[:1500]
    except Exception:
        return ""

def get_repo_snapshot(repo_path: str) -> dict:
    status, commits = _run_git(repo_path, ["status", "-s"]), _run_git(repo_path, ["log", "-n", "3", "--oneline"])
    diff = _run_git(repo_path, ["diff", "--stat", "HEAD~1"])
    plan = ""
    for f in ("NEXT_PLAN.md", "PLAN.md", "TODO.md"):
        p = os.path.join(repo_path, f)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                plan = fp.read(1200)
            break
    return {"status": status, "commits": commits, "diff": diff, "plan": plan}

def _ask_gemini_reconcile(snap: dict, tasks: list[dict], agent_note: str) -> dict:
    prompt = (
        f"Reconcile code with Google Tasks.\nAgent Note: {agent_note or 'Inspect Git'}\n"
        f"Snapshot: {json.dumps(snap)}\nTasks: {json.dumps(tasks)}\n"
        f"JSON output keys: completed_task_ids (list[str]), progress_updates (list[{{task_id, note}}]), "
        f"new_tasks (list[{{title, notes}}]), next_plan_md (str), spoken_summary (str).\n"
        f"CRITICAL: every title and note must be a short, meaningful, human-readable description of what was "
        f"actually done or fixed in plain English (e.g. 'Fixed STT mis-transcribing English as Hindi'). "
        f"NEVER use a commit hash, numeric ID, or generic placeholder like 'commit73245' as a title — if the "
        f"git log/diff alone doesn't give enough signal to describe the change meaningfully, summarize the "
        f"Agent Note instead, or write a one-line description of the diff's actual purpose."
    )
    try:
        resp = generate(prompt, temperature=0.0, json_mode=True)
        parsed = json.loads(resp.text or "{}")
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    comp = [t["id"] for t in tasks if any(w in t["title"].lower() for w in agent_note.lower().split() if len(w) > 3)]
    return {"completed_task_ids": comp, "progress_updates": [], "new_tasks": [], "next_plan_md": "", "spoken_summary": "Reconciled tasks locally."}

def _apply_reconciliation(dec: dict, tasks: list[dict], target: str) -> tuple[list[str], list[str], list[str], list[str], str]:
    t_map = {t["id"]: t for t in tasks}
    done, upd, added = [], [], []
    has_oa = _has_oauth()
    svc, lid = (get_service_and_list_id() if has_oa else (None, None))
    all_t = ([] if has_oa else _read_local_tasks(_default_list_name()))

    for tid in dec.get("completed_task_ids", []):
        if tid in t_map:
            if has_oa:
                svc.tasks().patch(tasklist=lid, task=tid, body={"status": "completed"}).execute()
            else:
                for t in all_t:
                    if t["id"] == tid:
                        t["status"] = "completed"
            done.append(t_map[tid]["title"])

    stamp = datetime.datetime.now().strftime("%H:%M")
    for u in dec.get("progress_updates", []):
        tid = u.get("task_id")
        if tid in t_map and tid not in dec.get("completed_task_ids", []):
            merged = f"{t_map[tid]['notes']}\n[{stamp}] {u.get('note', '')}".strip()
            if has_oa:
                svc.tasks().patch(tasklist=lid, task=tid, body={"notes": merged}).execute()
            else:
                for t in all_t:
                    if t["id"] == tid:
                        t["notes"] = merged
            upd.append(t_map[tid]["title"])

    if not has_oa:
        _write_local_tasks(_default_list_name(), all_t)

    for n in dec.get("new_tasks", [])[:3]:
        if n.get("title"):
            add_task(n["title"], n.get("notes", ""))
            added.append(n["title"])
    next_md = dec.get("next_plan_md", "").strip()
    if next_md and os.path.isdir(target):
        with open(os.path.join(target, "NEXT_PLAN.md"), "w", encoding="utf-8") as fp:
            fp.write(next_md + "\n")
    rem = [t["title"] for t in tasks if t["id"] not in dec.get("completed_task_ids", [])] + added
    return done, upd, added, rem, next_md

def sync_coding_progress(agent_note: str = "", repo_path: str = "") -> str:
    target = repo_path.strip() or os.getenv("DEFAULT_REPO_PATH", os.getcwd())
    snap, tasks = get_repo_snapshot(target), get_open_tasks_raw()
    dec = _ask_gemini_reconcile(snap, tasks, agent_note)
    done, upd, added, rem, next_md = _apply_reconciliation(dec, tasks, target)
    send_summary(done, upd, added, rem, next_md[:200])
    return dec.get("spoken_summary", "Workspace synced with agenda.")
