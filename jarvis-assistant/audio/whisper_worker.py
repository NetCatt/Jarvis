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
        from faster_whisper import WhisperModel
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.stderr.flush()
        sys.exit(1)

    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    model_size = os.getenv("WHISPER_MODEL", "small.en")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    initial_prompt = os.getenv("WHISPER_INITIAL_PROMPT", "Fas, Mike Ross, Suits, Spotify, YouTube, Metallica, Daily Agenda, tasks")

    try:
        model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.stderr.flush()
        sys.exit(1)

    state = {
        "buffer": [],
        "last_text": "",
    }

    sys.stdout.write("READY\n")
    sys.stdout.flush()

    stdin = sys.stdin.buffer
    while True:
        chunk = _read_exact(stdin, 640)
        if not chunk:
            break
        if chunk.startswith(b"CMD:RESET"):
            state["buffer"].clear()
            state["last_text"] = ""
            sys.stdout.write('FINAL:{"text": ""}\n')
            sys.stdout.flush()
            continue
        if chunk.startswith(b"CMD:FINAL"):
            final_text = ""
            if len(state["buffer"]) > 1600:
                try:
                    audio_np = np.array(state["buffer"], dtype=np.float32)
                    segments, _ = model.transcribe(
                        audio_np,
                        beam_size=1,
                        vad_filter=False,
                        initial_prompt=initial_prompt,
                        language="en",
                    )
                    final_text = " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
                except Exception:
                    final_text = ""
            state["buffer"].clear()
            state["last_text"] = ""
            sys.stdout.write(f"FINAL:{json.dumps({'text': final_text})}\n")
            sys.stdout.flush()
            continue
        if len(chunk) < 640:
            chunk = chunk.ljust(640, b"\x00")
        samples = (np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0).tolist()
        state["buffer"].extend(samples)

if __name__ == "__main__":
    main()
