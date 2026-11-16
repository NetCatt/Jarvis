# Jarvis / Mike Ross: AI Project Lead & Local Desktop Orchestrator

Jarvis (configured as "Mike Ross") is a modular Python technical project lead and voice orchestrator for solo developers working with autonomous coding agents (Claude Code, Gemini) on resource-conscious hardware.

Mike holds real stateful, multi-turn conversations (not one-shot commands), backed by a three-tier local memory system (working state, durable facts with confidence/decay, embedding-based episodic recall). He bridges local Git workspaces with Google Tasks across multiple lists (not just one "Daily Agenda") — inspecting code changes and agent completion summaries, reconciling them with your tasks, scheduling new ones with due dates, and writing structured next-phase plans (`NEXT_PLAN.md`) for coding agents to execute. He can also dispatch real engineering/architecture work to the Claude Code CLI (`ml-engineer` / `architect` agents) instead of trying to do it himself.

## Hardware Resource Budget

- Deterministic one-shot commands (tasks, apps, media) keep a near-zero RAM fast path — no memory/embedding overhead.
- The full conversational path with offline STT (`vosk-model-en-us-0.22-lgraph`) and episodic embeddings (`model2vec`) both loaded runs ~460 MB RSS (measured). This is a deliberate trade-off versus the old cloud-STT approach (near-zero RAM, but unreliable and network-dependent) — on an 8GB machine this is negligible in absolute terms. A smaller Vosk model (~236 MB total) is available if RAM ever becomes a real constraint; the larger one was chosen for meaningfully better transcription accuracy.
- Zero Background Watchers: no `watchdog` daemons. Git repositories are inspected on-demand via bounded subprocesses (`timeout=3.0s`).
- Compute Offloading: Mike's own reasoning/routing runs via Google AI Studio Free Tier (Gemini Flash, with fallback). Claude Code CLI dispatch is only invoked for real engineering tasks and costs real API dollars, capped per call.
- Banned/avoided: `torch`, `onnxruntime` (for the offline STT path), `pygame`, `watchdog` daemons.

## Architecture

```
Trigger (CLI / Git Hook / Voice)
  -> Voice capture: webrtcvad-gated recording -> offline English-only STT (vosk)
  -> Speaker verification (voiceprint, or local hotkey/CLI)
  -> Memory assembly: working state + durable facts + episodic recall (SQLite, memory/)
  -> Gemini Flash conversation/routing (brain.converse) -> deterministic tool, or
     dispatch_coding_agent (Claude Code CLI, headless) for real engineering tasks
  -> Memory persistence (turn + extracted facts/state; compaction & decay run automatically)
  -> Google Tasks mutation (multi-list, due dates) & NEXT_PLAN.md generation
  -> Webhook standup notification (Discord / Slack / Telegram)
  -> Audio Output (Fish Audio Ross clone / Windows SAPI)
```

Voice capture starts/stops on actual detected speech (`webrtcvad`) instead of a fixed-duration clip, and transcribes fully offline and English-only via `vosk` — no cloud STT quota/reliability dependency, and structurally unable to mis-transcribe into another language.

## Directory Structure

```
jarvis-assistant/
├── AGENTS.md               # Architectural specification & agent handoff rules
├── .env.example            # Configuration template (zero secrets committed)
├── .gitignore              # Ignores .env, data/, *.mp3, models/, etc.
├── requirements.txt        # Pinned dependencies
├── run_mike.bat            # Double-click launcher for the voice loop
├── enroll_voice.py         # 5-second offline spectral voiceprint enrollment
├── voice_gate.py           # Speaker verification & hotkey toggles
├── brain.py                # Gemini Flash stateful multi-turn conversation (brain.converse)
├── jarvis_cli.py           # CLI entry point: --ask, --sync-git, --agent-report, --reflect, --recall
├── main.py                 # Always-on voice loop: VAD capture, offline STT, TTS
├── data/                   # Secrets & runtime state (gitignored): credentials.json, token.json,
│                            #   local_tasks.json, faisal.voice.npy, memory.db
├── models/                 # Offline STT model (gitignored, downloaded separately)
├── memory/                 # Three-tier memory: working state / durable facts / episodic recall
│   ├── store.py            # SQLite schema + CRUD (WAL mode)
│   ├── embeddings.py       # model2vec static embeddings (NumPy-only inference)
│   └── retrieval.py        # Cosine-ranked episodic recall
└── tools/
    ├── __init__.py         # Tool registry and dispatch map
    ├── llm.py              # Shared Gemini call-with-fallback helper
    ├── tasks.py            # Google Tasks CRUD, multi-list, due dates, offline fallback
    ├── dispatch.py         # Headless Claude Code CLI agent dispatch (ml-engineer/architect)
    ├── dev_sync.py         # Git diff/log inspection & Gemini task reconciler
    ├── planner.py          # NEXT_PLAN.md specification generator for coding agents
    ├── notify.py           # Zero-dependency webhook standup dispatcher
    ├── apps.py             # Windows desktop application launcher
    └── media.py            # YouTube and Spotify focus media controllers
```

## Setup & Installation

### 1. Prerequisites

- Windows 10 or 11 (64-bit)
- Python 3.10+
- Git for Windows

### 2. Install Dependencies

```bash
cd jarvis-assistant
pip install -r requirements.txt
```

### 3. Environment Configuration

Copy `.env.example` to `.env` inside `jarvis-assistant/`:

```bash
cp .env.example .env
```

Configure the following variables in `.env` (see `.env.example` for the full annotated list):

```ini
# LLM Configuration (Google AI Studio Free Tier)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite

# Assistant Identity
ASSISTANT_NAME=Mike Ross
ASSISTANT_NICKNAME=Mike
USER_NAME=Fas

# Speech & Audio
TTS_ENGINE=fish_audio          # Strictly custom cloned voice: Ross
TTS_VOICE=ross
FISH_AUDIO_KEY=your_key        # Fish Audio API key for Ross clone
FISH_AUDIO_MODEL_ID=model_id   # Fish Audio model reference ID (Ross)

# Offline Voice Capture (VAD + Vosk, English-only STT)
VOSK_MODEL_PATH=models/vosk-model-small-en-us-0.15
VAD_MODE=1                     # 0-3, lower = more lenient (fewer false "silence" cutoffs mid-sentence)
VAD_MAX_DURATION_SEC=120        # safety backstop once speech starts, not a real conversational limit

# Memory (three-tier)
MEMORY_DB_PATH=data/memory.db
EMBEDDING_MODEL=minishlab/potion-base-8M

# Agent Dispatch (Claude Code CLI, headless, real API cost per call)
AGENT_DISPATCH_MAX_BUDGET_USD=1.00

# Google Tasks
GOOGLE_TASKS_LIST_NAME=Daily Agenda
GOOGLE_CREDENTIALS_FILE=data/credentials.json
GOOGLE_TOKEN_FILE=data/token.json

# Webhook Notifications (Optional)
WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 4. Google Tasks Authentication

1. Go to Google Cloud Console and create a project.
2. Enable the **Google Tasks API**.
3. Create an **OAuth 2.0 Client ID** with Application Type set to **Desktop app**.
4. Download the client JSON file and save it as `jarvis-assistant/data/credentials.json` (create the `data/` folder if it doesn't exist yet).
5. Run the authentication setup once to generate `data/token.json`:
```bash
python auth_setup.py
```
*Note: If `data/credentials.json` is not present, the system automatically falls back to `data/local_tasks.json`, remaining 100% operational offline.*

### 5. Offline Voice Model (one-time download, ~130MB)

```bash
cd jarvis-assistant
curl -L -o models/vosk-model-en-us-0.22-lgraph.zip https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip
unzip models/vosk-model-en-us-0.22-lgraph.zip -d models/
rm models/vosk-model-en-us-0.22-lgraph.zip
```

If RAM is tight on your machine, `vosk-model-small-en-us-0.15` (~41MB download, ~236MB RSS vs. ~460MB for the lgraph model above) is a smaller/less accurate alternative — download it the same way and point `VOSK_MODEL_PATH` at it instead.

### 6. Speaker Recognition Setup (Optional)

To ensure the voice assistant only responds to your voice:

```bash
python enroll_voice.py
```

Speak for 5 seconds into your microphone when prompted. The script computes a 64-band normalized FFT voiceprint and saves `data/faisal.voice.npy`. The voice loop verifies incoming audio against this profile.

## Usage

### Command Line Interface

All commands run via `python jarvis_cli.py` from `jarvis-assistant/` (there's no separate `mike` executable — add a shell alias/doskey if you want one).

Hold a real multi-turn conversation — context carries across calls in the same `--session` (default: a persistent `"default"` session, so day-to-day CLI usage accumulates memory too):
```bash
python jarvis_cli.py --ask "what is my agenda"
python jarvis_cli.py --ask "search Google for python 3.14 features"
python jarvis_cli.py --ask "open browser"
python jarvis_cli.py --ask "open vscode"
```

Tasks — not limited to one list, with due-date scheduling and a today-only briefing:
```bash
python jarvis_cli.py --ask "add task implement redis caching to my agenda"
python jarvis_cli.py --ask "remind me to renew car insurance tomorrow"
python jarvis_cli.py --ask "create a task list called Groceries"
python jarvis_cli.py --ask "add milk and eggs to my Groceries list"
python jarvis_cli.py --ask "what's on my agenda today"
```

Dispatch real engineering/architecture work to the Claude Code CLI instead of Mike trying to do it himself (costs real API dollars, capped by `AGENT_DISPATCH_MAX_BUDGET_USD`):
```bash
python jarvis_cli.py --ask "have the ml-engineer refactor the training pipeline in my-project for batching"
```

Interactive music routing (Spotify vs. YouTube):
```bash
# Requesting music without specifying platform prompts for preference:
python jarvis_cli.py --ask "play Bohemian Rhapsody"
# Response: "Would you like to play Bohemian Rhapsody on Spotify or YouTube, Fas?"

# Follow up with platform:
python jarvis_cli.py --ask "Spotify"     # Opens native Spotify app and searches query
python jarvis_cli.py --ask "on YouTube"  # Opens YouTube search in default browser
```

Sync coding progress manually for any project:
```bash
python jarvis_cli.py --sync-git --repo "D:/path/to/project"
```

Memory debug and manual upkeep (compaction/decay otherwise run automatically):
```bash
python jarvis_cli.py --recall "what do you know about my preferences"
python jarvis_cli.py --reflect
```

Run silently (without spoken audio output):
```bash
python jarvis_cli.py --ask "what is my agenda" --silent
```

### Always-On Voice Assistant

Double-click `run_mike.bat` — no terminal or IDE needed. (Or run `python main.py` directly.)

- Speaks a personalized greeting on startup.
- Captures speech on actual detected speech (VAD-gated, not a fixed-duration clip), transcribes fully offline and English-only (`vosk`), verifies speaker identity, and holds one continuous multi-turn conversation for the life of the process.
- Press `F9` at any time to toggle between **Active** and **Standby** modes without quitting the process.
- Press `Ctrl + C` in the terminal to stop.

## Coding Agent Integration

Jarvis is designed to act as an automated Project Lead tethered to coding agents across all your IDEs.

### Claude in VS Code

Create or update `CLAUDE.md` in your project root (or globally at `~/.claude/CLAUDE.md`):

```markdown
## Automated Project Lead Sync (Mike Ross Hook)
- Before writing code, inspect `NEXT_PLAN.md` in the repository root if present.
- Whenever you finish an implementation step, milestone, refactor, or bugfix in this codebase, execute:
  ```bash
  python "D:/path/to/jarvis-assistant/jarvis_cli.py" --agent-report "<concise summary of completed work and files touched>" --repo "."
  ```
- This automatically reconciles code changes against Google Tasks ("Daily Agenda"), checks off finished tasks, appends progress notes, and updates `NEXT_PLAN.md` for your next session.
- Task titles/notes must be short, meaningful, human-readable descriptions of what was done — never a commit hash or opaque ID.
```

### Antigravity IDE (Gemini)

Add the directive to your workspace rules or `AGENTS.md`:

```markdown
## Automated Project Lead Sync
Whenever you finish an implementation task, run:
python "D:/path/to/jarvis-assistant/jarvis_cli.py" --agent-report "<summary of changes>" --repo "."
```

### Automated Git Post-Commit Hook

To have every `git commit` in any repository automatically update your Google Tasks, install the hook:

```bash
# In your target repository:
# .git/hooks/post-commit
#!/bin/sh
python "D:/path/to/jarvis-assistant/jarvis_cli.py" --sync-git --repo "$(pwd)" --silent &
```

Or configure globally across all git repositories:
```bash
git config --global core.hooksPath "C:/Users/Faisal/.git_hooks"
```

## Security & Secrets

All API keys, OAuth tokens, voice profiles, and memory are strictly excluded from version control via `.gitignore` — none of this has ever been committed:
- `.env` (real keys/config — only `.env.example`, a placeholder template, is tracked)
- `jarvis-assistant/data/` (`credentials.json`, `token.json`, `local_tasks.json`, `faisal.voice.npy`, `memory.db`)
- `jarvis-assistant/models/` (downloaded offline STT model)
- `*.mp3`

Use `jarvis-assistant/.env.example` as the clean configuration template — copy it to `.env` and fill in your own values; never commit the real `.env`.
