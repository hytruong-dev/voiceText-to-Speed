from __future__ import annotations

import contextlib
import wave
from dataclasses import asdict, dataclass
from pathlib import Path


class AudioValidationError(ValueError):
    """Raised when a reference clip is unsuitable for voice cloning."""


@dataclass(frozen=True, slots=True)
class AudioInfo:
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bits: int
    frames: int

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def inspect_wav(path: Path) -> AudioInfo:
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wav:
            frames = wav.getnframes()
            sample_rate = wav.getframerate()
            if sample_rate <= 0:
                raise AudioValidationError("Sample rate của WAV không hợp lệ.")
            return AudioInfo(
                duration_seconds=round(frames / sample_rate, 3),
                sample_rate=sample_rate,
                channels=wav.getnchannels(),
                sample_width_bits=wav.getsampwidth() * 8,
                frames=frames,
            )
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioValidationError("Tệp phải là WAV PCM hợp lệ.") from exc


def validate_reference(path: Path, *, strict_duration: bool = True) -> AudioInfo:
    info = inspect_wav(path)
    if info.channels not in (1, 2):
        raise AudioValidationError("Mẫu giọng chỉ nên có một hoặc hai kênh âm thanh.")
    if not 8_000 <= info.sample_rate <= 192_000:
        raise AudioValidationError("Sample rate của mẫu giọng phải từ 8 đến 192 kHz.")
    if info.sample_width_bits not in (16, 24, 32):
        raise AudioValidationError("Mẫu giọng cần là WAV PCM 16/24/32-bit.")
    if strict_duration and not 3.0 <= info.duration_seconds <= 8.0:
        raise AudioValidationError(
            "Mẫu giọng nên dài từ 3 đến 8 giây để clone ổn định."
        )
    return info
