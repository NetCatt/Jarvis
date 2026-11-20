import collections
import webrtcvad

class DynamicVoiceEndpoint:
    def __init__(self, sample_rate: int = 16000, frame_ms: int = 20, vad_mode: int = 1, stop_phrase: str = "over"):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.vad_mode = vad_mode
        self.stop_phrase = stop_phrase.strip().lower() if stop_phrase else ""
        self.vad = webrtcvad.Vad(self.vad_mode)
        self.expected_frame_len = int(self.sample_rate * (self.frame_ms / 1000) * 2)
        self.hangover_buffer = collections.deque(maxlen=12)
        self.silence_ms = 0
        self.stagnant_ms = 0
        self.last_text = ""
        self.triggered = False
        self.conjunctions = {
            "and", "or", "to", "because", "with", "but", "so", "that", "if",
            "when", "while", "then", "since", "as", "like", "for",
        }

    def reset(self) -> None:
        self.hangover_buffer.clear()
        self.silence_ms = 0
        self.stagnant_ms = 0
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

    def process_frame(self, pcm_frame: bytes, current_transcript: str = "") -> tuple[bool, bool]:
        if len(pcm_frame) < self.expected_frame_len:
            pcm_frame = pcm_frame.ljust(self.expected_frame_len, b"\x00")
        elif len(pcm_frame) > self.expected_frame_len:
            pcm_frame = pcm_frame[:self.expected_frame_len]
        raw_speech = self.vad.is_speech(pcm_frame, self.sample_rate)
        self.hangover_buffer.append(raw_speech)
        ratio = sum(self.hangover_buffer) / len(self.hangover_buffer)
        smoothed_speech = ratio >= 0.35
        clean_text = current_transcript.rstrip(" .,!?").lower() if current_transcript else ""
        if self.stop_phrase and (clean_text == self.stop_phrase or clean_text.endswith(" " + self.stop_phrase)):
            return smoothed_speech, True
        if not self.triggered:
            if raw_speech or (clean_text and len(clean_text) > 0):
                self.triggered = True
                self.silence_ms = 0
                self.stagnant_ms = 0
                self.last_text = clean_text
            else:
                return False, False
        words = clean_text.split() if clean_text else []
        last_word = words[-1].rstrip(" .,!?") if words else ""
        if last_word in self.conjunctions:
            threshold_ms = 1400
        elif len(words) < 3:
            threshold_ms = 1200
        else:
            threshold_ms = 800
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
