import json
import os
import sys

def main():
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    try:
        import sounddevice as sd
        import torch
        from kokoro import KPipeline
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        voice_pt = os.path.join(base_dir, "data", "ross.pt")
        pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        voice = torch.load(voice_pt, map_location="cpu")
    except Exception as exc:
        sys.stderr.write(f"INIT_ERROR:{exc}\n")
        sys.stderr.flush()
        sys.exit(1)

    sys.stdout.write("READY\n")
    sys.stdout.flush()

    try:
        stream = sd.OutputStream(samplerate=24000, channels=1, dtype="float32")
        stream.start()
    except Exception:
        stream = None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "CMD:STOP":
            break
        try:
            req = json.loads(line)
            text = req.get("text", "")
            speed = float(req.get("speed", 1.0))
            if text:
                generator = pipeline(text, voice=voice, speed=speed)
                for result in generator:
                    if hasattr(result, "audio"):
                        chunk = result.audio.cpu().numpy()
                        if stream:
                            stream.write(chunk)
            sys.stdout.write(json.dumps({"status": "done"}) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps({"status": "error", "error": str(exc)}) + "\n")
            sys.stdout.flush()

    if stream:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
