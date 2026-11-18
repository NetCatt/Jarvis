import pytest

from audio.vad import DynamicVoiceEndpoint
import memory.retrieval as retrieval
import memory.store as store


def test_vad_empty_and_undersized_and_oversized_frames():
    vad = DynamicVoiceEndpoint(vad_mode=2)
    sp, ep = vad.process_frame(b"", "")
    assert not ep

    sp, ep = vad.process_frame(b"\x00" * 80, "")
    assert not ep

    sp, ep = vad.process_frame(b"\x00" * 1280, "")
    assert not ep


def test_vad_hesitation_within_hangover_window(pcm_factory):
    vad = DynamicVoiceEndpoint(vad_mode=2)
    for frame in pcm_factory.speech_stream(duration_ms=200):
        vad.process_frame(frame, "let us look at")
    assert vad.triggered

    for frame in pcm_factory.silence_stream(duration_ms=300):
        _, is_ep = vad.process_frame(frame, "let us look at")
        assert not is_ep

    for frame in pcm_factory.speech_stream(duration_ms=200):
        vad.process_frame(frame, "let us look at the architecture")

    assert vad.silence_ms == 0


def test_vad_trailing_conjunctions_extended_hangover(pcm_factory):
    conjunctions = ["and", "or", "to", "because", "with", "but"]
    for conj in conjunctions:
        vad = DynamicVoiceEndpoint(vad_mode=2)
        for frame in pcm_factory.speech_stream(duration_ms=200):
            vad.process_frame(frame, f"we need to refactor {conj}")

        for frame in pcm_factory.silence_stream(duration_ms=900):
            _, is_ep = vad.process_frame(frame, f"we need to refactor {conj}")
            assert not is_ep, f"Premature endpoint reached for trailing conjunction '{conj}' at 900ms"

        reached = False
        for frame in pcm_factory.silence_stream(duration_ms=1000):
            _, is_ep = vad.process_frame(frame, f"we need to refactor {conj}")
            if is_ep:
                reached = True
                break
        assert reached, f"Expected endpoint reached after full 1400ms window for '{conj}'"


def test_vad_short_utterance_extended_hangover(pcm_factory):
    vad = DynamicVoiceEndpoint(vad_mode=2)
    for frame in pcm_factory.speech_stream(duration_ms=200):
        vad.process_frame(frame, "status check")

    for frame in pcm_factory.silence_stream(duration_ms=900):
        _, is_ep = vad.process_frame(frame, "status check")
        assert not is_ep

    reached = False
    for frame in pcm_factory.silence_stream(duration_ms=900):
        _, is_ep = vad.process_frame(frame, "status check")
        if is_ep:
            reached = True
            break
    assert reached


def test_vad_stop_phrase_immediate_cutoff():
    vad = DynamicVoiceEndpoint(stop_phrase="over")
    sp, ep = vad.process_frame(bytes(640), "run diagnostics over")
    assert ep
    clean = vad.strip_stop_phrase("run diagnostics over")
    assert clean == "run diagnostics"


def test_vad_reset_state(pcm_factory):
    vad = DynamicVoiceEndpoint(vad_mode=2)
    for frame in pcm_factory.speech_stream(duration_ms=200):
        vad.process_frame(frame, "testing reset")
    assert vad.triggered
    vad.reset()
    assert not vad.triggered
    assert vad.silence_ms == 0
    assert len(vad.hangover_buffer) == 0


def test_fts5_empty_query_and_special_syntax(temp_db):
    assert retrieval.recall("", session_id="s_test") == []
    assert retrieval.recall("   ", session_id="s_test") == []
    assert retrieval.recall(None, session_id="s_test") == []
    assert retrieval.recall(12345, session_id="s_test") == []
    assert retrieval.recall("!@#$%^&*()_+-=[]{}|;':,./<>?", session_id="s_test") == []
    assert retrieval.recall("AND OR NOT NEAR", session_id="s_test") == []

    assert store.query_skills("") == []
    assert store.query_skills("   ") == []
    assert store.query_skills("***???") == []


def test_fts5_zero_matches_fallback(temp_db):
    store.record_turn("s_zero", "user", "Standard logging in python")
    matches = retrieval.recall("astronomy astrophysics telescope", session_id="s_zero")
    assert matches == []


def test_active_state_capacity_and_clamping(temp_db):
    threads = [f"thread_{i}" for i in range(15)]
    followups = [f"followup_{i}" for i in range(15)]
    store.set_active_state("s_clamp", open_threads=threads, pending_followups=followups)
    state = store.get_active_state("s_clamp")
    assert len(state["open_threads"]) <= 8
    assert len(state["pending_followups"]) <= 8
    assert state["open_threads"] == threads[-8:]


def test_memory_high_turn_churn_and_compaction(temp_db):
    for i in range(60):
        store.record_turn("s_churn", "user" if i % 2 == 0 else "mike", f"Turn message payload index {i}")

    recalled = retrieval.recall("payload index 55", session_id="s_churn")
    assert len(recalled) > 0

    store.compact("s_churn", keep_last=15)
    recent = store.recent_turns("s_churn", n=100)
    assert len(recent) <= 16


def test_tool_call_invalid_kwargs_handling(monkeypatch):
    import brain

    def fake_call_gemini_rest(contents, **kwargs):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "sync_coding_progress",
                                    "args": {"hallucinated_param": 123},
                                }
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(brain, "_call_gemini_rest", fake_call_gemini_rest)
    monkeypatch.setattr(brain, "_get_client", lambda: None)
    monkeypatch.setattr(brain, "_build_system_prompt", lambda s, u: "")
    reply = brain.converse("s_tool_err", "sync code")
    assert "Tool execution error" in reply


def test_concurrent_record_turn_burst(temp_db):
    import threading

    errors = []

    def worker(idx):
        try:
            for j in range(25):
                store.record_turn("s_burst", "user", f"Worker {idx} msg {j}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    recent = store.recent_turns("s_burst", n=300)
    assert len(recent) == 200
