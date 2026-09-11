from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import pytest

from teu_voice.emotions import EmotionSegment
from teu_voice.jobs import JobManager, JobQueueFull


def make_wav(path: Path, duration: float = 0.1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(b"\x00\x00" * int(duration * 8_000))


def wait_for_terminal(manager: JobManager, job_id: str) -> dict[str, object]:
    for _ in range(200):
        payload = manager.get_public(job_id)
        assert payload is not None
        if payload["status"] in {"done", "error", "cancelled"}:
            return payload
        time.sleep(0.005)
    raise AssertionError("job did not reach a terminal state")


class BlockingEngine:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def availability(self) -> tuple[bool, str]:
        return True, "ready"

    def synthesize(self, text: str, output_path: Path, **_: object) -> None:
        self.started.set()
        assert self.release.wait(timeout=2)
        make_wav(output_path)


def test_queue_has_a_bounded_admission_limit(tmp_path: Path) -> None:
    engine = BlockingEngine()
    manager = JobManager(engine, tmp_path, max_pending_jobs=1)
    try:
        first = manager.submit(
            text="một",
            performance_text="một",
            engine_segments=(EmotionSegment("một"),),
            emotion_tags=(),
            warnings=(),
            speed=1.0,
            reference_path=None,
            builtin_voice="Adam",
            denoise=False,
        )
        assert engine.started.wait(timeout=1)
        with pytest.raises(JobQueueFull):
            manager.submit(
                text="hai",
                performance_text="hai",
                engine_segments=(EmotionSegment("hai"),),
                emotion_tags=(),
                warnings=(),
                speed=1.0,
                reference_path=None,
                builtin_voice="Adam",
                denoise=False,
            )
        engine.release.set()
        assert wait_for_terminal(manager, first.id)["status"] == "done"
    finally:
        engine.release.set()
        manager.close()


class PartialFailureEngine:
    def availability(self) -> tuple[bool, str]:
        return True, "ready"

    def synthesize(self, text: str, output_path: Path, **_: object) -> None:
        output_path.write_bytes(b"partial audio")
        raise RuntimeError("private model path and internal details")


def test_failed_job_removes_partial_audio_and_sanitizes_error(tmp_path: Path) -> None:
    manager = JobManager(PartialFailureEngine(), tmp_path)
    try:
        job = manager.submit(
            text="thử",
            performance_text="thử",
            engine_segments=(EmotionSegment("thử"),),
            emotion_tags=(),
            warnings=(),
            speed=1.0,
            reference_path=None,
            builtin_voice="Adam",
            denoise=False,
        )
        payload = wait_for_terminal(manager, job.id)
        assert payload["status"] == "error"
        assert "private model path" not in str(payload["error"])
        assert list(tmp_path.glob("*.wav")) == []
    finally:
        manager.close()
