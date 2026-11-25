import re
import time

_DENY_PATTERNS = re.compile(
    r"(format\s+[a-zA-Z]:|"
    r"rmdir\s+/[sS]|"
    r"del\s+/[sS]|"
    r"remove-item\s+.*-recurse.*-force|"
    r"\b(regedit|diskpart|shutdown|stop-computer|restart-computer|taskkill)\b|"
    r"\b(powershell|cmd|pwsh)\s+(-enc|-encodedcommand))",
    re.IGNORECASE
)

_HIGH_RISK_KEYS = {("ctrl", "w"), ("alt", "f4"), ("ctrl", "shift", "w")}

_PENDING_ACTION = None
_CONFIRM_WINDOW_SEC = 6.0

def evaluate_tool_safety(call_name: str, args: dict) -> tuple[str, str]:
    global _PENDING_ACTION
    cmd_str = str(args.get("command", "") or args.get("target", ""))
    if _DENY_PATTERNS.search(cmd_str):
        return "BLOCKED", f"Action blocked by safety policy: {cmd_str}"
    if call_name == "os_input":
        keys = args.get("keys", [])
        if isinstance(keys, str):
            key_list = [k.strip().lower() for k in keys.replace("+", " ").split()]
        elif isinstance(keys, list):
            key_list = [str(k).strip().lower() for k in keys]
        else:
            key_list = []
        if tuple(key_list) in _HIGH_RISK_KEYS or set(key_list).intersection({"f4"}):
            _PENDING_ACTION = {"call_name": call_name, "args": args, "time": time.time()}
            return "CONFIRM", "Just to be sure, Fas — want me to close that?"
    return "EXECUTE", "OK"

def handle_pending_confirmation(user_text: str) -> tuple[bool, str | None]:
    global _PENDING_ACTION
    if not _PENDING_ACTION:
        return False, None
    elapsed = time.time() - _PENDING_ACTION["time"]
    if elapsed > _CONFIRM_WINDOW_SEC:
        _PENDING_ACTION = None
        return False, None
    low = user_text.lower().strip().strip(".,!?")
    if low in ("yes", "do it", "confirm", "yeah", "yep", "sure", "proceed", "go ahead"):
        action = _PENDING_ACTION
        _PENDING_ACTION = None
        from tools import TOOL_MAP
        fn = TOOL_MAP.get(action["call_name"])
        if fn:
            try:
                res = str(fn(**action["args"]))
                return True, f"Done. {res}"
            except Exception as e:
                return True, f"Action failed: {e}"
        return True, "Executed confirmed action."
    if low in ("no", "cancel", "stop", "don't", "abort", "nope"):
        _PENDING_ACTION = None
        return True, "Cancelled action, Fas."
    _PENDING_ACTION = None
    return False, None
