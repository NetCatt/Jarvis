import os
import subprocess

def os_launch(target: str, args: list[str] | str = None) -> str:
    clean_target = target.strip()
    if not clean_target:
        return "Empty target specified."
    if ":" in clean_target and not os.path.exists(clean_target) and "\\" not in clean_target:
        try:
            os.startfile(clean_target)
            return f"Launched URI: {clean_target}"
        except Exception as exc:
            return f"Failed to launch URI {clean_target}: {exc}"
    if os.path.exists(clean_target):
        try:
            os.startfile(clean_target)
            return f"Opened {clean_target}"
        except Exception as exc:
            return f"Failed to open {clean_target}: {exc}"
    try:
        cmd = [clean_target]
        if args:
            if isinstance(args, str):
                cmd.extend(args.split())
            else:
                cmd.extend([str(a) for a in args])
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        return f"Launched application {clean_target}"
    except FileNotFoundError:
        try:
            os.startfile(clean_target)
            return f"Launched system target {clean_target}"
        except Exception as exc:
            return f"Application or command '{clean_target}' not found: {exc}"
    except Exception as exc:
        return f"Failed to launch '{clean_target}': {exc}"
