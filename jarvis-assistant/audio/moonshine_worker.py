import json
import os
import sys

def _read_exact(stream, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return bytes(buf) if buf else None
        buf.extend(chunk)
    return bytes(buf)

def main():
    try:
        import numpy as np
        import moonshine_voice
        from moonshine_voice import ModelArch, get_model_for_language
        from moonshine_voice.transcriber import Transcriber, LineTextChanged, LineCompleted
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.stderr.flush()
        sys.exit(1)

    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")

    model_path = os.getenv("MOONSHINE_MODEL_PATH")
    try:
        if model_path:
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Specified Moonshine model path not found: {model_path}")
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            local_cand = os.path.join(base_dir, "models", "moonshine-medium-streaming")
            if os.path.exists(local_cand):
                model_path = local_cand
            else:
                model_path, _ = get_model_for_language("en", ModelArch.MEDIUM_STREAMING)
        sample_rate = int(os.getenv("MOONSHINE_SAMPLE_RATE", "16000"))
        update_interval = float(os.getenv("MOONSHINE_UPDATE_INTERVAL", "0.35"))
        transcriber = Transcriber(model_path, model_arch=ModelArch.MEDIUM_STREAMING, update_interval=update_interval)
        try:
            transcriber.set_keyterms([
                "Fas", "Faas", "Mike", "Ross", "agenda", "Daily Agenda", "project", "repo",
                "subproject", "task", "list", "Redis", "caching", "standby", "tag", "flag",
                "isolate", "code", "branch", "git", "status", "tests", "benchmark", "folder",
                "browser", "YouTube", "Spotify", "upcoming", "neither"
            ])
        except Exception:
            pass
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.stderr.flush()
        sys.exit(1)

    state = {
        "last_partial": "",
        "final_emitted": False,
        "active_stream": None
    }

    def _on_event(event):
        if isinstance(event, LineCompleted):
            text = event.line.text.strip()
            state["final_emitted"] = True
            state["last_partial"] = ""
            sys.stdout.write(f"FINAL:{json.dumps({'text': text})}\n")
            sys.stdout.flush()
        elif isinstance(event, LineTextChanged):
            text = event.line.text.strip()
            state["last_partial"] = text
            sys.stdout.write(f"PARTIAL:{json.dumps({'partial': text})}\n")
            sys.stdout.flush()

    def _make_stream():
        st = transcriber.create_stream(update_interval=update_interval)
        st.add_listener(_on_event)
        st.start()
        state["final_emitted"] = False
        state["last_partial"] = ""
        return st

    state["active_stream"] = _make_stream()

    sys.stdout.write("READY\n")
    sys.stdout.flush()

    stdin = sys.stdin.buffer
    while True:
        chunk = _read_exact(stdin, 640)
        if not chunk:
            break
        if chunk.startswith(b"CMD:RESET"):
            try:
                state["active_stream"].stop()
            except Exception:
                pass
            sys.stdout.write('FINAL:{"text": ""}\n')
            sys.stdout.flush()
            state["active_stream"] = _make_stream()
            continue
        if chunk.startswith(b"CMD:FINAL"):
            state["final_emitted"] = False
            try:
                state["active_stream"].stop()
            except Exception:
                pass
            if not state["final_emitted"]:
                text = state["last_partial"]
                sys.stdout.write(f"FINAL:{json.dumps({'text': text})}\n")
                sys.stdout.flush()
            state["active_stream"] = _make_stream()
            continue
        if len(chunk) < 640:
            chunk = chunk.ljust(640, b"\x00")
        samples = (np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0).tolist()
        try:
            state["active_stream"].add_audio(samples, sample_rate)
        except Exception:
            pass

if __name__ == "__main__":
    main()
