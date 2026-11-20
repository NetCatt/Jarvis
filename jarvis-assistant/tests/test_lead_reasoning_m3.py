import ast
import io
import json
import os
import psutil
import subprocess
import sys
import tokenize
from unittest.mock import MagicMock
import pytest

from audio.tts import speak
from brain import _build_system_prompt, _build_tool_declarations, _call_gemini_rest
from lead.prompts import (
    LEAD_SYSTEM_PROMPT,
    build_dispatch_directive,
    build_lead_prompt,
    detect_emotion_cue,
    map_task_to_skills,
)
from tools.dispatch import dispatch_coding_agent
from tools.tasks import get_open_tasks_context, list_agenda


def test_context_enriched_task_retrieval_preserves_notes_and_blockers(monkeypatch, tmp_path):
    fake_tasks_file = tmp_path / "local_tasks.json"
    tasks_data = {
        "Daily Agenda": [
            {
                "id": "t1",
                "title": "Fix memory leak in STT worker",
                "notes": "[14:00] Investigated pipe buffering\n[16:30] RMS spike due to unbuffered stderr; blocker resolved with thread drain",
                "status": "needsAction",
                "due": "2026-11-20",
            },
            {
                "id": "t2",
                "title": "Refactor lead reasoning prompt",
                "notes": "Replace robotic prohibitions with Mike Ross persona",
                "status": "needsAction",
                "due": "",
            },
        ]
    }
    fake_tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")
    monkeypatch.setattr("tools.tasks._get_local_file", lambda: str(fake_tasks_file))
    monkeypatch.setattr("tools.tasks._has_oauth", lambda: False)

    context = get_open_tasks_context()
    assert "Fix memory leak in STT worker" in context
    assert "RMS spike due to unbuffered stderr" in context
    assert "Refactor lead reasoning prompt" in context

    agenda = list_agenda()
    assert "2 open in Daily Agenda" in agenda
    assert "Fix memory leak in STT worker" in agenda
    assert "blocker resolved with thread drain" in agenda


def test_task_retrieval_and_lead_prompt_with_null_and_missing_task_fields(monkeypatch, tmp_path):
    fake_tasks_file = tmp_path / "local_tasks_null.json"
    tasks_data = {
        "Daily Agenda": [
            {
                "id": "t_null_1",
                "title": "Task with null fields",
                "notes": None,
                "due": None,
                "status": "needsAction",
            },
            {
                "id": "t_null_2",
                "notes": "Valid note with missing title",
                "status": "needsAction",
            },
            {
                "id": "t_null_3",
                "title": None,
                "notes": None,
                "due": None,
                "status": "needsAction",
            },
        ]
    }
    fake_tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")
    monkeypatch.setattr("tools.tasks._get_local_file", lambda: str(fake_tasks_file))
    monkeypatch.setattr("tools.tasks._has_oauth", lambda: False)

    context = get_open_tasks_context()
    assert "- Task with null fields" in context
    assert "Notes: Valid note with missing title" in context

    agenda = list_agenda()
    assert "3 open in Daily Agenda (Local)" in agenda
    assert "Task with null fields" in agenda
    assert "Untitled" in agenda

    sys_prompt = _build_system_prompt("default_test_session", "Hello Mike Ross")
    assert "Mike Ross" in sys_prompt
    assert "Task with null fields" in sys_prompt


def test_task_retrieval_and_lead_prompt_with_non_string_scalar_fields(monkeypatch, tmp_path):
    fake_tasks_file = tmp_path / "local_tasks_scalars.json"
    tasks_data = {
        "Daily Agenda": [
            {
                "id": 101,
                "title": 9999,
                "notes": 12345,
                "due": False,
                "status": "needsAction",
            },
            {
                "id": "t_scalar_2",
                "title": "Scalar due test",
                "notes": 456,
                "due": 20261120,
                "status": "needsAction",
            },
        ]
    }
    fake_tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")
    monkeypatch.setattr("tools.tasks._get_local_file", lambda: str(fake_tasks_file))
    monkeypatch.setattr("tools.tasks._has_oauth", lambda: False)

    context = get_open_tasks_context()
    assert "- 9999:" in context
    assert "Notes: 12345" in context
    assert "- Scalar due test (due: 20261120):" in context
    assert "Notes: 456" in context

    agenda = list_agenda()
    assert "2 open in Daily Agenda (Local)" in agenda
    assert "9999 [Status: 12345]" in agenda
    assert "Scalar due test [Status: 456]" in agenda

    sys_prompt = _build_system_prompt("default_test_session", "Hello Mike Ross")
    assert "Mike Ross" in sys_prompt
    assert "9999" in sys_prompt
    assert "12345" in sys_prompt


def test_lead_prompt_defensive_thread_formatting():
    active_state = {
        "current_project": "jarvis-assistant",
        "last_topic": "defensive-checks",
        "open_threads": [None, "thread-1", 42, ""],
    }
    prompt = build_lead_prompt(active_state, [], [], [], "No open tasks.")
    assert "thread-1, 42" in prompt


def test_lead_prompt_construction_with_mike_ross_persona_and_emotions():
    active_state = {"current_project": "jarvis-assistant", "last_topic": "lead-reasoning", "open_threads": ["R2", "R4"]}
    personality_directives = ["Diagnose root cause before suggesting code changes.", "Maintain crisp spoken answers."]
    facts = [{"predicate": "role", "value": "Lead Architect"}]
    recalled_memories = ["Hardware constraint is 45 MB RSS."]
    open_tasks = "- Fix memory leak:\n  Notes: Blocked by pipe buffer"

    for emotion in ("focused", "urgent", "collaborative", "inquisitive"):
        prompt = build_lead_prompt(active_state, personality_directives, facts, recalled_memories, open_tasks, current_emotion=emotion)
        assert "Mike Ross" in prompt
        assert "jarvis-assistant" in prompt
        assert "lead-reasoning" in prompt
        assert "Lead Architect" in prompt
        assert "45 MB RSS" in prompt
        assert "Diagnose root cause" in prompt
        assert "Tier 1: Emergency" not in prompt
        assert f"Current emotional posture: {emotion}" in prompt


def test_detect_emotion_cue_heuristics():
    assert detect_emotion_cue("Emergency: memory leak crashing the server immediately!") == "urgent"
    assert detect_emotion_cue("Why did this test fail and how can we investigate the root cause?") == "inquisitive"
    assert detect_emotion_cue("Let's work together as a team to review this component") == "collaborative"
    assert detect_emotion_cue("Execute standard database migration step") == "focused"


def test_skill_mapping_and_dispatch_directive_generation():
    refactor_skills = map_task_to_skills("Refactor monolithic event loop into modular handlers")
    assert "anti-overengineering" in refactor_skills

    search_skills = map_task_to_skills("Investigate memory leak and trace token usage")
    assert "token-efficiency" in search_skills

    review_skills = map_task_to_skills("Review pull request diff and verify assertions")
    assert "code-review" in review_skills

    directive = build_dispatch_directive(refactor_skills)
    assert "[Project Lead Directive]:" in directive
    assert "Enforce strict modular architecture" in directive
    assert "Zero-to-minimal comments" in directive
    assert "anti-overengineering" in directive


def test_dispatch_coding_agent_prepends_directive_and_supports_backends(monkeypatch):
    captured_commands = []

    class FakeProc:
        def __init__(self, cmd):
            self.cmd = cmd
            self.stdout = json.dumps({"result": "Modular implementation complete.", "is_error": False, "total_cost_usd": 0.012})
            self.stderr = ""
            self.returncode = 0

    def fake_subprocess_run(cmd, *args, **kwargs):
        captured_commands.append(cmd)
        return FakeProc(cmd)

    monkeypatch.setattr("tools.dispatch._find_claude_cli", lambda: "fake_claude.exe")
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    task = "Refactor database indexing logic"
    result = dispatch_coding_agent(task, agent="architect", repo_path=".")
    assert "Modular implementation complete" in result
    assert len(captured_commands) == 1
    passed_prompt = captured_commands[0][2]
    assert "[Project Lead Directive]:" in passed_prompt
    assert "Enforce strict modular architecture" in passed_prompt
    assert "anti-overengineering" in passed_prompt
    assert task in passed_prompt

    monkeypatch.setattr("tools.dispatch._dispatch_gemini_agent", lambda p, t, to: ("Antigravity worker finished task cleanly.", "success", 0.0))
    gemini_result = dispatch_coding_agent("Investigate RSS memory trace", agent="antigravity", repo_path=".")
    assert "Antigravity worker finished" in gemini_result


def test_tts_emotion_prosody_modulation(monkeypatch):
    recorded_commands = []

    def fake_subprocess_run(cmd, *args, **kwargs):
        recorded_commands.append(cmd[2])
        return MagicMock(returncode=0)

    monkeypatch.setattr("audio.tts._speak_fish_stream", lambda text, emotion: False)
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    speak("System alert: CPU threshold exceeded.", emotion="urgent")
    assert len(recorded_commands) >= 1
    assert "$s.Rate = 2" in recorded_commands[-1]

    speak("Let's review our findings together.", emotion="collaborative")
    assert "$s.Rate = -1" in recorded_commands[-1]

    speak("Analysis confirmed.", emotion="focused")
    assert "$s.Rate = 0" in recorded_commands[-1]


def test_brain_rest_client_tool_chaining_and_response_parsing(monkeypatch):
    from tools import TOOL_FUNCTIONS

    declarations = _build_tool_declarations(TOOL_FUNCTIONS)
    names = [d["name"] for d in declarations]
    assert "list_agenda" in names
    assert "dispatch_coding_agent" in names
    assert "add_task" in names

    fake_response_data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Root cause identified: unbuffered pipe blockage."}
                    ]
                }
            }
        ]
    }

    class FakeUrlResponse:
        def read(self):
            return json.dumps(fake_response_data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeUrlResponse())
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")

    resp = _call_gemini_rest([{"role": "user", "parts": [{"text": "Diagnose root cause"}]}])
    assert "candidates" in resp
    text = resp["candidates"][0]["content"]["parts"][0]["text"]
    assert "Root cause identified" in text


def test_main_py_modular_structure_and_line_count():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_path = os.path.join(repo_dir, "main.py")
    with open(main_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) < 100
    assert "from audio import" in content
    assert "from brain import process_turn" in content
    assert "from memory.store import init_db" in content
    assert "StreamingTranscriber" in content
    assert "DynamicVoiceEndpoint" in content


def test_zero_comments_and_docstrings_in_all_m3_files():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_files = [
        os.path.join(repo_dir, "lead", "__init__.py"),
        os.path.join(repo_dir, "lead", "prompts.py"),
        os.path.join(repo_dir, "tools", "tasks.py"),
        os.path.join(repo_dir, "tools", "dispatch.py"),
        os.path.join(repo_dir, "brain.py"),
        os.path.join(repo_dir, "main.py"),
        os.path.join(repo_dir, "tools", "media.py"),
        os.path.join(repo_dir, "audio", "tts.py"),
        os.path.join(repo_dir, "tests", "test_lead_reasoning_m3.py"),
        os.path.join(repo_dir, "tests", "test_tier1_features.py"),
    ]

    for file_path in target_files:
        assert os.path.exists(file_path), f"File not found: {file_path}"
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
        comment_tokens = [t for t in tokens if t.type == tokenize.COMMENT]
        assert len(comment_tokens) == 0, f"Comments found in {file_path}: {[t.string for t in comment_tokens]}"

        tree = ast.parse(code)
        docstrings = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and ast.get_docstring(n) is not None
        ]
        assert len(docstrings) == 0, f"Docstrings found in {file_path}: {docstrings}"


def test_rss_memory_under_45mb_with_brain_and_lead():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = """
import psutil
from brain import process_turn
from lead.prompts import build_lead_prompt
from memory.store import init_db
from tools.tasks import get_open_tasks_context
from tools.dispatch import dispatch_coding_agent

init_db()
prompt = build_lead_prompt({}, [], [], [], "")
context = get_open_tasks_context()
rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
print(f"ACTIVE_LEAD_RSS:{rss_mb:.2f}")
assert rss_mb < 45.0, f"Active RSS exceeded 45 MB: {rss_mb}"
"""
    proc = subprocess.run([sys.executable, "-c", script], cwd=repo_dir, capture_output=True, text=True)
    assert proc.returncode == 0, f"Error: {proc.stderr}"
    assert "ACTIVE_LEAD_RSS:" in proc.stdout
