# Jarvis: Voice-First AI Project Lead & Desktop Orchestrator

Ultra-lightweight (< 45 MB host RSS) AI project lead and desktop orchestrator with a **Mike Ross** persona. Engineered for dual-core hardware with zero cloud downtime, bridging live streaming voice, native OS control, autonomous coding loops, and Google Tasks sync.

---

## Architecture

```
[Microphone]
     │
     ▼
[Dynamic VAD] ────────► [Streaming STT (Moonshine v2)]
(Context hangover,       (640-byte exact pipe, domain keyterms,
 anti-freeze guard)       live token preview)
                             │
                             ▼
                    [Brain Router]
     ┌───────────────────────┼───────────────────────┐
     ▼                       ▼                       ▼
Tier 1: Fast Action     Tier 2: Cloud LLM       Tier 3: Local SLM
 (Sub-10ms Native)     (Gemini Flash Lite 0.99s) (Qwen2.5-1.5B Offline)
 • Win32 Master Vol     • Spoken Sanitizer      • 100% Air-Gapped Fallback
 • Apps & Browser       • Tool Dispatching      • llama-server Runner
 • Google Tasks CRUD    • 3.5s Timeout Guard
 • Media & Search
     │                       │                       │
     └───────────────────────┼───────────────────────┘
                             │
                             ▼
                 [TTS Engine Dispatch]
             ├─► Kokoro-82M (Local ross.pt Voice Tensor)
             └─► Fish Audio (Cloud Low-Latency Stream)
```

---

## Core Capabilities

- **Sub-10ms Fast Actions**: Deterministic regex-routed system control (Windows CoreAudio master volume, application launching, web queries, task management) with zero LLM latency and zero token burn.
- **Spoken Output Sanitizer**: Delineates direct conversational speech from internal state/directives, eliminating prompt context and memory leaks.
- **Hybrid Brain with SLM Failover**: Primary cloud routing (`gemini-flash-lite-latest` ~0.99s) backed by offline quantized `Qwen2.5-1.5B-Instruct` served locally via embedded `llama-server`.
- **Edge Speech Recognition**: Streaming Moonshine v2 Medium over decoupled Windows IPC pipes, aligned to exact 640-byte PCM boundaries with domain keyterm biasing.
- **Context-Adaptive VAD**: Adaptive speech endpointing scaling from 600ms to 1400ms across short utterances and conjunction clauses, with stagnant text freeze detection.
- **Dual Neural TTS**: Offline low-latency Kokoro-82M audio chunk streaming using custom Mike Ross voice embeddings (`ross.pt`), paired with online Fish Audio streaming.
- **Zero-Model FTS5 Memory**: 4-tier persistent state, active personality directives, decayed facts, and BM25 conversation recall within a strict SQLite footprint.
- **Autonomous Lead Sync**: Reconciles git commits against Google Tasks, tracks blocker notes, and generates `NEXT_PLAN.md` across coding sessions.

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
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-flash-lite-latest
TTS_ENGINE=kokoro              # 'kokoro' (offline neural) or 'fish_audio' (cloud)
LOCAL_BRAIN_PORT=8088          # Local Qwen2.5 server port
```

### 3. Setup Local Brain & Models (Optional Offline Fallback)
```bash
python scripts/setup_local_brain.py
```

### 4. Run
- **Interactive Voice Loop**:
  ```bash
  python main.py
  # Press F9 to toggle Active / Standby
  # Press Ctrl+C to quit
  ```
- **CLI Commands**:
  ```bash
  python jarvis_cli.py --ask "what is on my agenda today"
  python jarvis_cli.py --sync-git --repo "."
  ```

---

## Project Lead Sync Hook

Integrate with your coding agent (`AGENTS.md` / `CLAUDE.md` / git hooks):

```bash
python "d:/path/to/jarvis-assistant/jarvis_cli.py" --agent-report "<1-sentence summary of completed milestone>" --repo "."
```

Automatically reconciles repository commits with Google Tasks ("Daily Agenda"), checks off finished items, appends progress notes, and updates `NEXT_PLAN.md`.

---

## Verification & Benchmarks

```bash
python -m pytest tests          # 77/77 passing
python benchmark_synthetic.py   # Active RSS < 45.0 MB (39.9 MB measured)
```
