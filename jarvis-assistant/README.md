# Jarvis: Voice-First AI Project Lead & Desktop Orchestrator

Ultra-lightweight (< 45 MB RSS) AI assistant and technical project lead with a **Mike Ross** persona. Bridges live voice, local system orchestration, autonomous coding agent loops, and Google Tasks sync with zero cloud downtime.

---

## Key Features

- **Sub-50ms Fast-Path**: Instant deterministic execution for apps, media, web, and task mutations without LLM token burn.
- **Hybrid Brain**: Primary fast cloud inference (`gemini-flash-lite-latest` ~0.99s) with automatic failover to local offline SLM (`Qwen2.5-1.5B-Instruct` via `llama-server.exe`).
- **Edge Speech-to-Text**: Low-latency Moonshine v2 Medium streaming with domain vocabulary conditioning and syntax-aware VAD hangover.
- **Dual Voice Synthesis**: High-fidelity online Fish Audio streaming clone paired with local offline Kokoro-82M neural TTS (`ross.pt` voice tensor).
- **Automated Lead Sync**: Reconciles Git commits with Google Tasks, tracking progress and updating `NEXT_PLAN.md` across sessions.
- **Zero-Model FTS5 Memory**: 4-tier persistent state, facts, and episodic conversation recall within a strict hardware budget.

---

## Architecture

```
[Microphone] ──► Silero/WebRTC VAD ──► Moonshine v2 STT
                                             │
                                             ▼
                                     [Brain Router]
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
           Tier 1: Fast Action      Tier 2: Cloud LLM        Tier 3: Local SLM
             (Sub-50ms Native)     (Gemini Flash Lite 0.99s)   (Qwen2.5-1.5B Offline)
                    │                        │                        │
                    └────────────────────────┼────────────────────────┘
                                             ▼
                                  [TTS Engine Dispatch]
                                     ├─► Fish Audio (Cloud Stream)
                                     └─► Kokoro-82M (Local ross.pt)
```

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
TTS_ENGINE=fish_audio          # or 'kokoro' for 100% offline TTS
FISH_AUDIO_KEY=your_fish_key
FISH_AUDIO_MODEL_ID=your_model_id
```

### 3. Setup Local Brain & Models (Optional Offline Fallback)
```bash
python scripts/setup_local_brain.py
```

### 4. Run
- **Interactive Voice Loop**:
  ```bash
  python main.py
  # Toggle Active/Standby with F9
  ```
- **CLI Commands**:
  ```bash
  python jarvis_cli.py --ask "what is on my agenda today"
  python jarvis_cli.py --sync-git --repo "."
  ```

---

## Autonomous Agent Hook

Add to your project's `AGENTS.md` or `CLAUDE.md`:

```bash
python "/path/to/jarvis-assistant/jarvis_cli.py" --agent-report "<1-sentence summary of changes>" --repo "."
```
Reconciles completed code changes with Google Tasks ("Daily Agenda"), checks off finished items, and generates `NEXT_PLAN.md` for the next session.

---

## Verification & Benchmarks

```bash
python -m pytest tests          # 75/75 passing
python benchmark_synthetic.py   # Hardware RSS < 45.0 MB verified
```
