# AGENTS.md — Jarvis Project Lead & Voice Orchestrator Specification

## 1. System Overview & Hardware Constraints
- **Host**: Windows 10 Home (10.0.19045), Dell Inspiron 15 3511
- **CPU**: 11th Gen Intel Core i3-1115G4 (2 Cores / 4 Threads)
- **RAM**: 8.00 GB (7.75 GB usable, ~355 MB free physical RAM)
- **Resident Process Cap**: Python RSS <= 45 MB RAM
- **Banned Libraries**: torch, onnxruntime, pygame, watchdog daemon

## 2. Squad Roles & Responsibilities
- **Lead ML Architect**: System topology, linearity, token/quota budget, agent task reconciliation.
- **Senior Systems & Runtime Engineer**: Native Windows C-bindings (winmm.dll, user32.dll), speaker verification (<15ms), audio self-mute guard.
- **Senior Model & Inference Engineer**: Gemini 3.8 Flash + 3.5 Flash Lite fallback, temp=0.0, deterministic tool routing, 1 RTT execution.
- **Senior Integration & QA Engineer**: Google Tasks OAuth CRUD, webhook standup dispatches, Git bounded inspection, CLI hooks.

## 3. Automated Coding Agent Hook
Coding agents in VS Code and Antigravity IDE must follow this rule:
```bash
# After completing any milestone, bugfix, or feature:
python C:/path/to/jarvis-assistant/jarvis_cli.py --agent-report "<concise summary of changes and files touched>" --repo "."
```
- Jarvis reconciles the report against Google Tasks ("Daily Agenda").
- Ticks completed tasks, appends progress notes, generates `NEXT_PLAN.md`.
- Posts status to Discord/Slack/Telegram webhook and speaks 1-sentence confirmation.

## 4. Verification Commands (Smoke Tests)
```bash
# 1. Test Webhook:
python -c "from tools.notify import send_summary; print(send_summary(['Test Completed'], ['Test Progress'], ['Test New Task'], ['Remaining Task']))"

# 2. Test Git Snapshot:
python -c "from tools.dev_sync import get_repo_snapshot; print(get_repo_snapshot('.'))"

# 3. Test Tasks Agenda:
python -c "from tools.tasks import list_agenda; print(list_agenda())"

# 4. Test Brain Routing:
python -c "from brain import route_command; print(route_command('list my daily agenda'))"

# 5. Test CLI Agent Hook:
python jarvis_cli.py --agent-report "Scaffolded core tools and brain" --repo . --silent
```
