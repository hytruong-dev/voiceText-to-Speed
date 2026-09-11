import wave
from pathlib import Path

import pytest

from teu_voice.audio import AudioValidationError, inspect_wav, validate_reference


def make_wav(path: Path, duration: float, sample_rate: int = 8_000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * int(duration * sample_rate))


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
