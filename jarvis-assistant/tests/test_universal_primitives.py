from tools.os_context import os_context
from tools.os_input import os_input
from tools.os_launch import os_launch
from tools.web_dispatch import web_dispatch

def test_web_dispatch_query():
    res = web_dispatch(query="suits clips", engine="youtube")
    assert "Searching Youtube for 'suits clips'" in res or "Searching" in res

    res_url = web_dispatch(url="https://google.com")
    assert "Opening https://google.com" in res_url

def test_os_context_active_window():
    res = os_context("active_window")
    assert isinstance(res, str)
    assert len(res) > 0

def test_os_context_system_stats():
    res = os_context("system_stats")
    assert "System Memory" in res
    assert "used" in res

def test_os_context_clipboard():
    res = os_context("clipboard")
    assert isinstance(res, str)

def test_os_launch_empty():
    res = os_launch("")
    assert "Empty" in res

def test_os_input_empty():
    res = os_input()
    assert "No keys" in res

def test_vad_noise_floor_and_max_duration_cap(pcm_factory):
    from audio.vad import DynamicVoiceEndpoint
    vad = DynamicVoiceEndpoint(vad_mode=3, max_duration_sec=0.1)
    steady_noise = pcm_factory.speech_frame(amp=80)
    for _ in range(15):
        _, is_ep = vad.process_frame(steady_noise, "")
        assert not is_ep
        assert not vad.triggered

    vad.triggered = True
    reached = False
    for frame in pcm_factory.speech_stream(duration_ms=200):
        _, is_ep = vad.process_frame(frame, "talking continuously")
        if is_ep:
            reached = True
            break
    assert reached

def test_local_brain_recall_and_think_strip(monkeypatch, temp_db):
    import json
    import io
    import local_brain
    import memory.store as store
    store.upsert_fact("Fas", "favorite_music", "metallica")
    store.record_turn("default", "user", "remember I love metallica")
    captured = {}

    def fake_urlopen(req, timeout=8.0):
        body = json.loads(req.data.decode("utf-8"))
        captured["system"] = body["messages"][0]["content"]
        resp_obj = {"choices": [{"message": {"content": "<think>internal thought</think>Got it, Fas."}}]}
        return io.BytesIO(json.dumps(resp_obj).encode("utf-8"))

    monkeypatch.setattr(local_brain, "is_server_running", lambda: True)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    reply = local_brain.execute_local_turn("play metallica")
    assert "favorite_music=metallica" in captured["system"]
    assert "<think>" not in reply
    assert "Got it, Fas." in reply

def test_now_playing_and_hallucination_filter(monkeypatch):
    import io, json, sys
    from audio.stt import transcribe_wav_groq
    from audio.vad import DynamicVoiceEndpoint
    import brain
    from tools.os_context import os_context

    res = os_context("now_playing")
    assert isinstance(res, str) and len(res) > 0
    monkeypatch.setattr(sys.modules["tools.os_context"], "os_context", lambda q: "On Spotify, you're listening to Test Song (Playing), Fas.")
    assert "Test Song" in brain._try_fast_action("Can you see which song I was playing on Spotify?")

    vad = DynamicVoiceEndpoint(vad_mode=3, onset_frames=3)
    assert vad.active_speech_frames == 0

    def fake_groq_silence(req, timeout=4.0):
        payload = {"text": "Thank you.", "segments": [{"no_speech_prob": 0.40}]}
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_groq_silence)
    assert transcribe_wav_groq(b"wav", "key") is None

    def fake_groq_real(req, timeout=4.0):
        payload = {"text": "Look at my Spotify.", "segments": [{"no_speech_prob": 0.02}]}
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_groq_real)
    assert transcribe_wav_groq(b"wav", "key") == "Look at my Spotify."

def test_play_it_last_song_and_empty_partial_hallucination(monkeypatch):
    import io, json
    from audio.stt import transcribe_wav_groq
    import brain
    monkeypatch.setenv("DISABLE_MEDIA_UI_AUTOMATION", "1")
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: True)
    monkeypatch.setattr("os.startfile", lambda *args, **kwargs: None)
    monkeypatch.setattr("tools.media._resolve_youtube_video_url", lambda q: f"https://www.youtube.com/watch?v=test_{q}")

    r1 = brain._try_fast_action("Can you play goodbye to a lover again?")
    assert "goodbye to a lover again" in r1.lower()
    r2 = brain._try_fast_action("Play it on Spotify.")
    assert "goodbye to a lover again on spotify" in r2.lower()
    r3 = brain._try_fast_action("It didn't start playing.")
    assert "playback" in r3.lower()

    def fake_groq_echo(req, timeout=4.0):
        payload = {"text": "Thank you.", "segments": [{"no_speech_prob": 0.02, "avg_logprob": -0.1}]}
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_groq_echo)
    assert transcribe_wav_groq(b"wav", "key", partial_hint="") is None

def test_groq_only_online_and_offline_fallback(monkeypatch):
    import urllib.error
    from audio.stt import StreamingTranscriber

    stt = StreamingTranscriber(engine="groq")
    stt.start()
    assert stt.active_engine == "groq"
    assert stt.process is None

    monkeypatch.setenv("GROQ_API_KEY", "test_key")
    monkeypatch.setenv("STT_GEMINI_FALLBACK", "0")
    monkeypatch.setattr("audio.stt._local_offline_transcribe" if False else "urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    called = {}
    monkeypatch.setattr(stt, "_local_offline_transcribe", lambda pcm: called.setdefault("offline", "local fallback text"))
    res = stt.transcribe_hybrid(b"\x01\x00" * 2400)
    assert res == "local fallback text"
    assert called["offline"] == "local fallback text"

def test_groq_no_prompt_hallucination_and_noisy_ambient_vad(monkeypatch, pcm_factory):
    import io, json
    from audio.stt import StreamingTranscriber
    from audio.vad import DynamicVoiceEndpoint

    captured = {}

    def fake_groq_thank_so_much(req, timeout=4.0):
        captured["body"] = req.data
        payload = {"text": "Thank you so much.", "segments": [{"no_speech_prob": 0.01, "avg_logprob": -0.1}]}
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setenv("GROQ_API_KEY", "test_key")
    monkeypatch.setattr("urllib.request.urlopen", fake_groq_thank_so_much)
    stt = StreamingTranscriber(engine="groq")
    stt.start()
    assert stt.transcribe_hybrid(b"\x01\x00" * 2400) == ""
    assert b'name="prompt"' not in captured["body"]
    assert b"Fas, Mike, Spotify" not in captured["body"]

    vad = DynamicVoiceEndpoint(vad_mode=3, onset_frames=5)
    monkeypatch.setattr(vad.vad, "is_speech", lambda f, sr: True)
    ambient = pcm_factory.speech_frame(amp=400)
    for _ in range(30):
        _, is_ep = vad.process_frame(ambient, "")
        assert not vad.triggered
        assert not is_ep
    assert vad.noise_floor > 200
