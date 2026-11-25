import array
import collections
import math
import os
import webrtcvad

def frame_rms(pcm_frame: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm_frame)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))

class DynamicVoiceEndpoint:
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 20,
        vad_mode: int = 2,
        stop_phrase: str = "over",
        base_silence_ms: int = 800,
        max_duration_sec: float = None,
        onset_frames: int = 3,
    ):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.vad_mode = vad_mode
        self.stop_phrase = stop_phrase.strip().lower() if stop_phrase else ""
        self.base_silence_ms = int(base_silence_ms)
        self.onset_frames = max(1, int(onset_frames))
        self.vad = webrtcvad.Vad(self.vad_mode)
        self.expected_frame_len = int(self.sample_rate * (self.frame_ms / 1000) * 2)
        self.hangover_buffer = collections.deque(maxlen=12)
        self.silence_ms = 0
        self.stagnant_ms = 0
        self.speech_ms = 0
        self.consecutive_speech = 0
        self.active_speech_frames = 0
        self.last_text = ""
        self.triggered = False
        self.noise_floor = 0.0
        self._hp_prev_x = 0.0
        self._hp_prev_y = 0.0
        self.min_rms = float(os.getenv("VAD_MIN_RMS", "120"))
        cap_sec = max_duration_sec if max_duration_sec is not None else float(os.getenv("VAD_MAX_DURATION_SEC", "12"))
        self.max_duration_ms = int(cap_sec * 1000)
        self.conjunctions = {
            "and", "or", "to", "because", "with", "but", "so", "that", "if",
            "when", "while", "then", "since", "as", "like", "for",
        }

    def reset(self) -> None:
        self.hangover_buffer.clear()
        self.silence_ms = 0
        self.stagnant_ms = 0
        self.speech_ms = 0
        self.consecutive_speech = 0
        self.active_speech_frames = 0
        self.last_text = ""
        self.triggered = False

    def strip_stop_phrase(self, text: str) -> str:
        if not self.stop_phrase or not text:
            return text
        stripped = text.rstrip(" .,!?")
        lower = stripped.lower()
        if lower == self.stop_phrase:
            return ""
        if lower.endswith(" " + self.stop_phrase):
            return stripped[: len(stripped) - len(self.stop_phrase)].rstrip(" .,!?")
        return text

    def _frame_rms(self, pcm_frame: bytes) -> float:
        return frame_rms(pcm_frame)

    def _highpass_frame(self, pcm_frame: bytes) -> bytes:
        samples = array.array("h")
        samples.frombytes(pcm_frame)
        if not samples:
            return pcm_frame
        px, py = self._hp_prev_x, self._hp_prev_y
        out = array.array("h")
        for x in samples:
            y = 0.955 * (py + x - px)
            px = x
            py = y
            iv = int(y)
            if iv > 32767:
                iv = 32767
            elif iv < -32768:
                iv = -32768
            out.append(iv)
        self._hp_prev_x, self._hp_prev_y = px, py
        return out.tobytes()

    def process_frame(self, pcm_frame: bytes, current_transcript: str = "") -> tuple[bool, bool]:
        if len(pcm_frame) < self.expected_frame_len:
            pcm_frame = pcm_frame.ljust(self.expected_frame_len, b"\x00")
        elif len(pcm_frame) > self.expected_frame_len:
            pcm_frame = pcm_frame[:self.expected_frame_len]
        filtered_frame = self._highpass_frame(pcm_frame)
        rms = frame_rms(filtered_frame)
        vad_speech = self.vad.is_speech(filtered_frame, self.sample_rate)
        if not self.triggered and (not vad_speech or rms < max(self.min_rms, self.noise_floor * 2.0)):
            alpha = 0.06 if (not vad_speech or self.noise_floor > 0.0) else 0.15
            self.noise_floor = (1.0 - alpha) * self.noise_floor + alpha * rms
        raw_speech = vad_speech and (rms >= max(self.min_rms, self.noise_floor * 2.2))
        self.hangover_buffer.append(raw_speech)
        ratio = sum(self.hangover_buffer) / len(self.hangover_buffer)
        smoothed_speech = ratio >= 0.35
        clean_text = current_transcript.rstrip(" .,!?").lower() if current_transcript else ""
        if self.stop_phrase and (clean_text == self.stop_phrase or clean_text.endswith(" " + self.stop_phrase)):
            return smoothed_speech, True
        if not self.triggered:
            self.consecutive_speech = (self.consecutive_speech + 1) if raw_speech else 0
            if self.consecutive_speech >= self.onset_frames or (clean_text and len(clean_text) > 0):
                self.triggered = True
                self.silence_ms = 0
                self.stagnant_ms = 0
                self.speech_ms = 0
                self.active_speech_frames = max(self.consecutive_speech, 1 if raw_speech else 0)
                self.last_text = clean_text
            else:
                return False, False
        elif raw_speech:
            self.active_speech_frames += 1
        self.speech_ms += self.frame_ms
        if self.speech_ms >= self.max_duration_ms:
            return smoothed_speech, True
        words = clean_text.split() if clean_text else []
        last_word = words[-1].rstrip(" .,!?") if words else ""
        if last_word in self.conjunctions:
            threshold_ms = max(self.base_silence_ms + 600, 1400)
        elif 0 < len(words) < 3:
            threshold_ms = max(self.base_silence_ms + 400, 1200)
        else:
            threshold_ms = self.base_silence_ms
        if clean_text and clean_text == self.last_text:
            self.stagnant_ms += self.frame_ms
        else:
            self.last_text = clean_text
            self.stagnant_ms = 0
        if smoothed_speech:
            self.silence_ms = 0
        else:
            self.silence_ms += self.frame_ms
        if self.silence_ms >= threshold_ms or (words and smoothed_speech and self.stagnant_ms >= threshold_ms + 600):
            return smoothed_speech, True
        return smoothed_speech, False
