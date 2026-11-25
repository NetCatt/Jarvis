# Jarvis: Voice-First AI Project Lead & Desktop Orchestrator

Ultra-lightweight (`< 45.0 MB` host RSS) AI project lead and desktop orchestrator with an authentic **Mike Ross** (*Suits*) persona. Combines sub-second **Groq `qwen/qwen3.8-27b` (`reasoning_effort=high`)** online routing, **Groq `whisper-large-v3-turbo`** STT with lazy offline Moonshine fallback, local **`Qwen3-1.7B-Q4_K_M`** offline high-reasoning fallback, Win64 OS automation, offline timers/web answers, deterministic safety guardrails, and Google Tasks sync.

---

## Architecture

```text
[Microphone: Non-Blocking RawInputStream Callback]
                        │
                        ▼
[80Hz High-Pass + Adaptive VAD] ──► [Groq-First STT Pipeline]
  (VAD_MODE=3, 100ms onset,          ├─► Online Primary: Groq whisper-large-v3-turbo (prompt-free)
   650 min RMS, 700ms pause,         ├─► Hallucination Filter: drops uncorroborated silence phantoms
   0.75s post-TTS echo guard)        └─► Offline / 429 Fallback: Lazy Moonshine v2 (medium-streaming-en)
                                                │
                                                ▼
                                         [Brain Router]
     ┌──────────────────────────────────────────┼──────────────────────────────────────────┐
     ▼                                          ▼                                          ▼
Tier 1: Fast Action                  Tier 2: Groq Cloud Brain               Tier 3: Offline SLM / Gemini
(Sub-5ms Shortcut)                   (qwen/qwen3.8-27b -> gpt-oss-20b)      (Qwen3-1.7B-Q4_K_M / Flash-Lite)
• Timers, Volume (<10ms)             • reasoning_effort=high, ~295ms        • -t 4 -c 4096 --reasoning on
• Spotify/YT Song & Track Title      • Native OpenAI Tool Calling           • --reasoning-budget 1024 (max 1536)
• Folders, Files, Agenda             • Full Spoken Explanations             • SQLite FTS5 Facts & Recall
     │                                          │                                          │
     └──────────────────────────────────────────┼─────────────────────────────┬────────────┘
                                                ▼                             ▼
                                     [Deterministic Safety Gate]   [OS & Daily Tools (`tools/`)]
                                     • Denylist Block (format,     • os_input (40B Win64 SendInput)
                                       regedit, del /s, taskkill)  • play_spotify (Ctrl+K + Green Play)
                                     • 6s Spoken Confirm           • daily (timers, wttr.in, math, DDG)
                                       (ctrl+w, alt+f4)            • os_context (SMTC, Window, RAM)
                                                │
                                                ▼
                      [Sentence-Chunked Async TTS + Opt-In Barge-In]
                      ├─► Fish Audio PCM Stream (carry-buffered, 30s timeout, F9 abort)
                      └─► Kokoro-82M / Windows SAPI Offline Fallback
```

---

## Core Capabilities

- **Groq-Primary Brain + High-Reasoning Offline `Qwen3-1.7B` (`brain.py`, `local_brain.py`)**:
  - `ROUTING_MODE=groq_hybrid` routes online turns to **`qwen/qwen3.8-27b`** (`reasoning_effort=high`, `max_tokens=1024`, native function calling) with **`openai/gpt-oss-20b`** and Gemini Flash-Lite backups.
  - When offline, `local_brain.py` lazily launches `Qwen_Qwen3-1.7B-Q4_K_M.gguf` via `llama-server.exe` (`-c 4096 -t 4 --reasoning on --reasoning-format deepseek --reasoning-budget 1024`, `max_tokens=1536`, `timeout=60s`).
- **Groq-First STT with Lazy Moonshine Fallback (`audio/stt.py`, `audio/moonshine_worker.py`)**:
  - Default `STT_ENGINE=groq` avoids local streaming CPU burn while online and omits static Whisper prompts to eliminate prompt-echo hallucinations; lazily starts Moonshine v2 (`medium-streaming-en`) only on network errors or Groq `429` limits.
- **80Hz High-Pass + Adaptive VAD & Full-Speech TTS (`audio/vad.py`, `audio/tts.py`, `main.py`)**:
  - Strips `<80Hz` fan/AC rumble before WebRTC VAD Mode 3 + RMS noise-floor adaptation (`VAD_MIN_RMS=650`, `VAD_ONSET_FRAMES=5`, `VAD_SILENCE_MS=700`, `VAD_MIN_SPEECH_FRAMES=12`).
  - `speak_async` streams Fish Audio sentence-by-sentence over a continuous `RawOutputStream` with odd-byte `carry` buffering so long explanations finish speaking uninterrupted (`ENABLE_BARGE_IN=0` default on speakers, `1` opt-in for headsets; `F9` aborts anytime).
- **Daily Utility & Reliable Spotify/Win64 Automation (`tools/`)**:
  - `tools/daily.py`: Offline countdown `set_timer` / `list_timers` / `cancel_timer` with chime + spoken alert, safe `ast` math evaluator, current time/date, live `wttr.in` weather, and DuckDuckGo instant facts.
  - `tools/os_input.py` & `tools/media.py`: True 40-byte 64-bit Win32 `SendInput` union structs, title-preserving Spotify queries (`DEFAULT_MUSIC_PLATFORM=spotify`), Win32 `AttachThreadInput` foreground focus, `Ctrl+K` `Shift+Enter`, and `#1ED760` green Play button pixel-centroid fallback verified via Windows SMTC (`now_playing`).
  - Deterministic safety gate (`tools/safety_gate.py`), SQLite FTS5 memory (`memory/`), and autonomous Git + Google Tasks sync (`tools/dev_sync.py`).

---

## Quickstart

### 1. Installation
```bash
git clone https://github.com/NetCatt/Jarvis.git
cd Jarvis/jarvis-assistant
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure Environment (`.env`)
```ini
GEMINI_API_KEY=your_google_ai_studio_key
GROQ_API_KEY=your_free_groq_key          # Powers whisper-large-v3-turbo STT + qwen/qwen3.8-27b brain
ROUTING_MODE=groq_hybrid                 # 'groq_hybrid' or 'local'
GROQ_BRAIN_MODEL=qwen/qwen3.8-27b
GROQ_BRAIN_FALLBACK=openai/gpt-oss-20b
GROQ_REASONING_EFFORT=high
LOCAL_BRAIN_THREADS=4
LOCAL_BRAIN_CTX=4096
LOCAL_BRAIN_REASONING=on
LOCAL_BRAIN_REASONING_BUDGET=1024
LOCAL_BRAIN_MAX_TOKENS=1536
STT_ENGINE=groq                          # 'groq' (Groq + lazy Moonshine offline fallback), 'hybrid', or 'moonshine'
VAD_MODE=3
VAD_SILENCE_MS=700
VAD_MIN_RMS=650
VAD_ONSET_FRAMES=5
VAD_MIN_SPEECH_FRAMES=12
ENABLE_BARGE_IN=0                        # Set 1 with headsets to enable voice barge-in during TTS
DEFAULT_MUSIC_PLATFORM=spotify
TTS_ENGINE=fish_audio
```

### 3. Setup Local Brain (`Qwen3-1.7B-Q4_K_M`)
```bash
python scripts/setup_local_brain.py qwen3
```

### 4. Run
- **Interactive Voice Loop**:
  ```bash
  run_mike.bat
  # or: python main.py
  # Press F9 to toggle Active / Standby (also stops current speech), Ctrl+C to quit
  ```
- **CLI Commands**:
  ```bash
  python jarvis_cli.py --ask "what is on my agenda today"
  python jarvis_cli.py --sync-git --repo "."
  ```

---

## Project Lead Sync Hook

```bash
python "d:/path/to/jarvis-assistant/jarvis_cli.py" --agent-report "<1-sentence summary of completed milestone>" --repo "."
```

Automatically reconciles repository commits with Google Tasks ("Daily Agenda"), checks off finished items, appends progress notes, and updates `NEXT_PLAN.md`.

---

## Verification & Benchmarks

```bash
python -m pytest tests -q       # 104/104 passing
python benchmark_synthetic.py   # 6/6 PASS | Final Process RSS: 40.81 MB (< 45.0 MB) | 0.0% comments
```
