from __future__ import annotations

import contextlib
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


class AudioValidationError(ValueError):
    """Raised when a reference clip is unsuitable for voice cloning."""


CLONE_SAMPLE_RATE = 48_000
CLONE_MIN_SECONDS = 3.0
CLONE_MAX_SECONDS = 8.0
CLONE_PREFERRED_SECONDS = 7.2
CLONE_TARGET_PEAK = 10 ** (-2.0 / 20)
_RAW_UPLOAD_MAX_SECONDS = 60.0
_SPEECH_ABS_THRESHOLD = 0.010
_FRAME_MS = 20


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
    if strict_duration and not CLONE_MIN_SECONDS <= info.duration_seconds <= CLONE_MAX_SECONDS:
        raise AudioValidationError(
            "Mẫu giọng nên dài từ 3 đến 8 giây để clone ổn định."
        )
    if not strict_duration and not CLONE_MIN_SECONDS <= info.duration_seconds <= _RAW_UPLOAD_MAX_SECONDS:
        raise AudioValidationError(
            "Mẫu giọng nên dài từ 3 đến 60 giây; hệ thống sẽ tự chọn cửa sổ 3–8 giây tốt nhất."
        )
    return info


def _fade_edges(audio: np.ndarray, sample_rate: int, milliseconds: int = 12) -> np.ndarray:
    fade_samples = min(int(sample_rate * milliseconds / 1000), max(1, len(audio) // 2))
    if fade_samples <= 1:
        return audio
    result = audio.copy()
    ramp = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    result[:fade_samples] *= ramp
    result[-fade_samples:] *= ramp[::-1]
    return result


def _best_clone_window(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Keep the densest continuous speech window inside VieNeu's 3–8 s clone range."""

    if not len(audio):
        return audio
    preferred = int(sample_rate * CLONE_PREFERRED_SECONDS)
    maximum = int(sample_rate * CLONE_MAX_SECONDS)
    minimum = int(sample_rate * CLONE_MIN_SECONDS)

    active = np.flatnonzero(np.abs(audio) > _SPEECH_ABS_THRESHOLD)
    if active.size:
        start = max(0, int(active[0]) - int(sample_rate * 0.08))
        end = min(len(audio), int(active[-1]) + 1 + int(sample_rate * 0.12))
        audio = audio[start:end]

    if len(audio) <= maximum:
        if len(audio) < minimum:
            raise AudioValidationError(
                "Phần tiếng nói thực trong mẫu còn ngắn hơn 3 giây; hãy thu lại liền mạch hơn."
            )
        return audio

    frame = max(1, int(sample_rate * _FRAME_MS / 1000))
    window = preferred if preferred <= len(audio) else maximum
    window = min(window, len(audio))
    hop = max(1, frame * 2)
    best_start = 0
    best_score = -1.0
    for start in range(0, len(audio) - window + 1, hop):
        chunk = audio[start : start + window]
        magnitude = np.abs(chunk)
        speech = magnitude > _SPEECH_ABS_THRESHOLD
        speech_ratio = float(np.mean(speech))
        # Prefer continuous speech with rich dynamics (identity lives in formants).
        rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
        dynamic = float(np.std(chunk, dtype=np.float64))
        score = speech_ratio * (0.65 * rms + 0.35 * dynamic)
        if score > best_score:
            best_score = score
            best_start = start
    return audio[best_start : best_start + window].copy()


def prepare_clone_reference(source: Path, destination: Path) -> AudioInfo:
    """Normalize a WAV into a mono 48 kHz clip optimized for VieNeu identity cloning."""

    import soundfile as sf
    import soxr

    try:
        wav, sample_rate = sf.read(str(source), dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001 - surface as validation error
        raise AudioValidationError("Không đọc được mẫu giọng WAV.") from exc

    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = np.mean(wav, axis=1, dtype=np.float32)
    if not len(wav):
        raise AudioValidationError("Mẫu giọng rỗng.")

    wav = wav - float(np.mean(wav))
    if sample_rate != CLONE_SAMPLE_RATE:
        wav = np.asarray(
            soxr.resample(wav, sample_rate, CLONE_SAMPLE_RATE),
            dtype=np.float32,
        )
        sample_rate = CLONE_SAMPLE_RATE

    wav = _best_clone_window(wav, sample_rate)
    peak = float(np.max(np.abs(wav)))
    if peak < 0.02:
        raise AudioValidationError(
            "Mẫu giọng quá nhỏ. Hãy thu gần mic hơn hoặc tăng volume trước khi clone."
        )
    if peak >= 0.985:
        raise AudioValidationError(
            "Mẫu giọng bị clipping. Hãy hạ gain mic rồi thu lại để giữ đúng màu giọng."
        )

    wav *= CLONE_TARGET_PEAK / peak
    # Light high-shelf tilt keeps consonants clear without dulling the timbre.
    if len(wav) > 8:
        tilted = wav.copy()
        tilted[1:] += 0.04 * (wav[1:] - wav[:-1])
        peak_tilt = float(np.max(np.abs(tilted)))
        if peak_tilt > 1e-8:
            tilted *= min(1.0, CLONE_TARGET_PEAK / peak_tilt)
        wav = tilted
    wav = _fade_edges(wav, sample_rate, milliseconds=6)

    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), wav, sample_rate, subtype="PCM_16")
    return validate_reference(destination, strict_duration=True)
