import datetime
import difflib
import os
from tools.notify import send_summary

_TASKS_SVC, _LIST_ID = None, None
SCOPES = ["https://www.googleapis.com/auth/tasks"]


def get_service_and_list_id():
    """Lazy init Google Tasks client and cache target tasklist ID."""
    global _TASKS_SVC, _LIST_ID
    if _TASKS_SVC is None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        token, creds_f = os.getenv("GOOGLE_TOKEN_FILE", "token.json"), os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        creds = Credentials.from_authorized_user_file(token, SCOPES) if os.path.exists(token) else None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds = InstalledAppFlow.from_client_secrets_file(creds_f, SCOPES).run_local_server(port=0)
            with open(token, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        _TASKS_SVC = build("tasks", "v1", credentials=creds, cache_discovery=False)
    if _LIST_ID is None:
        target = os.getenv("GOOGLE_TASKS_LIST_NAME", "Daily Agenda").lower()
        items = _TASKS_SVC.tasklists().list(maxResults=50).execute().get("items", [])
        _LIST_ID = next((i["id"] for i in items if i.get("title", "").strip().lower() == target), None)
        if _LIST_ID is None:
            _LIST_ID = _TASKS_SVC.tasklists().insert(body={"title": target}).execute()["id"]
    return _TASKS_SVC, _LIST_ID


def get_open_tasks_raw() -> list[dict]:
    """Fetch raw incomplete tasks."""
    svc, lid = get_service_and_list_id()
    items = svc.tasks().list(tasklist=lid, showCompleted=False, maxResults=50).execute().get("items", [])
    return [{"id": t["id"], "title": t.get("title", "").strip(), "notes": t.get("notes", "").strip()} for t in items if t.get("title", "").strip()]


def list_agenda() -> str:
    """Voice/CLI output for open tasks."""
    tasks = get_open_tasks_raw()
    return f"{len(tasks)} open tasks: {', '.join(t['title'] for t in tasks[:4])}." if tasks else "Daily Agenda is clear."


def add_task(title: str, notes: str = "") -> str:
    """Insert new task."""
    svc, lid = get_service_and_list_id()
    svc.tasks().insert(tasklist=lid, body={"title": title.strip(), "notes": notes.strip()}).execute()
    return f"Added '{title}' to Daily Agenda."


def _match(query: str, tasks: list[dict]) -> tuple[float, dict | None]:
    q = query.lower().strip()
    scored = [(max(difflib.SequenceMatcher(None, q, t["title"].lower()).ratio(), 0.85 if q in t["title"].lower() else 0.0), t) for t in tasks]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0] if scored else (0.0, None)


def update_task_progress(task_query: str, progress_note: str) -> str:
    """Append timestamped progress note to task."""
    svc, lid = get_service_and_list_id()
    tasks = get_open_tasks_raw()
    score, matched = _match(task_query, tasks)
    if not matched or score < 0.45:
        return f"No open task matching '{task_query}'."
    stamp = datetime.datetime.now().strftime("%H:%M")
    notes = f"{matched['notes']}\n[{stamp}] {progress_note}".strip()
    svc.tasks().patch(tasklist=lid, task=matched["id"], body={"notes": notes}).execute()
    return f"Updated progress on '{matched['title']}'."


def complete_task(task_query: str) -> str:
    """Complete matching task and send standup report."""
    svc, lid = get_service_and_list_id()
    tasks = get_open_tasks_raw()
    score, matched = _match(task_query, tasks)
    if not matched or score < 0.50:
        return f"No task matching '{task_query}' found."
    svc.tasks().patch(tasklist=lid, task=matched["id"], body={"status": "completed"}).execute()
    rem = [t["title"] for t in tasks if t["id"] != matched["id"]]
    send_summary(completed=[matched["title"]], remaining=rem)
    return f"Completed '{matched['title']}'. {len(rem)} remaining."
