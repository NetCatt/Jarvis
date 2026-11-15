# AGENTS.md — Jarvis Project Lead & Voice Orchestrator Specification

## 1. System Overview & Hardware Constraints
- **Host**: Windows 10 Home (10.0.19045), Dell Inspiron 15 3511
- **CPU**: 11th Gen Intel Core i3-1115G4 (2 Cores / 4 Threads)
- **RAM**: 8.00 GB (7.75 GB usable, ~355 MB free physical RAM)
- **Resident Process Cap**: ~45 MB RSS for the lightweight deterministic command path (tasks/apps/media — unchanged). The full conversational path with offline STT (`vosk`) and episodic embeddings (`model2vec`) both loaded runs ~236 MB RSS — a deliberate trade-off: offline voice capture trades RAM for eliminating cloud STT's quota/reliability dependency entirely. On this machine's 8GB total RAM this is accepted as negligible in absolute terms; revisit only if free RAM is observed under real pressure.
- **Banned Libraries**: torch, onnxruntime, pygame, watchdog daemon

## 2. Squad Roles & Responsibilities
- **Lead ML Architect**: System topology, linearity, token/quota budget, agent task reconciliation.
- **Senior Systems & Runtime Engineer**: Native Windows C-bindings (winmm.dll, user32.dll), speaker verification (<15ms), audio self-mute guard.
- **Senior Model & Inference Engineer**: Gemini Flash + Flash Lite fallback, deterministic tool routing, stateful multi-turn conversation via `brain.converse()`.
- **Senior Integration & QA Engineer**: Google Tasks OAuth CRUD, webhook standup dispatches, Git bounded inspection, CLI hooks.

## 2b. Voice Pipeline (offline, English-only)
- Capture: `webrtcvad`-gated recording in `main.py` (`_capture_audio_vad`) — starts on detected speech, stops after trailing silence, bounded by `VAD_MAX_DURATION_SEC`. No more fixed-duration clips.
- STT: `vosk` (`vosk-model-small-en-us-0.15`, Kaldi/C++ backend) — fully offline, no API quota, and **structurally English-only** (the model has no other-language vocabulary, so it cannot mistranscribe into another language the way the old free Google Web Speech API did).
- Defense-in-depth: `brain.py`'s system prompt hard-locks replies to English regardless of apparent input language.

## 2c. Memory (three tiers, `jarvis-assistant/memory/`, one SQLite file in WAL mode)
1. **Working memory** (`active_state` table) — current project/topic/open threads, always loaded in full every turn, updated deterministically after each exchange.
2. **Durable facts** (`facts` table) — `(subject, predicate, value, confidence, evidence_count)` with fuzzy dedup and reinforcement; this is also where personality/preference traits live.
3. **Episodic recall** (`conversations` table + `model2vec` static embeddings) — cosine-ranked recency-bounded recall for the long tail, via `memory.recall()`.

Deterministic one-shot commands (tasks, apps, media) bypass memory entirely — only genuine conversational turns are stored/recalled.

## 2d. Agent Dispatch (`tools/dispatch.py`)
- `dispatch_coding_agent(task, agent, repo_path)` shells out to the Claude Code CLI headlessly (`claude -p ... --output-format json`), bundled inside the VS Code extension at `%USERPROFILE%\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe` (auto-discovered, or set `CLAUDE_CLI_PATH`).
- `agent='ml-engineer'` or `agent='architect'` (mapped to the CLI's `Plan` agent — there is no literal `architect` agent in this account's setup); empty routes to the default agent.
- Bounded by `AGENT_DISPATCH_MAX_BUDGET_USD` (real API dollars, unlike Mike's own free-tier Gemini routing) and `AGENT_DISPATCH_TIMEOUT_SEC`. Every dispatch is logged to the `workflows` table with cost and result.

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

# 4. Test stateful conversation + memory recall:
python -c "from brain import converse; converse('smoke','remember I like dark mode'); print(converse('smoke','what do you know about my preferences?'))"

# 5. Test CLI Agent Hook:
python jarvis_cli.py --agent-report "Scaffolded core tools and brain" --repo . --silent

# 6. Test offline voice pipeline components load:
python -c "import vosk, webrtcvad; vosk.SetLogLevel(-1); vosk.Model('models/vosk-model-small-en-us-0.15'); print('voice pipeline OK')"

# 7. Test agent dispatch (real API cost, small/cheap prompt only):
python -c "from tools.dispatch import dispatch_coding_agent; print(dispatch_coding_agent('what is this repo for, one sentence', agent='architect', repo_path='.'))"

# 8. Debug memory state for a session:
python jarvis_cli.py --recall "preferences" --session smoke
```
