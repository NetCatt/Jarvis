import json
import os
import sys

def _to_line(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw))
    except Exception:
        return raw.replace("\r", " ").replace("\n", " ").strip()

def main():
    import vosk
    vosk.SetLogLevel(-1)
    model_path = os.getenv("VOSK_MODEL_PATH")
    if not model_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(base_dir, "models", "vosk-model-en-us-0.22-lgraph")
        if not os.path.isdir(model_path):
            alt_path = os.path.join(base_dir, "models", "vosk-model-small-en-us-0.15")
            if os.path.isdir(alt_path):
                model_path = alt_path
    elif not os.path.isabs(model_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(base_dir, model_path)
    sample_rate = int(os.getenv("VOSK_SAMPLE_RATE", "16000"))
    model = vosk.Model(model_path)
    rec = vosk.KaldiRecognizer(model, sample_rate)
    rec.SetWords(False)
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    stdin = sys.stdin.buffer
    while True:
        chunk = stdin.read(640)
        if not chunk:
            break
        if chunk.startswith(b"CMD:RESET"):
            rec = vosk.KaldiRecognizer(model, sample_rate)
            rec.SetWords(False)
            sys.stdout.write('FINAL:{"text": ""}\n')
            sys.stdout.flush()
            continue
        if chunk.startswith(b"CMD:FINAL"):
            res = rec.FinalResult()
            sys.stdout.write(f"FINAL:{_to_line(res)}\n")
            sys.stdout.flush()
            rec = vosk.KaldiRecognizer(model, sample_rate)
            rec.SetWords(False)
            continue
        if rec.AcceptWaveform(chunk):
            res = rec.Result()
            sys.stdout.write(f"FINAL:{_to_line(res)}\n")
            sys.stdout.flush()
        else:
            partial = rec.PartialResult()
            sys.stdout.write(f"PARTIAL:{_to_line(partial)}\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
