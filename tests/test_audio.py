import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from teu_voice.audio import (
    AudioValidationError,
    inspect_wav,
    prepare_clone_reference,
    validate_reference,
)


def make_wav(path: Path, duration: float, sample_rate: int = 8_000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * int(duration * sample_rate))


def make_speech_wav(path: Path, duration: float, sample_rate: int = 48_000, amplitude: float = 0.35) -> None:
    timeline = np.arange(int(duration * sample_rate), dtype=np.float32) / sample_rate
    speech = (amplitude * np.sin(2 * np.pi * 180 * timeline)).astype(np.float32)
    sf.write(str(path), speech, sample_rate, subtype="PCM_16")


def test_inspect_and_validate_reference(tmp_path: Path) -> None:
    path = tmp_path / "voice.wav"
    make_wav(path, 4.25)
    info = inspect_wav(path)
    assert info.duration_seconds == 4.25
    assert info.channels == 1
    assert info.sample_width_bits == 16
    assert validate_reference(path) == info


@pytest.mark.parametrize("duration", [1.0, 9.0])
def test_reference_duration_window(tmp_path: Path, duration: float) -> None:
    path = tmp_path / "voice.wav"
    make_wav(path, duration)
    with pytest.raises(AudioValidationError):
        validate_reference(path)


def test_raw_upload_allows_longer_source(tmp_path: Path) -> None:
    path = tmp_path / "long.wav"
    make_wav(path, 20.0)
    info = validate_reference(path, strict_duration=False)
    assert info.duration_seconds == 20.0


def test_invalid_wav(tmp_path: Path) -> None:
    path = tmp_path / "not.wav"
    path.write_text("not audio", encoding="utf-8")
    with pytest.raises(AudioValidationError):
        inspect_wav(path)


def test_reference_rejects_unsupported_sample_rate(tmp_path: Path) -> None:
    path = tmp_path / "low-rate.wav"
    make_wav(path, 4.0, sample_rate=4_000)
    with pytest.raises(AudioValidationError, match="Sample rate"):
        validate_reference(path)


def test_prepare_clone_reference_resamples_and_normalizes(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    destination = tmp_path / "prepared.wav"
    make_speech_wav(source, 5.0, sample_rate=22_050, amplitude=0.2)

    info = prepare_clone_reference(source, destination)

    assert destination.exists()
    assert info.sample_rate == 48_000
    assert info.channels == 1
    assert 3.0 <= info.duration_seconds <= 8.0
    audio, sr = sf.read(str(destination), dtype="float32")
    assert sr == 48_000
    assert float(np.max(np.abs(audio))) == pytest.approx(10 ** (-3.0 / 20), rel=0.08)


def test_prepare_clone_reference_accepts_hot_clipped_peak(tmp_path: Path) -> None:
    source = tmp_path / "hot.wav"
    destination = tmp_path / "prepared-hot.wav"
    make_speech_wav(source, 5.0, sample_rate=48_000, amplitude=1.05)

    info = prepare_clone_reference(source, destination)

    assert destination.exists()
    assert 3.0 <= info.duration_seconds <= 8.0
    audio, _sr = sf.read(str(destination), dtype="float32")
    assert float(np.max(np.abs(audio))) == pytest.approx(10 ** (-3.0 / 20), rel=0.08)


def test_prepare_clone_reference_picks_dense_window_from_long_clip(tmp_path: Path) -> None:
    source = tmp_path / "long.wav"
    destination = tmp_path / "window.wav"
    sample_rate = 48_000
    silence = np.zeros(int(sample_rate * 4.0), dtype=np.float32)
    timeline = np.arange(int(sample_rate * 6.5), dtype=np.float32) / sample_rate
    speech = (0.4 * np.sin(2 * np.pi * 170 * timeline)).astype(np.float32)
    trailing = np.zeros(int(sample_rate * 5.0), dtype=np.float32)
    sf.write(str(source), np.concatenate((silence, speech, trailing)), sample_rate, subtype="PCM_16")

    info = prepare_clone_reference(source, destination)

    assert 6.0 <= info.duration_seconds <= 8.0
