import ast
import datetime
import json
import operator
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request

_TIMERS = {}
_TIMERS_LOCK = threading.Lock()
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 20:
            raise ValueError("Exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Unsupported expression")

def _parse_duration_sec(duration: str | int | float) -> int:
    if isinstance(duration, (int, float)):
        return max(1, int(duration))
    txt = str(duration or "").lower().strip()
    if txt.isdigit():
        return max(1, int(txt))
    total = 0
    for val_s, unit in re.findall(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)", txt):
        val = int(val_s)
        if unit.startswith("h"):
            total += val * 3600
        elif unit.startswith("m"):
            total += val * 60
        else:
            total += val
    return total

def _play_timer_alert(label: str) -> None:
    try:
        import math
        import struct
        import sounddevice as sd
        sr = 16000
        tone = b"".join(
            struct.pack("<h", int(10000 * math.sin(2 * math.pi * 880 * i / sr)))
            for i in range(int(sr * 0.25))
        )
        with sd.RawOutputStream(samplerate=sr, channels=1, dtype="int16") as stream:
            stream.write(tone)
            time.sleep(0.08)
            stream.write(tone)
    except Exception:
        pass
    try:
        from audio.tts import speak
        msg = f"Time's up for {label}, Fas." if label else "Your timer is up, Fas."
        speak(msg, emotion="urgent")
    except Exception:
        pass

def set_timer(duration: str | int, label: str = "") -> str:
    secs = _parse_duration_sec(duration)
    if secs <= 0:
        return "Tell me how long for the timer, Fas."
    clean_label = (label or "").strip() or f"{secs}s"
    def _fire():
        with _TIMERS_LOCK:
            _TIMERS.pop(clean_label.lower(), None)
        _play_timer_alert(clean_label)
    t = threading.Timer(secs, _fire)
    t.daemon = True
    with _TIMERS_LOCK:
        old = _TIMERS.pop(clean_label.lower(), None)
        if old:
            old["timer"].cancel()
        _TIMERS[clean_label.lower()] = {"timer": t, "label": clean_label, "ends_at": time.time() + secs}
    t.start()
    if secs >= 60:
        mins, rem = divmod(secs, 60)
        span = f"{mins} minute{'s' if mins != 1 else ''}" + (f" {rem} seconds" if rem else "")
    else:
        span = f"{secs} second{'s' if secs != 1 else ''}"
    return f"Timer set for {span}, Fas."

def list_timers() -> str:
    now = time.time()
    with _TIMERS_LOCK:
        active = [(v["label"], max(0, int(v["ends_at"] - now))) for v in _TIMERS.values() if v["ends_at"] > now]
    if not active:
        return "No active timers right now, Fas."
    parts = [f"{lbl}: {rem}s left" for lbl, rem in active]
    return "Active timers: " + ", ".join(parts) + "."

def cancel_timer(label: str = "") -> str:
    key = (label or "").strip().lower()
    with _TIMERS_LOCK:
        if key and key in _TIMERS:
            _TIMERS.pop(key)["timer"].cancel()
            return f"Cancelled timer {label}, Fas."
        if not _TIMERS:
            return "No active timers to cancel, Fas."
        if not key:
            for item in _TIMERS.values():
                item["timer"].cancel()
            _TIMERS.clear()
            return "Cancelled all timers, Fas."
    return f"No timer named {label} found, Fas."

def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

def _try_math(text: str) -> str | None:
    low = text.lower().strip(" ?.!")
    pct = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(\d+(?:\.\d+)?)", low)
    if pct:
        res = (float(pct.group(1)) / 100.0) * float(pct.group(2))
        return f"{res:g}"
    cleaned = low
    for w, sym in (("plus", "+"), ("minus", "-"), ("times", "*"), ("multiplied by", "*"), ("divided by", "/"), ("over", "/"), ("x", "*")):
        cleaned = re.sub(rf"\b{w}\b", f" {sym} ", cleaned)
    expr = re.sub(r"[^0-9+\-*/().% ]", "", cleaned).strip()
    if not expr or not re.search(r"[+\-*/]", expr) or not re.search(r"\d", expr):
        return None
    try:
        val = _safe_eval(ast.parse(expr, mode="eval"))
        return f"That's {val:g}, Fas."
    except Exception:
        return None

def quick_answer(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "What do you want me to look up, Fas?"
    low = q.lower()
    if any(k in low for k in ("what time is it", "current time", "what's the time")):
        return f"It's {datetime.datetime.now().strftime('%I:%M %p')}, Fas."
    if any(k in low for k in ("what is today's date", "what's the date", "today's date", "what day is it")):
        return f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}, Fas."
    math_res = _try_math(q)
    if math_res:
        return math_res
    ctx = _ssl_context()
    if "weather" in low or "temperature" in low or "forecast" in low:
        loc_m = re.search(r"(?:weather|temperature|forecast)\s+(?:in|at|for)\s+([a-zA-Z0-9 ,.-]+)", q, flags=re.IGNORECASE)
        loc = urllib.parse.quote(loc_m.group(1).strip(" ?.!") if loc_m else "")
        try:
            url = f"https://wttr.in/{loc}?format=%C,+%t,+feels+like+%f"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
            body = urllib.request.urlopen(req, timeout=3.5, context=ctx).read().decode("utf-8", errors="ignore").strip()
            if body and "unknown location" not in body.lower():
                place = loc_m.group(1).strip(" ?.!") if loc_m else "here"
                return f"Weather in {place}: {body}."
        except Exception:
            pass
    try:
        ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote_plus(q)}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(ddg_url, headers={"User-Agent": "Jarvis/1.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=3.5, context=ctx).read().decode("utf-8", errors="ignore"))
        ans = (data.get("AbstractText") or data.get("Answer") or data.get("Definition") or "").strip()
        if ans:
            sent = ans.split(". ")[0].strip()
            return sent if sent.endswith(".") else f"{sent}."
    except Exception:
        pass
    return f"I couldn't fetch a direct answer for {q}, Fas."
