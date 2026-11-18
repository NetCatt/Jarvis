# AGENTS.md — Jarvis Project Lead & Voice Orchestrator Specification

## 1. System Overview & Hardware Constraints
- **Host**: Windows 10 Home (10.0.19045), Dell Inspiron 15 3511
- **CPU**: 11th Gen Intel Core i3-1115G4 (2 Cores / 4 Threads)
- **RAM**: 8.00 GB (7.75 GB usable, ~355 MB free physical RAM)
- **Resident Process Cap**: ~45 MB RSS for the lightweight deterministic command path (tasks/apps/media — unchanged). The full conversational path with offline STT (`vosk-model-en-us-0.22-lgraph`) and episodic embeddings (`model2vec`) both loaded runs ~460 MB RSS — measured directly, not estimated. This is a deliberate trade-off, made explicitly (not by default): the smaller `vosk-model-small-en-us-0.15` (~236 MB) was tried first and upgraded on request for better transcription accuracy, since STT errors were directly causing the bad-conversation symptoms this whole rebuild exists to fix. On this machine's 8GB total RAM, ~460MB is accepted as negligible in absolute terms; revisit only if free RAM is observed under real pressure.
- **Banned Libraries**: torch, onnxruntime, pygame, watchdog daemon

## 2. Squad Roles & Responsibilities
- **Lead ML Architect**: System topology, linearity, token/quota budget, agent task reconciliation.
- **Senior Systems & Runtime Engineer**: Native Windows C-bindings (winmm.dll, user32.dll), speaker verification (<15ms), audio self-mute guard.
- **Senior Model & Inference Engineer**: Gemini Flash Lite (primary) + Flash (fallback), deterministic tool routing, stateful multi-turn conversation via `brain.converse()`. **Confirmed (not assumed)**: free-tier `gemini-3.5-flash` caps at only 20 requests/day — too tight for real conversational use — so `flash-lite` (much more generous free quota, performs identically for this workload) is primary, `flash` the fallback. A previously-hardcoded third fallback (`gemini-2.5-flash`) is a confirmed 404 (deprecated for new users) and has been removed rather than left as dead weight.
- **Senior Integration & QA Engineer**: Google Tasks OAuth CRUD, webhook standup dispatches, Git bounded inspection, CLI hooks.

## 2b. Voice Pipeline (offline, English-only)
- Capture: `webrtcvad`-gated recording in `main.py` (`_capture_audio_vad`) — two independent budgets, not one shared cap: `VAD_LISTEN_TIMEOUT_SEC` (how long to wait silently for speech to start) and `VAD_MAX_DURATION_SEC` (how long an utterance may run ONCE SPEECH STARTS, counted from the trigger — not from when listening began). The old bug counted both phases against a single cap, truncating longer sentences mid-word whenever any time was spent waiting before Fas started talking. `VAD_MAX_DURATION_SEC` defaults high (120s) — it's a safety backstop against a stuck mic, not a real conversational limit; actual end-of-utterance is purely silence-based (`VAD_SILENCE_MS`).
- STT: `vosk` (`vosk-model-small-en-us-0.15`, Kaldi/C++ backend) — fully offline, no API quota, and **structurally English-only** (the model has no other-language vocabulary, so it cannot mistranscribe into another language the way the old free Google Web Speech API did).
- Defense-in-depth: `brain.py`'s system prompt hard-locks replies to English regardless of apparent input language.
- Wake-word gating (`main.py`, `_strip_wake_word`): Mike only engages on a wake word (`WAKE_WORDS`, default "mike,ross,hey mike,hey ross") or within `WAKE_GRACE_SEC` (default 8s) of his last reply — otherwise the utterance is logged as ignored and never reaches Gemini at all. This exists because the always-on loop was trying to interpret every fragment of ambient speech/side-commentary as a command, producing nonsense "I didn't catch that" responses to things never directed at him.
- `VOICE_SESSION_ID` (`main.py`'s `listen_and_execute`) is a STABLE session id (default `"voice"`), not randomized per launch. A previous version minted a fresh `voice-{pid}-{timestamp}` session every run, so any restart (crash, manual stop/start while testing) silently wiped all short-term memory and working state — which presented as "forgets everything after one sentence," even though the memory system itself was verified working correctly turn-to-turn when the session id stays constant. Fixed by not generating a new identity every launch.
- **Live console feedback added** — the capture loop previously printed nothing until an entire utterance finished, so a quiet mic, a rejected speaker check, or a no-speech timeout all looked identical to "frozen." `_capture_and_transcribe` now prints `[Mike] Listening...`, a `[Fas, live]: ...` partial transcript as Vosk decodes (via `rec.PartialResult()`), and an explicit "(no speech detected, still listening)" message on timeout. `voice_gate.verify_speaker` now prints the actual rejection reason (spectral-similarity score vs threshold, or energy-gate std vs 250) instead of silently returning `False` — a mismatched/too-strict voice profile was a likely silent-failure point and is now visible. `listen_and_execute` also prints the resolved input device name at startup so a wrong/missing mic shows up immediately instead of as unexplained silence.
- **`VOICE_MATCH_THRESHOLD` lowered 0.65 -> 0.40** — the spectral-similarity score between live mic audio and the enrolled profile (`data/faisal.voice.npy`) drifts with gain/room noise, and 0.65 was silently rejecting genuine speech with zero signal before the logging above existed. If false accepts become a problem, raise it back up gradually while watching the now-visible score in the console.
- **`STOP_PHRASE` (default `"over"`)** — saying it at the end of an utterance ends capture immediately instead of waiting out `VAD_SILENCE_MS` of trailing silence. `_capture_and_transcribe` tracks finalized Vosk result chunks plus the current partial, checks the running text against the phrase every frame, and on match breaks the capture loop and strips the phrase (`_strip_stop_phrase`) from the transcript before it reaches `brain.converse()` — so saying "...turn off the lights, over" sends "...turn off the lights" to Mike, not the literal word "over".

## 2b-3. Speed Optimizations
- **Streaming STT decode**: `_capture_and_transcribe` (merged from the previous separate capture/transcribe functions) feeds each audio frame to Vosk's recognizer AS IT ARRIVES during capture, not as one `AcceptWaveform` call on the full buffer after silence is detected. Decode time overlaps with capture time instead of stacking after it.
- **Lower default `VAD_SILENCE_MS`** (900ms -> 650ms) — snappier perceived response; still enough trailing silence to rarely clip a trailing word.
- **Explicit Gemini context caching was tried and confirmed unavailable** on this account/API tier — `client.caches.create()` returns a 404 regardless of model name format, tested directly, not assumed. Not implemented; don't re-attempt without re-verifying availability first.
- **Streaming TTS playback** (`main.py`, `_speak_fish_stream`): requests `format="pcm"` + `latency="balanced"` from Fish Audio's plain `POST /v1/tts` endpoint (confirmed via their docs — no WebSocket needed when the full reply text is already known) and streams raw PCM chunks straight into `sounddevice.RawOutputStream` as they arrive — no MP3 decode library needed. Falls back to the previous full-file-download-then-MCI path (`_speak_fish_file`) on any error, which itself falls back to Windows SAPI — three tiers, each degrading gracefully, never a regression risk to the previously-working path.
- The single largest latency cost remains the Gemini API round trip itself (measured 3.9-6.7s per call during testing) — this is cloud network + inference time and not addressable client-side. Chained turns (agenda checks, dispatch) pay it twice by design; that's a deliberate naturalness-vs-speed tradeoff, not a bug.

## 2b-2. Agentic Behavior (plan-then-act, not plan-then-describe)
- `brain.converse()` runs a bounded multi-step loop (`MAX_AGENTIC_STEPS`, default 3), not a single round trip: a tool call's result is fed back so Mike can call another tool or give a final synthesized reply — but only for tools in `_CHAINABLE_TOOLS` (`dispatch_coding_agent`, `list_agenda`, `list_task_lists`, `sync_coding_progress` — tools whose result is information to discuss naturally, not just confirm). Pure action-confirmation tools (add_task, play_music, open_app...) stay terminal/single-round-trip — this is what keeps common commands fast; chaining costs a real extra Gemini round trip, so it's scoped only to tools that need synthesis.
- When reusing a chained tool call's result for a follow-up Gemini call, append `resp.candidates[0].content` as-is — do NOT hand-build a `types.Part.from_function_call(...)`. Gemini's thinking models attach a required `thought_signature` to function-call parts that gets silently dropped on manual reconstruction, producing a 400 on the next call. Hit and fixed during testing; this is not hypothetical.
- The system prompt enforces a hard rule: when Fas describes a problem or asks what Mike will do about something, the next action MUST be a real tool call in that same turn — "I'll look into it" with no accompanying tool call is a failure, not an acceptable reply. Likewise, when answering from a chained tool's data, answer in the terms Fas actually asked (yes/no question gets a yes/no answer) rather than reciting the tool's raw return string. Both verified empirically, not just by inspection.

## 2c. Memory (three tiers, `jarvis-assistant/memory/`, one SQLite file in WAL mode)
1. **Working memory** (`active_state` table) — current project/topic/open threads, always loaded in full every turn, updated deterministically after each exchange.
2. **Durable facts** (`facts` table) — `(subject, predicate, value, confidence, evidence_count)` with fuzzy dedup and reinforcement; this is also where personality/preference traits live.
3. **Episodic recall** (`conversations` table + `model2vec` static embeddings) — cosine-ranked recency-bounded recall for the long tail, via `memory.recall()`.

Deterministic one-shot commands (tasks, apps, media) bypass memory entirely — only genuine conversational turns are stored/recalled.

Compaction and fact decay run automatically (`brain._maybe_run_memory_upkeep`, called after every conversational turn) — compaction no-ops cheaply under its threshold so it's safe to call every turn, decay is throttled to once per calendar day per process. `jarvis_cli.py --reflect` remains available to force both manually.

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
