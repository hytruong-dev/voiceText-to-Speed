from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .audio import inspect_wav
from .emotions import EmotionSegment, natural_render_group_count
from .engine import SpeechEngine


logger = logging.getLogger("teu_voice.jobs")


class JobQueueFull(RuntimeError):
    """Raised when the local inference queue has reached its admission limit."""


@dataclass(slots=True)
class SynthesisJob:
    id: str
    text: str
    performance_text: str
    engine_segments: tuple[EmotionSegment, ...]
    emotion_tags: tuple[str, ...]
    warnings: tuple[str, ...]
    speed: float
    reference_path: Path | None
    builtin_voice: str
    denoise: bool
    style_transfer: bool = False
    cleanup_reference: bool = False
    status: str = "queued"
    stage: str = "Đang xếp hàng"
    error: str | None = None
    output_name: str | None = None
    duration_seconds: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("engine_segments", None)
        payload.pop("reference_path", None)
        payload.pop("cleanup_reference", None)
        payload["effects"] = {
            "speed": self.speed,
            "segment_count": len(self.engine_segments),
            "wrapper_group_count": natural_render_group_count(self.engine_segments),
            "style_transfer": self.style_transfer,
        }
        if self.output_name:
            payload["audio_url"] = f"/audio/{self.output_name}"
        else:
            payload["audio_url"] = None
        return payload


class JobManager:
    def __init__(
        self,
        engine: SpeechEngine,
        output_dir: Path,
        *,
        max_pending_jobs: int = 4,
        max_retained_jobs: int = 100,
    ) -> None:
        self.engine = engine
        self.output_dir = output_dir
        self.max_pending_jobs = max_pending_jobs
        self.max_retained_jobs = max_retained_jobs
        self._jobs: dict[str, SynthesisJob] = {}
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="teu-voice")

    def submit(
        self,
        *,
        text: str,
        performance_text: str,
        engine_segments: tuple[EmotionSegment, ...],
        emotion_tags: tuple[str, ...],
        warnings: tuple[str, ...],
        speed: float,
        reference_path: Path | None,
        builtin_voice: str,
        denoise: bool,
        style_transfer: bool = False,
        cleanup_reference: bool = False,
    ) -> SynthesisJob:
        job_id = uuid.uuid4().hex
        job = SynthesisJob(
            id=job_id,
            text=text,
            performance_text=performance_text,
            engine_segments=engine_segments,
            emotion_tags=emotion_tags,
            warnings=warnings,
            speed=speed,
            reference_path=reference_path,
            builtin_voice=builtin_voice,
            denoise=denoise,
            style_transfer=style_transfer,
            cleanup_reference=cleanup_reference,
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("Hàng đợi đã đóng.")
            active = sum(
                job.status in {"queued", "running"} for job in self._jobs.values()
            )
            if active >= self.max_pending_jobs:
                raise JobQueueFull(
                    "Hàng đợi local đang đầy. Vui lòng chờ một lượt hoàn tất."
                )
            self._evict_completed_locked()
            self._jobs[job_id] = job
            future = self._executor.submit(self._run, job_id)
            self._futures[job_id] = future
        return job

    def get(self, job_id: str) -> SynthesisJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_public(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.public_dict()

    def _evict_completed_locked(self) -> None:
        overflow = len(self._jobs) - self.max_retained_jobs + 1
        if overflow <= 0:
            return
        completed = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in {"done", "error", "cancelled"}
        ]
        for job_id in completed[:overflow]:
            self._jobs.pop(job_id, None)
            self._futures.pop(job_id, None)

    def _update(self, job_id: str, **changes: object) -> SynthesisJob:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            return job

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None:
            return
        output_name = f"teu-voice-{job_id[:12]}.wav"
        output_path = self.output_dir / output_name
        temporary_output = self.output_dir / f".{output_name}.part.wav"
        try:
            available, detail = self.engine.availability()
            if not available:
                raise RuntimeError(detail)
            self._update(
                job_id,
                status="running",
                stage=(
                    "Đang dựng "
                    f"{natural_render_group_count(job.engine_segments)} nhóm tổng hợp"
                ),
            )
            self.engine.synthesize(
                job.engine_segments,
                temporary_output,
                reference_path=job.reference_path,
                builtin_voice=job.builtin_voice,
                denoise=job.denoise,
                speed=job.speed,
                style_transfer=job.style_transfer,
            )
            if not temporary_output.exists() or temporary_output.stat().st_size == 0:
                raise RuntimeError("Engine không tạo được tệp âm thanh.")
            info = inspect_wav(temporary_output)
            temporary_output.replace(output_path)
            self._update(
                job_id,
                status="done",
                stage="Hoàn tất",
                output_name=output_name,
                duration_seconds=info.duration_seconds,
            )
        except Exception as exc:  # The worker must always surface model errors to the UI.
            temporary_output.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            logger.exception("Synthesis job %s failed", job_id)
            self._update(
                job_id,
                status="error",
                stage="Không thể tạo giọng",
                error="Engine local gặp lỗi khi tạo giọng. Chi tiết đã được ghi ở terminal.",
            )
        finally:
            if job.cleanup_reference and job.reference_path is not None:
                job.reference_path.unlink(missing_ok=True)

    def close(self) -> None:
        cleanup_paths: list[Path] = []
        with self._lock:
            self._closed = True
            for job_id, future in self._futures.items():
                job = self._jobs.get(job_id)
                if job is None or job.status != "queued":
                    continue
                if future.cancel():
                    job.status = "cancelled"
                    job.stage = "Đã hủy khi tắt ứng dụng"
                    job.error = "Lượt tạo giọng đã bị hủy khi ứng dụng dừng."
                    if job.cleanup_reference and job.reference_path is not None:
                        cleanup_paths.append(job.reference_path)
        for path in cleanup_paths:
            path.unlink(missing_ok=True)
        self._executor.shutdown(wait=False, cancel_futures=True)
