import io
import os
import subprocess
import sys
import pytest

from audio.stt import StreamingTranscriber, render_live_token
from audio.vad import DynamicVoiceEndpoint
import memory.retrieval as retrieval
import memory.store as store
from brain import _build_system_prompt


def test_dynamic_vad_endpointing_happy_path(pcm_factory):
    vad = DynamicVoiceEndpoint(vad_mode=2)
    for frame in pcm_factory.silence_stream(duration_ms=400):
        vad.process_frame(frame, "")
    assert not vad.triggered

    speech_frames = pcm_factory.speech_stream(duration_ms=300)
    for frame in speech_frames:
        is_sp, is_ep = vad.process_frame(frame, "run integration benchmark")
        assert not is_ep
    assert vad.triggered

    reached = False
    for frame in pcm_factory.silence_stream(duration_ms=1600):
        _, is_ep = vad.process_frame(frame, "run integration benchmark")
        if is_ep:
            reached = True
            break
    assert reached


def test_streaming_transcriber_startup_and_stop():
    stt = StreamingTranscriber()
    stt.start()
    assert stt.process is not None
    assert stt.process.poll() is None
    silence = bytes(640)
    transcript, is_final = stt.feed_pcm(silence)
    assert isinstance(transcript, str)
    assert isinstance(is_final, bool)
    stt.stop()
    assert stt.process is None


def test_ansi_live_token_rendering(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    render_live_token("synthesizing architecture")
    output = buf.getvalue()
    assert "\r\033[K" in output
    assert "[Fas, live]: synthesizing architecture" in output


def test_fts5_memory_turn_storage_and_recall(temp_db):
    store.record_turn("session_alpha", "user", "Refactor memory subsystem with zero-model SQLite FTS5")
    store.record_turn("session_alpha", "mike", "Implemented BM25 full-text indexing without dense embeddings")
    store.record_turn("session_alpha", "user", "Optimize active RSS under forty five megabytes")

    results = retrieval.recall("sqlite fts5", session_id="session_alpha")
    assert len(results) > 0
    assert any("zero-model SQLite FTS5" in r or "BM25" in r for r in results)

    results_rss = retrieval.recall("megabytes forty five", session_id="session_alpha")
    assert len(results_rss) > 0
    assert any("forty five megabytes" in r for r in results_rss)


def test_personality_traits_and_directives(temp_db):
    store.update_personality_trait(
        "proactive_lead",
        "Synthesize concrete implementation steps instead of reciting raw tool outputs.",
        delta_weight=0.5,
    )
    directives = store.get_active_personality_directives()
    assert len(directives) >= 1
    assert any("concrete implementation steps" in d for d in directives)


def test_learned_skills_store_and_query(temp_db):
    store.upsert_skill(
        "anti-overengineering",
        "architecture",
        "Enforce YAGNI and minimal code structure",
        "Avoid unnecessary abstractions",
    )
    store.upsert_skill(
        "token-efficiency",
        "performance",
        "Reduce context consumption and remove fluff",
        "Surgical line edits",
    )
    skills = store.query_skills("unnecessary abstractions", limit=2)
    assert len(skills) >= 1
    assert skills[0]["name"] == "anti-overengineering"


def test_tech_lead_prompt_synthesis_happy_path(temp_db):
    store.set_active_state("session_beta", current_project="jarvis-assistant", last_topic="audio-optimization")
    store.upsert_fact("Fas", "role", "Lead Architect")
    store.record_turn("session_beta", "user", "What is the next step for voice streaming?")

    prompt = _build_system_prompt("session_beta", "voice streaming")
    assert "Mike Ross" in prompt
    assert "jarvis-assistant" in prompt
    assert "audio-optimization" in prompt
    assert "Lead Architect" in prompt
    assert "Tier 1: Emergency" not in prompt


def test_rss_memory_budget_under_45mb():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = """
import psutil
from audio.vad import DynamicVoiceEndpoint
from audio.stt import StreamingTranscriber
import memory.store as store
import memory.retrieval as retrieval
store.init_db()
vad = DynamicVoiceEndpoint(vad_mode=2)
silence = bytes(640)
for _ in range(200):
    vad.process_frame(silence, '')
for i in range(20):
    retrieval.recall('test query ' + str(i))
rss = psutil.Process().memory_info().rss / (1024 * 1024)
print(f'RSS:{rss:.2f}')
assert rss < 45.0, f'RSS exceeded: {rss}'
"""
    proc = subprocess.run([sys.executable, "-c", script], cwd=repo_dir, capture_output=True, text=True)
    assert proc.returncode == 0, f"Error: {proc.stderr}"
    assert "RSS:" in proc.stdout


def test_system_volume_control_and_fast_actions(monkeypatch):
    from brain import _try_fast_action
    from tools.media import get_volume, set_volume, change_volume

    monkeypatch.setattr("tools.media._get_endpoint_volume", lambda: None)
    assert "unavailable" in get_volume().lower()
    assert "unavailable" in set_volume(50).lower()
    assert "unavailable" in change_volume(10).lower()

    fake_state = {"vol": 0.24}

    def fake_get_volume():
        pct = int(round(fake_state["vol"] * 100))
        return f"Current master volume is at {pct}%."

    def fake_set_volume(level):
        fake_state["vol"] = int(level) / 100.0
        return f"Master volume set to {level}%, Fas."

    def fake_change_volume(delta=10):
        fake_state["vol"] = max(0.0, min(1.0, fake_state["vol"] + delta / 100.0))
        pct = int(round(fake_state["vol"] * 100))
        return f"Adjusted volume to {pct}%, Fas."

    monkeypatch.setattr("tools.media.get_volume", fake_get_volume)
    monkeypatch.setattr("tools.media.set_volume", fake_set_volume)
    monkeypatch.setattr("tools.media.change_volume", fake_change_volume)

    rep1 = _try_fast_action("turn up the volume to 50%")
    assert "50%" in rep1

    rep2 = _try_fast_action("volume down")
    assert "Adjusted volume" in rep2

    rep3 = _try_fast_action("what's the volume")
    assert "Current master volume" in rep3


def test_sanitize_spoken_reply_strips_hallucinated_facts():
    from brain import _sanitize_spoken_reply

    leaked = (
        "Volume is cranked to 50 percent, Fas, let's keep riding this momentum.\n"
        'Mike refers to the user as "Fas."\n'
        "The user and Mike are currently working on a Redis caching optimization project.\n"
        "Accountability is maintained on agenda lists by tagging people or project mates next to to-do items."
    )
    cleaned = _sanitize_spoken_reply(leaked)
    assert "Volume is cranked to 50 percent, Fas" in cleaned
    assert "Mike refers to" not in cleaned
    assert "The user and Mike" not in cleaned
    assert "Accountability is" not in cleaned


def test_open_folder_and_search_files(monkeypatch):
    from tools.apps import open_folder, search_files

    opened = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p))

    rep1 = open_folder("models")
    assert "models" in rep1.lower()
    assert len(opened) == 1

    rep2 = open_folder("nonexistent_random_directory_xyz")
    assert "not found" in rep2.lower()

    rep3 = search_files("moonshine")
    assert "found" in rep3.lower()


def test_local_brain_tool_parsing_and_execution(monkeypatch):
    from local_brain import parse_and_execute_local_action, execute_local_turn

    opened = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p))

    t_res, sp = parse_and_execute_local_action('TOOL_CALL: open_folder({"target": "models"})\nOpening models for you, Fas.')
    assert "models" in t_res.lower()
    assert "Opening models for you, Fas." in sp

    t_res2, sp2 = parse_and_execute_local_action('TOOL_CALL: set_volume({"level": 60})\nVolume adjusted to 60%, Fas.')
    assert "Volume adjusted to 60%, Fas." in sp2

    monkeypatch.setattr("local_brain.query_local_brain", lambda p, u, h=None: 'TOOL_CALL: open_folder({"target": "models"})\nOpened models folder, Fas.')
    turn_res = execute_local_turn("open models folder")
    assert "Opened models folder" in turn_res


def test_sanitize_screenplay_and_stage_directions():
    from brain import _sanitize_spoken_reply, _is_system_intent

    dirty = "Mike is now Fas, the tech lead. Fas requests a video.\nMike's tone changes to a serious one.\nI'm on it, Fas."
    clean = _sanitize_spoken_reply(dirty)
    assert clean == "I'm on it, Fas."

    paren = "(whispers) I will take care of this immediately."
    clean_paren = _sanitize_spoken_reply(paren)
    assert clean_paren == "I will take care of this immediately."

    assert _is_system_intent("turn the volume to 50")
    assert _is_system_intent("open folder downloads")
    assert not _is_system_intent("What is the roadmap for Redis optimization?")


def test_tasks_context_completed_items(monkeypatch):
    from tools.tasks import get_completed_tasks_raw, get_open_tasks_context, list_agenda

    mock_tasks = [
        {"id": "t1", "title": "Task 1", "status": "completed"},
        {"id": "t2", "title": "Task 2", "status": "needsAction"}
    ]
    monkeypatch.setattr("tools.tasks._has_oauth", lambda: False)
    monkeypatch.setattr("tools.tasks._read_local_tasks", lambda name: mock_tasks)

    completed = get_completed_tasks_raw()
    assert len(completed) == 1
    assert completed[0]["title"] == "Task 1"

    ctx = get_open_tasks_context()
    assert "Task 2" in ctx
    assert "[Completed] Task 1" in ctx

    agenda_comp = list_agenda(when="completed")
    assert "Task 1" in agenda_comp


def test_media_playback_controls(monkeypatch):
    from tools.media import next_track, pause_music, prev_track
    from brain import _is_system_intent, _try_fast_action
    from local_brain import parse_and_execute_local_action

    monkeypatch.setattr("ctypes.windll.user32.keybd_event", lambda *args: None)

    res_pause = pause_music()
    assert "playback" in res_pause.lower()

    res_next = next_track()
    assert "next track" in res_next.lower()

    res_prev = prev_track()
    assert "previous track" in res_prev.lower()

    assert _is_system_intent("pause my music")
    assert _is_system_intent("skip to next track")

    fast_pause = _try_fast_action("pause my music")
    assert fast_pause and "playback" in fast_pause.lower()

    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: True)
    from tools.media import play_music
    res_music = play_music("metallica")
    assert "metallica on youtube" in res_music.lower()

    fast_play = _try_fast_action("Play Metallica.")
    assert fast_play and "metallica on youtube" in fast_play.lower()

    tool_res, spoken = parse_and_execute_local_action('TOOL_CALL: pause_music({})\nI paused the music for you, Fas.')
    assert "playback" in str(tool_res).lower()
    assert "paused the music" in spoken.lower()

    tool_res_play, _ = parse_and_execute_local_action('TOOL_CALL: play_music({"song": "metallica"})\nPlaying metallica.')
    assert "metallica on youtube" in str(tool_res_play).lower()



