import datetime
import difflib
import json
import os
from dotenv import load_dotenv
from tools.notify import send_summary

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(env_path)
load_dotenv()

_TASKS_SVC = None
_LIST_ID_CACHE: dict[str, str] = {}
SCOPES = ["https://www.googleapis.com/auth/tasks"]


def _default_list_name() -> str:
    return os.getenv("GOOGLE_TASKS_LIST_NAME", "Daily Agenda")


def _res_path(fname: str) -> str:
    if os.path.isabs(fname):
        return fname
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), fname)
    return p if os.path.exists(p) else os.path.abspath(fname)


def _has_oauth() -> bool:
    token = _res_path(os.getenv("GOOGLE_TOKEN_FILE", "data/token.json"))
    creds_f = _res_path(os.getenv("GOOGLE_CREDENTIALS_FILE", "data/credentials.json"))
    return os.path.exists(token) or os.path.exists(creds_f)


def _get_local_file() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "local_tasks.json"))


def _read_local_store() -> dict[str, list[dict]]:
    """Local fallback is keyed by list name: {"Daily Agenda": [...], "Groceries": [...]}."""
    p = _get_local_file()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):  # migrate legacy flat format into the default list
            return {_default_list_name(): data}
        return data
    except Exception:
        return {}


def _write_local_store(store: dict[str, list[dict]]) -> None:
    path = _get_local_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def _read_local_tasks(list_name: str) -> list[dict]:
    return _read_local_store().get(list_name, [])


def _write_local_tasks(list_name: str, tasks: list[dict]) -> None:
    store = _read_local_store()
    store[list_name] = tasks
    _write_local_store(store)


def _get_tasks_service():
    global _TASKS_SVC
    if _TASKS_SVC is None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        token = _res_path(os.getenv("GOOGLE_TOKEN_FILE", "data/token.json"))
        creds_f = _res_path(os.getenv("GOOGLE_CREDENTIALS_FILE", "data/credentials.json"))
        creds = Credentials.from_authorized_user_file(token, SCOPES) if os.path.exists(token) else None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds = InstalledAppFlow.from_client_secrets_file(creds_f, SCOPES).run_local_server(port=0)
            os.makedirs(os.path.dirname(token), exist_ok=True)
            with open(token, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        _TASKS_SVC = build("tasks", "v1", credentials=creds, cache_discovery=False)
    return _TASKS_SVC


def get_service_and_list_id(list_name: str = ""):
    """Lazy init Google Tasks client and resolve/cache a named tasklist's ID, creating it if absent."""
    target = (list_name or _default_list_name()).strip()
    svc = _get_tasks_service()
    cache_key = target.lower()
    if cache_key not in _LIST_ID_CACHE:
        items = svc.tasklists().list(maxResults=100).execute().get("items", [])
        lid = next((i["id"] for i in items if i.get("title", "").strip().lower() == cache_key), None)
        if lid is None:
            lid = svc.tasklists().insert(body={"title": target}).execute()["id"]
        _LIST_ID_CACHE[cache_key] = lid
    return svc, _LIST_ID_CACHE[cache_key]


def list_task_lists() -> str:
    """List all existing Google Tasks lists (or the single local fallback list)."""
    if not _has_oauth():
        names = list(_read_local_store().keys()) or [_default_list_name()]
        return f"Local lists: {', '.join(names)}."
    svc = _get_tasks_service()
    items = svc.tasklists().list(maxResults=100).execute().get("items", [])
    names = [i.get("title", "").strip() for i in items if i.get("title", "").strip()]
    return f"Task lists: {', '.join(names)}." if names else "No task lists found."


def create_task_list(list_name: str) -> str:
    """Create a new, separate task list (distinct from the default Daily Agenda)."""
    list_name = list_name.strip()
    if not list_name:
        return "Need a name for the new list."
    if not _has_oauth():
        store = _read_local_store()
        store.setdefault(list_name, [])
        _write_local_store(store)
        return f"Created local list '{list_name}'."
    svc, _ = get_service_and_list_id(list_name)  # creates it if it doesn't already exist
    return f"Created task list '{list_name}'."


def get_open_tasks_raw(list_name: str = "") -> list[dict]:
    """Fetch raw incomplete tasks from a named Google Tasks list, or local fallback."""
    target = list_name or _default_list_name()
    if not _has_oauth():
        return [t for t in _read_local_tasks(target) if t.get("status") != "completed"]
    svc, lid = get_service_and_list_id(target)
    items = svc.tasks().list(tasklist=lid, showCompleted=False, maxResults=50).execute().get("items", [])
    return [
        {"id": t["id"], "title": t.get("title", "").strip(), "notes": t.get("notes", "").strip(), "due": (t.get("due") or "")[:10]}
        for t in items if t.get("title", "").strip()
    ]


def list_agenda(when: str = "all", list_name: str = "") -> str:
    """Voice/CLI output for open tasks in a named list (default: Daily Agenda). when='today' filters to tasks due today."""
    target = list_name or _default_list_name()
    tasks = get_open_tasks_raw(target)
    tag = " (Local)" if not _has_oauth() else ""
    label = f"'{target}'" if list_name else "Daily Agenda"
    if when.lower().strip() == "today":
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        tasks = [t for t in tasks if t.get("due") == today]
        if not tasks:
            return f"Nothing specifically due today in {label}{tag}."
        return f"{len(tasks)} due today in {label}{tag}: {', '.join(t['title'] for t in tasks[:6])}."
    if not tasks:
        return f"{label}{tag} is clear."
    due_soon = [t for t in tasks if t.get("due")]
    summary = f"{len(tasks)} open in {label}{tag}: {', '.join(t['title'] for t in tasks[:4])}."
    if due_soon:
        summary += " Scheduled: " + ", ".join(f"{t['title']} ({t['due']})" for t in due_soon[:3]) + "."
    return summary


def add_task(title: str, notes: str = "", due_date: str = "", list_name: str = "") -> str:
    """Insert new task into a named list (default: Daily Agenda) locally or on Google Tasks.
    due_date is an ISO date (YYYY-MM-DD), optional. list_name lets Fas organize tasks into
    separate lists (e.g. 'Groceries', 'Project X') instead of everything going into one agenda."""
    title, notes, due_date = title.strip(), notes.strip(), due_date.strip()
    target = list_name or _default_list_name()
    label = f"'{target}'" if list_name else "Daily Agenda"
    if not _has_oauth():
        tasks = _read_local_tasks(target)
        tasks.append({"id": f"task_{len(tasks)+1}", "title": title, "notes": notes, "status": "needsAction", "due": due_date})
        _write_local_tasks(target, tasks)
        suffix = f" for {due_date}" if due_date else ""
        return f"Added '{title}'{suffix} to {label} (Local)."
    svc, lid = get_service_and_list_id(target)
    body = {"title": title, "notes": notes}
    if due_date:
        body["due"] = f"{due_date}T00:00:00.000Z"
    svc.tasks().insert(tasklist=lid, body=body).execute()
    suffix = f" for {due_date}" if due_date else ""
    return f"Added '{title}'{suffix} to {label}."


def _match(query: str, tasks: list[dict]) -> tuple[float, dict | None]:
    q = query.lower().strip()
    scored = [(max(difflib.SequenceMatcher(None, q, t["title"].lower()).ratio(), 0.85 if q in t["title"].lower() else 0.0), t) for t in tasks]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0] if scored else (0.0, None)


def update_task_progress(task_query: str, progress_note: str, list_name: str = "") -> str:
    """Append timestamped progress note to a task in a named list (default: Daily Agenda)."""
    target = list_name or _default_list_name()
    tasks = get_open_tasks_raw(target)
    score, matched = _match(task_query, tasks)
    if not matched or score < 0.45:
        return f"No open task matching '{task_query}'."
    stamp = datetime.datetime.now().strftime("%H:%M")
    notes = f"{matched['notes']}\n[{stamp}] {progress_note}".strip()
    if not _has_oauth():
        all_t = _read_local_tasks(target)
        for t in all_t:
            if t["id"] == matched["id"]:
                t["notes"] = notes
        _write_local_tasks(target, all_t)
        return f"Updated progress on '{matched['title']}'."
    svc, lid = get_service_and_list_id(target)
    svc.tasks().patch(tasklist=lid, task=matched["id"], body={"notes": notes}).execute()
    return f"Updated progress on '{matched['title']}'."


def complete_task(task_query: str, list_name: str = "") -> str:
    """Complete a matching task in a named list (default: Daily Agenda) and send a standup report."""
    target = list_name or _default_list_name()
    tasks = get_open_tasks_raw(target)
    score, matched = _match(task_query, tasks)
    if not matched or score < 0.50:
        return f"No task matching '{task_query}' found."
    if not _has_oauth():
        all_t = _read_local_tasks(target)
        for t in all_t:
            if t["id"] == matched["id"]:
                t["status"] = "completed"
        _write_local_tasks(target, all_t)
    else:
        svc, lid = get_service_and_list_id(target)
        svc.tasks().patch(tasklist=lid, task=matched["id"], body={"status": "completed"}).execute()
    rem = [t["title"] for t in tasks if t["id"] != matched["id"]]
    send_summary(completed=[matched["title"]], remaining=rem)
    return f"Completed '{matched['title']}'. {len(rem)} remaining."
