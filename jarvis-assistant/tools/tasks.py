import datetime
import difflib
import json
import os
import urllib.parse
import urllib.request
from dotenv import load_dotenv
from tools.notify import send_summary

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(env_path)
load_dotenv()

_LIST_ID_CACHE: dict[str, str] = {}


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
    p = _get_local_file()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
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


def _refresh_token_if_needed(token_path: str, token_data: dict) -> str:
    expiry_str = token_data.get("expiry")
    needs_refresh = False
    if expiry_str:
        try:
            exp = datetime.datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            if datetime.datetime.now(datetime.timezone.utc) >= exp:
                needs_refresh = True
        except Exception:
            pass
    if needs_refresh and token_data.get("refresh_token"):
        post_data = urllib.parse.urlencode({
            "client_id": token_data.get("client_id"),
            "client_secret": token_data.get("client_secret"),
            "refresh_token": token_data.get("refresh_token"),
            "grant_type": "refresh_token",
        }).encode("utf-8")
        req = urllib.request.Request(token_data.get("token_uri", "https://oauth2.googleapis.com/token"), data=post_data)
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            new_data = json.loads(resp.read().decode("utf-8"))
        token_data["token"] = new_data.get("access_token", token_data["token"])
        with open(token_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f)
    return token_data.get("token", "")


def _get_access_token() -> str:
    token_file = _res_path(os.getenv("GOOGLE_TOKEN_FILE", "data/token.json"))
    if not os.path.exists(token_file):
        return ""
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            token_data = json.load(f)
        return _refresh_token_if_needed(token_file, token_data)
    except Exception:
        return ""


def _tasks_rest(method: str, path: str, body: dict = None) -> dict:
    token = _get_access_token()
    if not token:
        return {}
    url = f"https://tasks.googleapis.com/tasks/v1/{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


class _TasksServiceShim:
    class _TasksResource:
        def patch(self, tasklist: str, task: str, body: dict):
            class _Exec:
                def execute(self):
                    return _tasks_rest("PATCH", f"lists/{tasklist}/tasks/{task}", body)
            return _Exec()

        def insert(self, tasklist: str, body: dict):
            class _Exec:
                def execute(self):
                    return _tasks_rest("POST", f"lists/{tasklist}/tasks", body)
            return _Exec()

        def list(self, tasklist: str, showCompleted: bool = False, maxResults: int = 50):
            class _Exec:
                def execute(self):
                    return _tasks_rest("GET", f"lists/{tasklist}/tasks?showCompleted={str(showCompleted).lower()}&maxResults={maxResults}")
            return _Exec()

    class _TasklistsResource:
        def list(self, maxResults: int = 100):
            class _Exec:
                def execute(self):
                    return _tasks_rest("GET", f"users/@me/lists?maxResults={maxResults}")
            return _Exec()

        def insert(self, body: dict):
            class _Exec:
                def execute(self):
                    return _tasks_rest("POST", "users/@me/lists", body)
            return _Exec()

    def tasks(self):
        return self._TasksResource()

    def tasklists(self):
        return self._TasklistsResource()


_SERVICE_SHIM = _TasksServiceShim()


def get_service_and_list_id(list_name: str = ""):
    target = (list_name or _default_list_name()).strip()
    cache_key = target.lower()
    if cache_key not in _LIST_ID_CACHE:
        try:
            data = _tasks_rest("GET", "users/@me/lists?maxResults=100")
            items = data.get("items", [])
            lid = next((i["id"] for i in items if i.get("title", "").strip().lower() == cache_key), None)
            if lid is None:
                new_list = _tasks_rest("POST", "users/@me/lists", {"title": target})
                lid = new_list.get("id")
            _LIST_ID_CACHE[cache_key] = lid
        except Exception:
            _LIST_ID_CACHE[cache_key] = ""
    return _SERVICE_SHIM, _LIST_ID_CACHE[cache_key]


def list_task_lists() -> str:
    if not _has_oauth():
        names = list(_read_local_store().keys()) or [_default_list_name()]
        return f"Local lists: {', '.join(names)}."
    try:
        data = _tasks_rest("GET", "users/@me/lists?maxResults=100")
        items = data.get("items", [])
        names = [i.get("title", "").strip() for i in items if i.get("title", "").strip()]
        return f"Task lists: {', '.join(names)}." if names else "No task lists found."
    except Exception:
        names = list(_read_local_store().keys()) or [_default_list_name()]
        return f"Local lists: {', '.join(names)}."


def create_task_list(list_name: str) -> str:
    list_name = list_name.strip()
    if not list_name:
        return "Need a name for the new list."
    if not _has_oauth():
        store = _read_local_store()
        store.setdefault(list_name, [])
        _write_local_store(store)
        return f"Created local list '{list_name}'."
    try:
        _tasks_rest("POST", "users/@me/lists", {"title": list_name})
        return f"Created task list '{list_name}'."
    except Exception:
        store = _read_local_store()
        store.setdefault(list_name, [])
        _write_local_store(store)
        return f"Created local list '{list_name}'."


def get_open_tasks_raw(list_name: str = "") -> list[dict]:
    target = list_name or _default_list_name()
    if not _has_oauth():
        return [t for t in _read_local_tasks(target) if t.get("status") != "completed"]
    try:
        _, lid = get_service_and_list_id(target)
        if not lid:
            return [t for t in _read_local_tasks(target) if t.get("status") != "completed"]
        data = _tasks_rest("GET", f"lists/{lid}/tasks?showCompleted=false&maxResults=50")
        items = data.get("items", [])
        return [
            {"id": str(t.get("id") or ""), "title": str(t.get("title") or "").strip(), "notes": str(t.get("notes") or "").strip(), "due": str(t.get("due") or "")[:10]}
            for t in items if str(t.get("title") or "").strip()
        ]
    except Exception:
        return [t for t in _read_local_tasks(target) if t.get("status") != "completed"]


def get_completed_tasks_raw(list_name: str = "") -> list[dict]:
    target = list_name or _default_list_name()
    if not _has_oauth():
        return [t for t in _read_local_tasks(target) if t.get("status") == "completed"]
    try:
        _, lid = get_service_and_list_id(target)
        if not lid:
            return [t for t in _read_local_tasks(target) if t.get("status") == "completed"]
        data = _tasks_rest("GET", f"lists/{lid}/tasks?showCompleted=true&showHidden=true&maxResults=20")
        items = data.get("items", [])
        return [
            {"id": str(t.get("id") or ""), "title": str(t.get("title") or "").strip(), "notes": str(t.get("notes") or "").strip(), "status": "completed"}
            for t in items if str(t.get("status") or "") == "completed" and str(t.get("title") or "").strip()
        ]
    except Exception:
        return [t for t in _read_local_tasks(target) if t.get("status") == "completed"]


def get_open_tasks_context(list_name: str = "") -> str:
    target = list_name or _default_list_name()
    tasks = get_open_tasks_raw(target)
    completed = get_completed_tasks_raw(target)
    lines = []
    if tasks:
        lines.append("Open Tasks:")
        for t in tasks:
            title = str(t.get("title") or "").strip()
            notes = str(t.get("notes") or "").strip()
            due = str(t.get("due") or "").strip()
            due_str = f" (due: {due})" if due else ""
            if notes:
                lines.append(f"- {title}{due_str}:\n  Notes: {notes}")
            else:
                lines.append(f"- {title}{due_str}")
    else:
        lines.append("No open tasks.")
    if completed:
        lines.append("Recently Completed Tasks:")
        for t in completed[:5]:
            title = str(t.get("title") or "").strip()
            lines.append(f"- [Completed] {title}")
    return "\n".join(lines)


def list_agenda(when: str = "all", list_name: str = "") -> str:
    target = list_name or _default_list_name()
    tag = " (Local)" if not _has_oauth() else ""
    label = f"'{target}'" if list_name else "Daily Agenda"
    if when.lower().strip() == "completed":
        completed = get_completed_tasks_raw(target)
        if not completed:
            return f"No completed tasks found in {label}{tag}."
        items = [str(t.get("title") or "Untitled") for t in completed[:6]]
        return f"{len(completed)} completed in {label}{tag}: {'; '.join(items)}."
    tasks = get_open_tasks_raw(target)
    if when.lower().strip() == "today":
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        tasks = [t for t in tasks if str(t.get("due") or "") == today]
        if not tasks:
            return f"Nothing specifically due today in {label}{tag}."
        items = []
        for t in tasks[:6]:
            raw_notes = str(t.get("notes") or "").strip()
            recent = raw_notes.splitlines()[-1].strip() if raw_notes else ""
            item_str = str(t.get("title") or "Untitled") + (f" [Status: {recent}]" if recent else "")
            items.append(item_str)
        return f"{len(tasks)} due today in {label}{tag}: {'; '.join(items)}."
    if not tasks:
        return f"{label}{tag} is clear."
    due_soon = [t for t in tasks if str(t.get("due") or "")]
    items = []
    for t in tasks[:4]:
        raw_notes = str(t.get("notes") or "").strip()
        recent = raw_notes.splitlines()[-1].strip() if raw_notes else ""
        item_str = str(t.get("title") or "Untitled") + (f" [Status: {recent}]" if recent else "")
        items.append(item_str)
    summary = f"{len(tasks)} open in {label}{tag}: {'; '.join(items)}."
    if due_soon:
        summary += " Scheduled: " + ", ".join(f"{str(t.get('title') or 'Untitled')} ({str(t.get('due') or '')})" for t in due_soon[:3]) + "."
    return summary


def add_task(title: str, notes: str = "", due_date: str = "", list_name: str = "") -> str:
    title, notes, due_date = title.strip(), notes.strip(), due_date.strip()
    target = list_name or _default_list_name()
    label = f"'{target}'" if list_name else "Daily Agenda"
    if not _has_oauth():
        tasks = _read_local_tasks(target)
        tasks.append({"id": f"task_{len(tasks)+1}", "title": title, "notes": notes, "status": "needsAction", "due": due_date})
        _write_local_tasks(target, tasks)
        suffix = f" for {due_date}" if due_date else ""
        return f"Added '{title}'{suffix} to {label} (Local)."
    try:
        _, lid = get_service_and_list_id(target)
        body = {"title": title, "notes": notes}
        if due_date:
            body["due"] = f"{due_date}T00:00:00.000Z"
        _tasks_rest("POST", f"lists/{lid}/tasks", body)
        suffix = f" for {due_date}" if due_date else ""
        return f"Added '{title}'{suffix} to {label}."
    except Exception:
        tasks = _read_local_tasks(target)
        tasks.append({"id": f"task_{len(tasks)+1}", "title": title, "notes": notes, "status": "needsAction", "due": due_date})
        _write_local_tasks(target, tasks)
        suffix = f" for {due_date}" if due_date else ""
        return f"Added '{title}'{suffix} to {label} (Local)."


def _match(query: str, tasks: list[dict]) -> tuple[float, dict | None]:
    q = query.lower().strip()
    scored = [(max(difflib.SequenceMatcher(None, q, str(t.get("title") or "").lower()).ratio(), 0.85 if q in str(t.get("title") or "").lower() else 0.0), t) for t in tasks]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0] if scored else (0.0, None)


def update_task_progress(task_query: str, progress_note: str, list_name: str = "") -> str:
    target = list_name or _default_list_name()
    tasks = get_open_tasks_raw(target)
    score, matched = _match(task_query, tasks)
    if not matched or score < 0.45:
        return f"No open task matching '{task_query}'."
    stamp = datetime.datetime.now().strftime("%H:%M")
    notes = f"{str(matched.get('notes') or '').strip()}\n[{stamp}] {progress_note}".strip()
    matched_title = str(matched.get("title") or "Untitled")
    if not _has_oauth():
        all_t = _read_local_tasks(target)
        for t in all_t:
            if str(t.get("id") or "") == str(matched.get("id") or ""):
                t["notes"] = notes
        _write_local_tasks(target, all_t)
        return f"Updated progress on '{matched_title}'."
    try:
        _, lid = get_service_and_list_id(target)
        _tasks_rest("PATCH", f"lists/{lid}/tasks/{matched.get('id')}", {"notes": notes})
        return f"Updated progress on '{matched_title}'."
    except Exception:
        all_t = _read_local_tasks(target)
        for t in all_t:
            if str(t.get("id") or "") == str(matched.get("id") or ""):
                t["notes"] = notes
        _write_local_tasks(target, all_t)
        return f"Updated progress on '{matched_title}'."


def complete_task(task_query: str, list_name: str = "") -> str:
    target = list_name or _default_list_name()
    tasks = get_open_tasks_raw(target)
    score, matched = _match(task_query, tasks)
    if not matched or score < 0.50:
        return f"No task matching '{task_query}' found."
    if not _has_oauth():
        all_t = _read_local_tasks(target)
        for t in all_t:
            if str(t.get("id") or "") == str(matched.get("id") or ""):
                t["status"] = "completed"
        _write_local_tasks(target, all_t)
    else:
        try:
            _, lid = get_service_and_list_id(target)
            _tasks_rest("PATCH", f"lists/{lid}/tasks/{matched.get('id')}", {"status": "completed"})
        except Exception:
            all_t = _read_local_tasks(target)
            for t in all_t:
                if str(t.get("id") or "") == str(matched.get("id") or ""):
                    t["status"] = "completed"
            _write_local_tasks(target, all_t)
    rem = [str(t.get("title") or "Untitled") for t in tasks if str(t.get("id") or "") != str(matched.get("id") or "")]
    matched_title = str(matched.get("title") or "Untitled")
    send_summary(completed=[matched_title], remaining=rem)
    return f"Completed '{matched_title}'. {len(rem)} remaining."
