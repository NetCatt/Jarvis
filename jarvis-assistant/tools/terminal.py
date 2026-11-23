import os
import re
import subprocess

_BLOCKLIST = re.compile(
    r"(format\s+[a-zA-Z]:|"
    r"rmdir\s+/[sS]|"
    r"del\s+/[sS]\s+[a-zA-Z]:|"
    r"remove-item\s+.*-recurse.*-force\s+([a-zA-Z]:\\|\$env:SystemDrive)|\b"
    r"(shutdown\s+/[sSrR]|stop-computer|restart-computer)\b)",
    re.IGNORECASE,
)


def run_terminal(command: str, timeout: float = 5.0) -> str:
    cmd_clean = command.strip()
    if not cmd_clean:
        return "Empty terminal command."
    if _BLOCKLIST.search(cmd_clean):
        return f"Command blocked by safety policy: {cmd_clean}"

    shell_exe = "powershell.exe"
    shell_args = [shell_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd_clean]

    try:
        proc = subprocess.run(
            shell_args,
            capture_output=True,
            text=True,
            timeout=float(timeout),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            errors="replace",
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        combined = f"{out}\n{err}".strip() if (out and err) else (out or err)

        if proc.returncode != 0:
            msg = combined[:400] if combined else f"exit code {proc.returncode}"
            return f"Terminal error ({proc.returncode}): {msg}"

        if not combined:
            return "Command executed successfully."
        return combined[:500]
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except Exception as exc:
        return f"Terminal execution failed: {exc}"
