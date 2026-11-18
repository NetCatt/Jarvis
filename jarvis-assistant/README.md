# Jarvis: Developer Project Lead & Local Orchestrator

A lightweight Python service designed to reconcile local Git development progress with Google Tasks, generate next-step execution plans for coding agents, and provide desktop orchestration under strict RAM constraints (< 45 MB RSS).

## Requirements

- Python 3.10+
- Windows 10/11 (uses native winmm.dll and user32.dll bindings)
- Google AI Studio API Key (Free Tier: Gemini 3.8 Flash / Gemini 3.5 Flash Lite)
- Google Cloud OAuth 2.0 Desktop Client credentials (for Google Tasks API)

## Architecture

The system operates as a single-threaded linear pipeline without background polling daemons:

```
Trigger (CLI / Git Hook / Voice)
  -> Voice capture: webrtcvad-gated recording -> offline English-only STT (vosk)
  -> Input/Speaker Verification
  -> Memory assembly: working state + durable facts + episodic recall (SQLite, memory/)
  -> Gemini Flash Conversation/Routing (brain.converse) -> deterministic tool, or
     dispatch_coding_agent (Claude Code CLI, headless) for real engineering tasks
  -> Memory persistence (turn + extracted facts/state)
  -> Google Tasks Mutation & NEXT_PLAN.md Generation (dev_sync / planner)
  -> Webhook Standup Notification
  -> Text-to-Speech Output
```

Mike holds real stateful, multi-turn conversations (not one-shot commands), backed by a three-tier memory system (`memory/`): working state (always loaded), durable facts with confidence/decay (also where personality/preference traits live), and embedding-based episodic recall (`model2vec`, NumPy-only) for the long tail. Deterministic one-shot commands (tasks, apps, media) bypass memory entirely for latency.

Voice capture uses `webrtcvad` to start/stop on actual speech instead of a fixed-duration clip, transcribed offline and English-only via `vosk` — no cloud STT quota/reliability dependency, and structurally unable to mis-transcribe into another language.

## Installation

1. Clone repository and install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy environment template and configure keys:
```bash
cp .env.example .env
```

3. Configure Google Tasks API:
- Create a project on Google Cloud Console.
- Enable the Google Tasks API.
- Create an OAuth 2.0 Client ID (type: Desktop app).
- Download the client secrets file and save it as `credentials.json` in the project root.
- Run authentication flow once to generate `token.json`:
```bash
python auth_setup.py
```

4. Download the offline English STT model (one-time, ~130MB, not committed to git):
```bash
curl -L -o models/vosk-model-en-us-0.22-lgraph.zip https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip
unzip models/vosk-model-en-us-0.22-lgraph.zip -d models/
rm models/vosk-model-en-us-0.22-lgraph.zip
```
For a lower-RAM alternative (~236MB RSS vs ~460MB), use `vosk-model-small-en-us-0.15` (~41MB download) instead and point `VOSK_MODEL_PATH` at it.

## Configuration

Set configuration values in `.env`:

| Key | Description | Default |
| --- | --- | --- |
| GEMINI_API_KEY | Google AI Studio API Key | Required |
| GEMINI_MODEL | Primary model | gemini-3.5-flash-lite (generous free quota; full `flash` caps at 20 req/day free) |
| GEMINI_FALLBACK_MODEL | Fallback on rate limits/errors | gemini-3.5-flash |
| DEFAULT_REPO_PATH | Target codebase path to inspect | Local directory |
| GOOGLE_TASKS_LIST_NAME | Google Tasks list title | Daily Agenda |
| TTS_VOICE | Edge TTS voice identifier | en-US-ChristopherNeural |
| WEBHOOK_URL | Optional Discord/Slack webhook | None |
| VOSK_MODEL_PATH | Offline English STT model directory | models/vosk-model-en-us-0.22-lgraph |
| STOP_PHRASE | Say this at the end of a sentence to end your turn immediately (no silence wait) | over |
| VOICE_MATCH_THRESHOLD | Spectral-similarity score required to accept the speaker | 0.40 |
| MEMORY_DB_PATH | SQLite memory file (working state/facts/episodic) | memory.db |
| EMBEDDING_MODEL | Static embedding model for episodic recall | minishlab/potion-base-8M |
| AGENT_DISPATCH_MAX_BUDGET_USD | Cost cap per Claude Code CLI dispatch | 1.00 |
| CLAUDE_CLI_PATH | Override auto-discovered claude.exe path | auto-detected |

## Usage

### CLI Commands

Check open tasks:
```bash
python jarvis_cli.py --ask "what is on my agenda"
```

Add a task manually:
```bash
python jarvis_cli.py --ask "add task implement password reset to my agenda"
```

Schedule a task for a future date, or create/use separate task lists beyond the default Daily Agenda:
```bash
python jarvis_cli.py --ask "remind me to renew car insurance tomorrow"
python jarvis_cli.py --ask "create a task list called Groceries"
python jarvis_cli.py --ask "add milk and eggs to my Groceries list"
python jarvis_cli.py --ask "what task lists do I have"
python jarvis_cli.py --ask "what's on my agenda today"
```
Mike resolves relative dates against the real current date and keeps lists separate — a task added to "Groceries" won't show up when you ask about the Daily Agenda.

Sync workspace status and diffs with Google Tasks:
```bash
python jarvis_cli.py --sync-git --repo /path/to/project
```

### Coding Agent Integration (Claude / Gemini / Antigravity)

Add this hook to your project's `CLAUDE.md`, `.cursorrules`, or `AGENTS.md`:

```markdown
Whenever you complete an implementation milestone or bugfix, execute:
python /path/to/jarvis-assistant/jarvis_cli.py --agent-report "<summary of changes and files touched>" --repo "."
```

When fired, Jarvis automatically:
1. Reconciles code changes against open tasks on Daily Agenda.
2. Marks completed items done and appends timestamped notes to partial work.
3. Generates `NEXT_PLAN.md` in the target repo root for the agent's next task.
4. Sends a standup summary to the configured webhook.

### Voice Loop

Double-click `run_mike.bat` to start the always-on voice assistant — no terminal or IDE needed. (Or run `python main.py` directly.)

Press `F9` to toggle between Active and Standby modes. Each run holds one continuous multi-turn conversation (session tied to the process) — Mike will reference things said earlier in the same run.

### Data layout

All secrets and runtime state live under `data/` (gitignored): `credentials.json`, `token.json`, `local_tasks.json`, `faisal.voice.npy`, `memory.db`. Source code stays at the repo root/`tools/`/`memory/` packages.

### Dispatching real engineering work

Ask Mike to build/fix/architect something and he'll route it to the Claude Code CLI instead of trying to do it himself:
```bash
python jarvis_cli.py --ask "have the ml-engineer refactor the training pipeline in my-project for batching"
```
This costs real API dollars (capped by `AGENT_DISPATCH_MAX_BUDGET_USD`), unlike Mike's own Gemini-based conversation. Every dispatch is logged with cost/result; inspect it with:
```bash
python -c "from memory.store import _connect, init_db; init_db(); [print(dict(r)) for r in _connect().execute('SELECT * FROM workflows')]"
```

### Memory debug

```bash
python jarvis_cli.py --recall "what do you know about my preferences"
python jarvis_cli.py --reflect   # compacts older turns, bounding memory.db growth
```
