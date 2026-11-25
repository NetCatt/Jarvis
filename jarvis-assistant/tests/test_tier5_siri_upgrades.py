import io
import json
import math
import struct
import urllib.error


def test_groq_high_reasoning_tool_calling_and_offline_fallback(monkeypatch, temp_db):
    import brain
    import local_brain

    captured = {}
    calls = {"n": 0}

    def fake_groq(messages, tools=None, model=None, max_tokens=384):
        calls["n"] += 1
        captured["model"] = model
        captured["effort"] = "high"
        if calls["n"] == 1:
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_volume", "arguments": "{}"},
                        }],
                    }
                }]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "Volume is 50%, Fas."}}]}

    monkeypatch.setenv("ROUTING_MODE", "groq_hybrid")
    monkeypatch.setenv("GROQ_API_KEY", "test_groq")
    monkeypatch.setenv("GROQ_BRAIN_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setenv("GROQ_REASONING_EFFORT", "high")
    monkeypatch.setattr(brain, "_call_groq_chat", fake_groq)
    monkeypatch.setitem(brain.TOOL_MAP, "get_volume", lambda: "Current master volume is at 50%.")

    res = brain.converse("siri_test", "check my volume")
    assert "50%" in res
    assert captured["model"] == "qwen/qwen3.8-27b"

    monkeypatch.setattr(brain, "_call_groq_chat", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    monkeypatch.setattr(brain, "_call_gemini_rest", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    monkeypatch.setattr(local_brain, "execute_local_turn", lambda u, h=None: "Offline Qwen high reasoning active, Fas.")
    fallback_res = brain.converse("siri_test", "explain the architecture")
    assert "Offline Qwen" in fallback_res


def test_fast_action_song_regex_fixes_and_default_spotify(monkeypatch):
    import brain
    monkeypatch.setenv("DISABLE_MEDIA_UI_AUTOMATION", "1")
    monkeypatch.setenv("DEFAULT_MUSIC_PLATFORM", "spotify")
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, **k: opened.append(url) or True)
    monkeypatch.setattr("os.startfile", lambda target: opened.append(target))
    monkeypatch.setattr("tools.media._resolve_youtube_video_url", lambda q: f"https://www.youtube.com/watch?v={q}")

    r1 = brain._try_fast_action("open a song on youtube goodbye to a lover")
    assert "goodbye to a lover" in r1.lower() and "youtube" in r1.lower()
    r2 = brain._try_fast_action("start playing bohemian rhapsody")
    assert "bohemian rhapsody" in r2.lower() and "spotify" in r2.lower()
    assert any("spotify:search:bohemian%20rhapsody" in x for x in opened)
    r3 = brain._try_fast_action("play goodbye to a lover again on spotify")
    assert "goodbye to a lover again" in r3.lower()

def test_win64_sendinput_struct_size():
    import ctypes
    from PIL import Image, ImageDraw
    from tools.media import _find_green_play_in_image
    from tools.os_input import _INPUT
    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(_INPUT) == expected
    img = Image.new("RGB", (600, 400), (18, 18, 18))
    ImageDraw.Draw(img).ellipse((80, 140, 130, 190), fill=(30, 215, 96))
    hit = _find_green_play_in_image(img)
    assert hit is not None and 90 <= hit[0] <= 120 and 150 <= hit[1] <= 180


def test_daily_timers_and_quick_answer(monkeypatch):
    from tools.daily import cancel_timer, list_timers, quick_answer, set_timer
    import urllib.request

    res_set = set_timer("2 minutes", label="coffee")
    assert "2 minutes" in res_set
    assert "coffee" in list_timers().lower()
    assert "cancelled" in cancel_timer("coffee").lower()

    assert quick_answer("what is 15% of 340") == "51"
    assert "it's" in quick_answer("what time is it").lower()

    def fake_urlopen(req, timeout=3.5, context=None):
        url = req.full_url
        if "wttr.in" in url:
            return io.BytesIO(b"Clear, +26C, feels like +27C")
        return io.BytesIO(json.dumps({"AbstractText": "Berlin is the capital of Germany. Second sentence."}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    w = quick_answer("what's the weather in Dhaka")
    assert "Clear" in w and "26C" in w
    ddg = quick_answer("capital of Germany")
    assert ddg == "Berlin is the capital of Germany."


def test_vad_highpass_and_tts_barge_in(monkeypatch):
    import collections
    import audio.tts as tts_mod
    from audio.tts import _chunk_speech_text, check_barge_in, is_speaking, stop_speaking
    from audio.vad import DynamicVoiceEndpoint, frame_rms

    vad = DynamicVoiceEndpoint(vad_mode=3)
    dc_low = struct.pack("<320h", *[1200 for _ in range(320)])
    out_dc = vad._highpass_frame(dc_low)
    assert frame_rms(out_dc[-320:]) < 150

    sr = 16000
    tone_400 = struct.pack("<320h", *[int(14000 * math.sin(2 * math.pi * 400 * i / sr)) for i in range(320)])
    out_400 = vad._highpass_frame(tone_400)
    assert frame_rms(out_400) > 8500

    tts_mod._IS_SPEAKING = True
    q = collections.deque([tone_400] * 4)
    preroll = collections.deque(maxlen=10)
    barge_buf = collections.deque(maxlen=6)
    monkeypatch.setenv("ENABLE_BARGE_IN", "0")
    barged_off, _ = check_barge_in(q, preroll, barge_buf, 0, 100.0, 1400.0, frame_rms)
    assert not barged_off and len(q) == 0

    monkeypatch.setenv("ENABLE_BARGE_IN", "1")
    q = collections.deque([tone_400] * 4)
    barged, hits = check_barge_in(q, preroll, barge_buf, 0, 100.0, 1400.0, frame_rms)
    assert barged and hits == 0 and len(preroll) == 4
    chunks = _chunk_speech_text("First sentence here. " * 20, limit=120)
    assert len(chunks) > 1
    stop_speaking()
    assert not is_speaking()
