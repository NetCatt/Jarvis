import json
import os
import queue
import subprocess
import sys
import threading
import time

def render_live_token(text: str) -> None:
    if text:
        clean = text.strip().replace("\n", " ")
        if len(clean) > 65:
            clean = "..." + clean[-62:]
        sys.stdout.write(f"\r\033[K[Fas, live]: {clean}")
        sys.stdout.flush()

class StreamingTranscriber:
    def __init__(self, model_path: str = None, sample_rate: int = 16000, engine: str = "moonshine"):
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.engine = engine
        self.active_engine = None
        self.process = None
        self.out_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.reader_thread = None
        self.stderr_thread = None
        self.finalized_chunks = []
        self.current_partial = ""
        self.last_is_final = False

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.stop_event.clear()
        target = (self.engine or "moonshine").lower()
        if "whisper" in target:
            if self._try_start_whisper():
                self.active_engine = "whisper"
                return
            if self._try_start_moonshine():
                self.active_engine = "moonshine"
                return
            raise RuntimeError("Failed to start whisper_worker")
        if self._try_start_moonshine():
            self.active_engine = "moonshine"
            return
        raise RuntimeError("Failed to start speech recognition worker")

    def _try_start_whisper(self) -> bool:
        worker_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_worker.py")
        if not os.path.isfile(worker_script):
            return False
        env = os.environ.copy()
        if self.model_path:
            env["WHISPER_MODEL"] = self.model_path
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", worker_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                env=env,
            )
        except Exception:
            return False

        ready_line = ""
        deadline = time.time() + 25.0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.01)
                    continue
                txt = line.decode("utf-8", errors="replace").strip()
                if txt == "READY":
                    ready_line = "READY"
                    break
                elif txt.startswith("ERROR:"):
                    break
            except Exception:
                break

        if ready_line != "READY":
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return False

        self.process = proc
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        self.stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self.stderr_thread.start()
        return True

    def _try_start_moonshine(self) -> bool:
        worker_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moonshine_worker.py")
        if not os.path.isfile(worker_script):
            return False
        env = os.environ.copy()
        if self.model_path:
            env["MOONSHINE_MODEL_PATH"] = self.model_path
        env["MOONSHINE_SAMPLE_RATE"] = str(self.sample_rate)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", worker_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                env=env,
            )
        except Exception:
            return False

        ready_line = ""
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.01)
                    continue
                txt = line.decode("utf-8", errors="replace").strip()
                if txt == "READY":
                    ready_line = "READY"
                    break
                elif txt.startswith("ERROR:"):
                    break
            except Exception:
                break

        if ready_line != "READY":
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return False

        self.process = proc
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        self.stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self.stderr_thread.start()
        return True

    def _stderr_loop(self) -> None:
        while not self.stop_event.is_set():
            if not self.process or not self.process.stderr:
                break
            try:
                line = self.process.stderr.readline()
            except (ValueError, OSError):
                break
            if not line:
                break

    def _reader_loop(self) -> None:
        buf = ""
        while not self.stop_event.is_set():
            try:
                line = self.process.stdout.readline()
            except (ValueError, OSError):
                break
            if not line:
                break
            txt = line.decode("utf-8", errors="replace")
            txt_clean = txt.strip()
            if not txt_clean:
                continue
            if txt_clean.startswith(("FINAL:", "PARTIAL:", "{")) or len(buf) > 4096:
                buf = txt_clean
            elif buf:
                buf += " " + txt_clean
            else:
                buf = txt_clean
            if buf.startswith("FINAL:") or buf.startswith("PARTIAL:"):
                prefix = "FINAL:" if buf.startswith("FINAL:") else "PARTIAL:"
                raw = buf[len(prefix):].strip()
                try:
                    json.loads(raw)
                    self.out_queue.put(buf)
                    buf = ""
                except Exception:
                    continue
            elif buf.startswith("{"):
                try:
                    json.loads(buf)
                    self.out_queue.put(buf)
                    buf = ""
                except Exception:
                    continue
            else:
                self.out_queue.put(buf)
                buf = ""

    def _parse_line(self, line: str) -> tuple[str, bool]:
        line = line.strip()
        if not line:
            return "", False
        if line.startswith("FINAL:"):
            raw = line[6:].strip()
            try:
                data = json.loads(raw)
                return data.get("text", ""), True
            except Exception:
                return "", True
        if line.startswith("PARTIAL:"):
            raw = line[8:].strip()
            try:
                data = json.loads(raw)
                return data.get("partial", ""), False
            except Exception:
                return "", False
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if "text" in data:
                    return data.get("text", ""), True
                return data.get("partial", ""), False
            except Exception:
                return "", False
        return "", False

    def _handle_line(self, line: str) -> None:
        chunk, is_final = self._parse_line(line)
        if is_final:
            if chunk:
                self.finalized_chunks.append(chunk)
            self.current_partial = ""
            self.last_is_final = True
        else:
            self.current_partial = chunk
            self.last_is_final = False

    def get_transcript(self) -> str:
        parts = list(self.finalized_chunks)
        if self.current_partial:
            parts.append(self.current_partial)
        return " ".join(parts).strip()

    def feed_pcm(self, pcm_bytes: bytes) -> tuple[str, bool]:
        if not self.process or not self.process.stdin or self.process.poll() is not None:
            sys.stderr.write("STT: Worker process not running\n")
            sys.stderr.flush()
            return self.get_transcript(), False
        try:
            for offset in range(0, len(pcm_bytes), 640):
                frame = pcm_bytes[offset:offset + 640]
                if len(frame) < 640:
                    frame = frame.ljust(640, b"\x00")
                self.process.stdin.write(frame)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, RuntimeError) as e:
            sys.stderr.write(f"STT: Worker write error: {e}\n")
            sys.stderr.flush()
            return self.get_transcript(), False
        try:
            line = self.out_queue.get(timeout=0.005)
            self._handle_line(line)
        except queue.Empty:
            pass
        while not self.out_queue.empty():
            try:
                line = self.out_queue.get_nowait()
                self._handle_line(line)
            except queue.Empty:
                break
        return self.get_transcript(), self.last_is_final

    def get_final(self) -> str:
        if not self.process or self.process.poll() is not None:
            return self.get_transcript()
        self.process.stdin.write(b"CMD:FINAL".ljust(640, b"\x00"))
        self.process.stdin.flush()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                line = self.out_queue.get(timeout=0.1)
                chunk, is_final = self._parse_line(line)
                if is_final:
                    self.finalized_chunks = [chunk] if chunk else []
                    self.current_partial = ""
                    self.last_is_final = True
                    return chunk.strip()
            except queue.Empty:
                if self.process.poll() is not None:
                    break
        return self.get_transcript()

    def reset(self) -> None:
        self.finalized_chunks = []
        self.current_partial = ""
        self.last_is_final = False
        while not self.out_queue.empty():
            try:
                self.out_queue.get_nowait()
            except queue.Empty:
                break
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(b"CMD:RESET".ljust(640, b"\x00"))
                self.process.stdin.flush()
                time.sleep(0.01)
            except Exception:
                pass
        while not self.out_queue.empty():
            try:
                self.out_queue.get_nowait()
            except queue.Empty:
                break
        self.finalized_chunks = []
        self.current_partial = ""

    def stop(self) -> None:
        self.stop_event.set()
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except Exception:
                pass
            try:
                if self.process.stdout:
                    self.process.stdout.close()
            except Exception:
                pass
            try:
                if self.process.stderr:
                    self.process.stderr.close()
            except Exception:
                pass
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=0.5)
        if self.stderr_thread and self.stderr_thread.is_alive():
            self.stderr_thread.join(timeout=0.5)
        self.reader_thread = None
        self.stderr_thread = None
