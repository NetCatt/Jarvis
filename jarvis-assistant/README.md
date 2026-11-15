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
  -> Input Verification
  -> Workspace Context Collection (Git status, diff, commits)
  -> Gemini 3.8 Flash Reconciliation
  -> Google Tasks Mutation & NEXT_PLAN.md Generation
  -> Webhook Standup Notification
  -> Text-to-Speech Output
```

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

## Configuration

Set configuration values in `.env`:

| Key | Description | Default |
| --- | --- | --- |
| GEMINI_API_KEY | Google AI Studio API Key | Required |
| GEMINI_MODEL | Primary reconciliation model | gemini-3.8-flash |
| GEMINI_FALLBACK_MODEL | Fallback model on rate limits | gemini-3.5-flash-lite |
| DEFAULT_REPO_PATH | Target codebase path to inspect | Local directory |
| GOOGLE_TASKS_LIST_NAME | Google Tasks list title | Daily Agenda |
| TTS_VOICE | Edge TTS voice identifier | en-US-ChristopherNeural |
| WEBHOOK_URL | Optional Discord/Slack webhook | None |

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

Run the always-on voice assistant:
```bash
python main.py
```
Press `F9` to toggle between Active and Standby modes.
