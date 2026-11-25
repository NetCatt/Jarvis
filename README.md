# Jarvis: Voice-First AI Project Lead & Desktop Orchestrator

Ultra-lightweight (`< 45.0 MB` host RSS) AI project lead and desktop orchestrator with an authentic **Mike Ross** (*Suits*) persona. Engineered for dual-core laptops with non-blocking voice streaming, hybrid accented STT, local `Qwen3-1.7B` reasoning, universal Win32 OS primitives, deterministic safety guardrails, and Google Tasks sync.

---

## Architecture

```text
[Microphone: Non-Blocking RawInputStream Callback]
                        │
                        ▼
[Adaptive Noise-Floor VAD] ──► [Hybrid STT Pipeline]
  (VAD_MODE=3, RMS floor,       ├─► Live UI: Moonshine v2 medium-streaming-en (~150ms partials)
   60ms onset, 12s cap,         ├─► Online Free: Groq whisper-large-v3-turbo (0.39s RTT)
   250ms post-TTS guard)        ├─► Online Fallback: Gemini Flash-Lite inline WAV
                                └─► Offline Fallback: Moonshine non-streaming (0.69s)
                                          │
                                          ▼
                                   [Brain Router]
     ┌────────────────────────────────────┼────────────────────────────────────┐
     ▼                                    ▼                                    ▼
Tier 1: Fast Action               Tier 2: Local SLM                    Tier 3: Cloud LLM
(Sub-5ms Shortcut)                (Qwen3-1.7B-Q4_K_M)                  (Gemini Flash-Lite)
• CoreAudio Volume (<10ms)        • --reasoning off / budget 0         • Multi-step Planning
• Media Keys & Windows SMTC       • SQLite FTS5 Facts & Recall         • Chainable Inspection
• Folders, Files, Agenda          • Mike Ross Suits Persona            • Agent Dispatch
     │                                    │                                    │
     └────────────────────────────────────┼───────────────────────┬────────────┘
                                          ▼                       ▼
                               [Deterministic Safety Gate]   [Universal OS Primitives]
                               • Denylist Block (format,     • os_input (ctypes SendInput)
                                 regedit, del /s, taskkill)  • os_launch (URIs & Apps)
                               • 6s Spoken Confirm           • web_dispatch (Multi-Engine)
                                 (ctrl+w, alt+f4)            • os_context (SMTC, Window, RAM)
                                          │
                                          ▼
                        [TTS Dispatch + Half-Duplex Lock]
                        ├─► Fish Audio (Cloud Stream)
                        └─► Kokoro-82M (Persistent WASAPI Stream, ross.pt)
```

---

## Core Capabilities

- **Hybrid Accented STT (`audio/stt.py`, `audio/moonshine_worker.py`)**: Live terminal token preview via cached `Moonshine v2` (`medium-streaming-en`), paired with zero-CPU-load **Groq Free Tier `whisper-large-v3-turbo`** (`0.39s` RTT) and Gemini inline WAV / offline Moonshine (`0.69s`) fallbacks. Filters Whisper silence hallucinations via `verbose_json` `no_speech_prob` and minimum active speech gating.
- **Adaptive Noise-Floor VAD & Lock-Free Capture (`audio/vad.py`, `main.py`)**: WebRTC VAD Mode 3 combined with a pure-Python adaptive RMS noise floor (`VAD_MIN_RMS`), 60ms speech-onset debouncing, 12s max duration cap, and continuous non-blocking `RawInputStream` callbacks (zero per-turn WASAPI restarts).
- **Local `Qwen3-1.7B` Engine (`local_brain.py`)**: Serves `Qwen_Qwen3-1.7B-Q4_K_M.gguf` via `llama-server.exe` tuned for 2-core CPUs (`-c 1024 -b 512 -ub 256 -t 2 -fa on --parallel 1 --reasoning off --reasoning-budget 0`) with KV-prefix caching and SQLite fact/memory injection.
- **5 Universal OS Primitives (`tools/`)**: Pure Win32 `ctypes` / WinRT control with zero extra pip dependencies:
  - `os_input`: Hardware media keys (`playpause`, `nexttrack`, `prevtrack`), hotkeys (`ctrl+w`, `alt+tab`), and Unicode `SendInput`.
  - `os_launch`: Protocol URIs (`spotify:`, `ms-settings:`), executables, and Start Menu launch.
  - `web_dispatch`: Multi-engine web search (`google`, `youtube`, `spotify`, `github`, `reddit`) and direct URLs.
  - `os_context`: Windows 11 SMTC `now_playing` (Spotify/browser track, artist, playback state even when minimized), `active_window`, `clipboard`, and `system_stats`.
  - `existing_core`: Sub-10ms Win32 CoreAudio volume controls, `open_folder`, `search_files`, safe `run_terminal`, and Google Tasks.
- **Deterministic Safety Gate (`tools/safety_gate.py`)**: Blocks destructive commands (`format`, `del /s`, `rmdir /s`, `regedit`, `diskpart`, `shutdown`, `taskkill`, `powershell -enc`) and enforces a 6.0s spoken confirmation gate for high-risk hotkeys (`ctrl+w`, `alt+f4`).
- **Half-Duplex TTS Contention Guard (`audio/tts.py`, `audio/kokoro_worker.py`)**: Persistent WASAPI `OutputStream` in Kokoro-82M paired with `is_speaking()` mic gating to stop thread thrashing and self-echo.
- **Zero-Model FTS5 Memory & Autonomous Lead Sync**: Persistent SQLite state, facts, and BM25 recall (`memory/`), plus Google Tasks reconciliation and `NEXT_PLAN.md` generation (`tools/dev_sync.py`).

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
GROQ_API_KEY=your_free_groq_key          # Free tier (console.groq.com), powers 0.39s whisper-large-v3-turbo
STT_ENGINE=hybrid                        # 'hybrid' (Groq + Moonshine fallback) or 'moonshine' (100% offline)
VAD_MODE=3
VAD_SILENCE_MS=550
VAD_MIN_RMS=260
VAD_MAX_DURATION_SEC=12
ROUTING_MODE=hybrid
LOCAL_BRAIN_PORT=8088
TTS_ENGINE=fish_audio                    # 'fish_audio' or 'kokoro'
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
  # Press F9 to toggle Active / Standby, Ctrl+C to quit
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
python -m pytest tests -q       # 96/96 passing
python benchmark_synthetic.py   # 6/6 PASS | Active RSS: 40.59 MB (< 45.0 MB) | 0.0% comments
```
