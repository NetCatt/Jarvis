import os
import subprocess

APP_MAP = {
    "vscode": "code",
    "antigravity": "antigravity",
    "spotify": "spotify",
    "firefox": "firefox",
    "edge": "msedge",
    "terminal": "wt",
    "bash": "C:/Program Files/Git/git-bash.exe",
}


def open_app(app_name: str) -> str:
    """Launch local desktop application via Win32 os.startfile or bounded subprocess."""
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
