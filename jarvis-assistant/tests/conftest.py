import math
import os
import random
import struct
import tempfile
import psutil
import pytest

import memory.store as store


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_val = os.environ.get("MEMORY_DB_PATH")
    os.environ["MEMORY_DB_PATH"] = path

    if store._CONN is not None:
        store._CONN.close()
    store._CONN = None

    store.init_db()
    yield path

    if store._CONN is not None:
        store._CONN.close()
        store._CONN = None

    if old_val is not None:
        os.environ["MEMORY_DB_PATH"] = old_val
    else:
        os.environ.pop("MEMORY_DB_PATH", None)

    for p in [path, f"{path}-wal", f"{path}-shm"]:
        if os.path.exists(p):
            try:
                os.unlink(p)
            except OSError:
                pass


class PCMFactory:
    @staticmethod
    def silence_frame(sample_rate: int = 16000, frame_ms: int = 20) -> bytes:
        samples_per_frame = int(sample_rate * (frame_ms / 1000))
        return bytes(samples_per_frame * 2)

    @staticmethod
    def speech_frame(sample_rate: int = 16000, frame_ms: int = 20, freq: int = 400, amp: int = 14000) -> bytes:
        samples_per_frame = int(sample_rate * (frame_ms / 1000))
        samples = [
            int(amp * math.sin(2 * math.pi * freq * i / sample_rate))
            for i in range(samples_per_frame)
        ]
        return struct.pack(f"<{samples_per_frame}h", *samples)

    @classmethod
    def speech_stream(cls, duration_ms: int = 400, sample_rate: int = 16000, frame_ms: int = 20) -> list[bytes]:
        frames_count = max(1, duration_ms // frame_ms)
        return [cls.speech_frame(sample_rate, frame_ms) for _ in range(frames_count)]

    @classmethod
    def silence_stream(cls, duration_ms: int = 1000, sample_rate: int = 16000, frame_ms: int = 20) -> list[bytes]:
        frames_count = max(1, duration_ms // frame_ms)
        return [cls.silence_frame(sample_rate, frame_ms) for _ in range(frames_count)]


@pytest.fixture
def pcm_factory():
    return PCMFactory


@pytest.fixture
def assert_rss_budget():
    def _check(limit_mb: float = 45.0):
        rss = psutil.Process().memory_info().rss / (1024 * 1024)
        assert rss < limit_mb, f"RSS budget exceeded: {rss:.2f} MB >= {limit_mb} MB"
        return rss
    return _check
