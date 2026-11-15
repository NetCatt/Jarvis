# Jarvis / Mike Ross: AI Project Lead & Local Desktop Orchestrator

Jarvis (configured as "Mike Ross") is a modular, low-resource Python technical project lead and voice orchestrator built for solo developers working with autonomous coding agents (Claude in VS Code, Gemini in Antigravity) on resource-constrained hardware.

The system bridges local Git workspaces with Google Tasks ("Daily Agenda"). It inspects active code changes, commits, and agent completion summaries, reconciles them with your task agenda, ticks off finished work, updates progress notes, and writes structured next-phase plans (`NEXT_PLAN.md`) for coding agents to execute.

## Hardware Resource Budget

Designed to operate on memory-constrained systems (e.g., dual-core Intel Core i3 with under 1 GB available physical RAM) without competing with IDEs, browser tabs, or development servers:

- Target Resident Memory (RSS): Under 45 MB RAM
- Zero Background Watchers: No `watchdog` daemons indexing `node_modules` or `.venv`. Git repositories are inspected on-demand via bounded subprocesses (`timeout=3.0s`).
- Compute Offloading: Reasoning runs via Google AI Studio Free Tier (`gemini-3.8-flash` with automatic fallback to `gemini-3.5-flash-lite` and `gemini-2.5-flash`).
- Audio I/O: Native Windows `winmm.dll` MCI audio playback, lightweight `sounddevice` capture, and sub-2ms NumPy FFT voiceprint verification.

## Architecture

The runtime follows a strict linear execution flow:

```
Trigger (CLI / Git Hook / Voice)
  -> Input Verification (Voiceprint matching or CLI args)
  -> Workspace Context Collection (git status -s, git log -n 3, git diff --stat)
  -> Task Agenda Fetch (Google Tasks API / local fallback)
  -> Gemini Flash Reconciliation (Strict JSON Decision)
  -> State Mutation:
     - Mark completed tasks in Google Tasks
     - Append timestamped progress notes to in-progress tasks
     - Write NEXT_PLAN.md in target repo root
     - Dispatch webhook standup report (Discord / Slack / Telegram)
  -> Audio Output (Fish Audio clone / Edge-TTS / Windows SAPI)
```

## Directory Structure

```
jarvis-assistant/
├── AGENTS.md               # Architectural specification & agent handoff rules
├── .env.example            # Configuration template (zero secrets committed)
├── .gitignore              # Ignores .env, credentials.json, token.json, *.voice, etc.
├── requirements.txt        # Pinned lightweight dependencies
├── enroll_voice.py         # 5-second offline spectral voiceprint enrollment
├── voice_gate.py           # Sub-2ms speaker verification & hotkey toggles
├── brain.py                # Gemini Flash single-turn function-calling router
├── jarvis_cli.py           # Global CLI entry point for agents, git hooks, and terminal
├── main.py                 # Always-on voice loop with sounddevice + TTS
└── tools/
    ├── __init__.py         # Tool registry and dispatch map
    ├── tasks.py            # Google Tasks CRUD with offline local_tasks.json fallback
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

Configure the following variables in `.env`:

```ini
# LLM Configuration (Google AI Studio Free Tier)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite

# Assistant Identity
ASSISTANT_NAME=Mike Ross
ASSISTANT_NICKNAME=Mike
USER_NAME=Fas

# Speech & Audio
TTS_ENGINE=fish_audio          # Options: fish_audio, edge_tts
TTS_VOICE=en-GB-RyanNeural     # Edge TTS voice identifier
FISH_AUDIO_KEY=your_key        # Optional: Fish Audio API key for custom clone
FISH_AUDIO_MODEL_ID=model_id   # Optional: Fish Audio model reference ID

# Google Tasks
GOOGLE_TASKS_LIST_NAME=Daily Agenda
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json

# Webhook Notifications (Optional)
WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 4. Google Tasks Authentication

1. Go to Google Cloud Console and create a project.
2. Enable the **Google Tasks API**.
3. Create an **OAuth 2.0 Client ID** with Application Type set to **Desktop app**.
4. Download the client JSON file and save it as `jarvis-assistant/credentials.json`.
5. Run the authentication setup once to generate `token.json`:
```bash
python auth_setup.py
```
*Note: If credentials.json is not present, the system automatically falls back to `local_tasks.json`, remaining 100% operational offline.*

### 5. Speaker Recognition Setup (Optional)

To ensure the voice assistant only responds to your voice:

```bash
python enroll_voice.py
```

Speak for 5 seconds into your microphone when prompted. The script computes a 64-band normalized FFT voiceprint and saves `faisal.voice.npy`. The voice loop verifies incoming audio against this profile in under 2ms.

## Usage

### Command Line Interface

Ask questions or execute commands:
```bash
mike --ask "what is my agenda"
mike --ask "add task implement redis caching to my agenda"
```

Sync coding progress manually for any project:
```bash
mike --sync-git --repo "D:/path/to/project"
```

Run silently (without spoken audio output):
```bash
mike --ask "what is my agenda" --silent
```

### Always-On Voice Assistant

Start the voice listener:
```bash
python main.py
```

- Speaks a personalized greeting on startup.
- Automatically captures speech, verifies speaker identity, routes commands, and speaks responses.
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
  mike --agent-report "<concise summary of completed work and files touched>" --repo "."
  ```
- This automatically reconciles code changes against Google Tasks ("Daily Agenda"), checks off finished tasks, appends progress notes, and updates `NEXT_PLAN.md` for your next session.
```

### Antigravity IDE (Gemini)

Add the directive to your workspace rules or `AGENTS.md`:

```markdown
## Automated Project Lead Sync
Whenever you finish an implementation task, run:
`mike --agent-report "<summary of changes>" --repo "."`
```

### Automated Git Post-Commit Hook

To have every `git commit` in any repository automatically update your Google Tasks, install the hook:

```bash
# In your target repository:
# .git/hooks/post-commit
#!/bin/sh
mike --sync-git --repo "$(pwd)" --silent &
```

Or configure globally across all git repositories:
```bash
git config --global core.hooksPath "C:/Users/Faisal/.git_hooks"
```

## Security & Secrets

All API keys, OAuth tokens, and voice profiles are strictly excluded from version control via `.gitignore`:
- `.env`
- `credentials.json`
- `token.json`
- `local_tasks.json`
- `*.voice` / `*.npy`
- `*.mp3`

Use `jarvis-assistant/.env.example` as the clean configuration template.
