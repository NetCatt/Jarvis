import os
import subprocess

_SPOTIFY_EXE = os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")
APP_MAP = {
    "vscode": "code",
    "antigravity": "antigravity",
    "spotify": _SPOTIFY_EXE if os.path.exists(_SPOTIFY_EXE) else "spotify",
    "firefox": "firefox",
    "edge": "msedge",
    "terminal": "wt",
    "bash": "C:/Program Files/Git/git-bash.exe",
}


def open_app(app_name: str) -> str:
    name = app_name.lower().strip()
    target = APP_MAP.get(name, name)
    try:
        if os.path.exists(target):
            os.startfile(target)
            return f"Opened {app_name}."
        subprocess.Popen([target], shell=True)
        return f"Launched {app_name}."
    except Exception as exc:
        return f"Failed to open {app_name}: {exc}"


def open_folder(target: str = "") -> str:
    raw = target.strip().lower()
    home = os.path.expanduser("~")
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    aliases = {
        "": repo_root,
        "here": repo_root,
        "repo": repo_root,
        "project": repo_root,
        "assistant": repo_root,
        "downloads": os.path.join(home, "Downloads"),
        "documents": os.path.join(home, "Documents"),
        "desktop": os.path.join(home, "Desktop"),
        "models": os.path.join(repo_root, "models"),
        "audio": os.path.join(repo_root, "audio"),
        "tools": os.path.join(repo_root, "tools"),
        "data": os.path.join(repo_root, "data"),
        "tests": os.path.join(repo_root, "tests"),
        "code": "d:/Faisal/Code",
        "workflow": "d:/Faisal/Code/workflow automation",
    }
    resolved = aliases.get(raw)
    if not resolved:
        for k, v in aliases.items():
            if k and k in raw:
                resolved = v
                break
    if not resolved:
        resolved = target.strip()
    resolved = os.path.expandvars(os.path.expanduser(resolved))
    if os.path.exists(resolved):
        os.startfile(resolved)
        name = os.path.basename(resolved.rstrip("/\\")) or resolved
        return f"Opened {name} folder for you, Fas."
    return f"Folder {target} not found on system."


def search_files(query: str, root_dir: str = "") -> str:
    term = query.strip().lower()
    if not term:
        return "Please specify a filename or keyword to search for."
    base = root_dir.strip() or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if not os.path.exists(base):
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    matches = []
    for root, dirs, files in os.walk(base):
        if any(ign in root for ign in (".git", "__pycache__", "node_modules", ".venv")):
            continue
        for f in files:
            if term in f.lower():
                matches.append(os.path.join(root, f))
                if len(matches) >= 5:
                    break
        if len(matches) >= 5:
            break
    if not matches:
        return f"No files matching '{query}' found in {os.path.basename(base) or base}."
    results = [os.path.basename(m) for m in matches]
    return f"Found {len(matches)} files: {', '.join(results)}."
