from pathlib import Path

import numpy as np
import pytest

from teu_voice.config import Settings
from teu_voice.emotions import EmotionSegment
from teu_voice.engine import (
    VieneuEngine,
    _group_segments_for_natural_delivery,
    _master_speech,
    _safe_audio_effects,
    _sampling_temperature,
    _style_for_tags,
    _trim_generated_edges,
)


def test_reference_temp_is_redirected_inside_project(tmp_path: Path) -> None:
    cfg = Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        cache_dir=tmp_path / ".cache",
        default_reference=tmp_path / "data" / "voice_reference.wav",
    )

    class FakeModel:
        @staticmethod
        def _preclean_reference_audio(ref_audio, *, top_db=24, out_path=None):
            assert top_db == 24
            path = Path(out_path)
            path.write_bytes(Path(ref_audio).read_bytes())
            return str(path)

    source = tmp_path / "source.wav"
    source.write_bytes(b"voice")
    model = FakeModel()
    engine = VieneuEngine(cfg)
    engine._redirect_reference_temp(model)

    generated = Path(model._preclean_reference_audio(source))
    assert generated.parent == cfg.cache_dir / "vieneu" / "tmp"
    assert generated.read_bytes() == b"voice"


def test_speed_effect_changes_duration_without_overdriving_peak() -> None:
    sample_rate = 48_000
    timeline = np.arange(sample_rate, dtype=np.float32) / sample_rate
    source = (0.35 * np.sin(2 * np.pi * 220 * timeline)).astype(np.float32)

    slow = _safe_audio_effects(
        source,
        sample_rate,
        speed=0.8,
        pitch_steps=0.0,
        gain_db=0.0,
    )
    fast = _safe_audio_effects(
        source,
        sample_rate,
        speed=1.25,
        pitch_steps=0.0,
        gain_db=8.0,
    )

    assert len(slow) > len(source) > len(fast)
    assert np.max(np.abs(fast)) <= 10 ** (-1.5 / 20) + 1e-5


def test_pitch_shift_preserves_duration_and_rough_loudness() -> None:
    sample_rate = 48_000
    timeline = np.arange(sample_rate // 2, dtype=np.float32) / sample_rate
    source = (0.2 * np.sin(2 * np.pi * 180 * timeline)).astype(np.float32)
    shifted = _safe_audio_effects(
        source,
        sample_rate,
        speed=1.0,
        pitch_steps=1.25,
        gain_db=0.0,
    )
    source_rms = np.sqrt(np.mean(source**2))
    shifted_rms = np.sqrt(np.mean(shifted**2))

    assert len(shifted) == len(source)
    assert shifted_rms == pytest.approx(source_rms, rel=0.08)


def test_semantic_tags_share_context_until_an_explicit_pause() -> None:
    segments = (
        EmotionSegment("Mở đầu.", tag_ids=("warm",)),
        EmotionSegment("[cười] Câu đùa!", tag_ids=("chuckle",)),
        EmotionSegment("Đợi một nhịp.", tag_ids=("pause_short",), pause_before_ms=200),
        EmotionSegment("Câu chốt.", tag_ids=("deadpan",)),
    )

    groups = _group_segments_for_natural_delivery(segments)

    assert len(groups) == 2
    assert groups[0].engine_text == "Mở đầu. [cười] Câu đùa!"
    assert groups[0].pause_before_ms == 0
    assert groups[1].engine_text == "Đợi một nhịp. Câu chốt."
    assert groups[1].pause_before_ms == 200
    assert groups[0].tag_ids == ("warm", "chuckle")


def test_style_selection_uses_dominant_then_most_recent_direction() -> None:
    assert _style_for_tags(("funny", "chuckle", "excited")) == "funny"
    assert _style_for_tags(("funny", "excited")) == "excited"
    assert _style_for_tags(("calm", "slow")) is None


def test_clone_sampling_stays_identity_first() -> None:
    assert _sampling_temperature((), cloning=True) == 0.5
    assert _sampling_temperature((0.8, 0.86), cloning=True) == 0.51
    assert _sampling_temperature((0.8,), cloning=False) == 0.8
    assert 0.42 <= _sampling_temperature((0.95,), cloning=True) <= 0.62


def test_generated_edge_trim_removes_padding_but_keeps_a_guard() -> None:
    sample_rate = 48_000
    padding = np.zeros(round(sample_rate * 0.25), dtype=np.float32)
    timeline = np.arange(round(sample_rate * 0.4), dtype=np.float32) / sample_rate
    speech = (0.25 * np.sin(2 * np.pi * 180 * timeline)).astype(np.float32)
    source = np.concatenate((padding, speech, padding))

    trimmed = _trim_generated_edges(source, sample_rate)

    assert len(speech) < len(trimmed) < len(source)
    assert np.max(np.abs(trimmed)) == pytest.approx(np.max(np.abs(speech)), rel=1e-5)


def test_generated_edge_trim_preserves_quiet_breath_tails() -> None:
    sample_rate = 48_000
    padding = np.zeros(round(sample_rate * 0.2), dtype=np.float32)
    breath = np.linspace(0.0001, 0.002, round(sample_rate * 0.08), dtype=np.float32)
    speech = np.full(round(sample_rate * 0.2), 0.2, dtype=np.float32)
    source = np.concatenate((padding, breath, speech, breath[::-1], padding))

    trimmed = _trim_generated_edges(source, sample_rate)

    assert len(trimmed) >= len(breath) * 2 + len(speech)
    assert trimmed[round(sample_rate * 0.02)] < 0.01


def test_whole_program_mastering_raises_average_without_clipping() -> None:
    sample_rate = 48_000
    timeline = np.arange(sample_rate, dtype=np.float32) / sample_rate
    source = (0.07 * np.sin(2 * np.pi * 180 * timeline)).astype(np.float32)
    source[1_000] = 0.9

    mastered = _master_speech(source)

    assert np.sqrt(np.mean(mastered**2)) > np.sqrt(np.mean(source**2))
    assert np.max(np.abs(mastered)) <= 10 ** (-1.5 / 20) + 1e-6


def test_vieneu_engine_infers_continuously_between_explicit_pauses(tmp_path: Path) -> None:
    cfg = Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        cache_dir=tmp_path / ".cache",
        default_reference=tmp_path / "data" / "voice_reference.wav",
    )

    class FakeModel:
        sample_rate = 48_000

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, float]] = []

        def infer(self, text: str, *, voice: str, temperature: float, **kwargs) -> np.ndarray:
            self.calls.append((text, voice, temperature))
            timeline = np.arange(4_800, dtype=np.float32) / self.sample_rate
            speech = (0.1 * np.sin(2 * np.pi * 180 * timeline)).astype(np.float32)
            return np.concatenate((np.zeros(1_200, dtype=np.float32), speech, np.zeros(1_200, dtype=np.float32)))

        @staticmethod
        def save(audio: np.ndarray, path: str) -> None:
            Path(path).write_bytes(audio.tobytes())

    model = FakeModel()
    engine = VieneuEngine(cfg)
    engine._model = model
    output = tmp_path / "result.wav"

    engine.synthesize(
        (
            EmotionSegment("Câu một.", tag_ids=("happy",), speed_multiplier=1.1),
            EmotionSegment("Câu hai!", tag_ids=("excited",), pitch_steps=1.0),
            EmotionSegment("Câu ba.", tag_ids=("pause_short",), pause_before_ms=200),
        ),
        output,
        reference_path=None,
        builtin_voice="Adam",
        denoise=False,
        speed=1.0,
    )

    assert output.exists()
    assert model.calls == [
        ("Câu một. Câu hai!", "Adam", 0.8),
        ("Câu ba.", "Adam", 0.8),
    ]


def test_style_transfer_combines_base_speaker_with_emotional_codes(tmp_path: Path) -> None:
    cfg = Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        cache_dir=tmp_path / ".cache",
        default_reference=tmp_path / "data" / "voice_reference.wav",
    )
    style_dir = cfg.data_dir / "style_references"
    style_dir.mkdir(parents=True)
    (style_dir / "excited.wav").write_bytes(b"local style")

    class FakeStyleModel:
        sample_rate = 48_000

        def __init__(self) -> None:
            self.voice: object = None

        @staticmethod
        def _resolve_ref(voice, ref_audio, denoise, use_ref_codes):
            assert not denoise
            assert use_ref_codes
            if ref_audio is not None:
                return np.array([9.0]), np.array([22])
            assert voice == "Adam"
            return np.array([1.0]), np.array([11])

        def infer(self, text: str, *, voice: object, temperature: float, **kwargs) -> np.ndarray:
            self.voice = voice
            return np.full(4_800, 0.05, dtype=np.float32)

        @staticmethod
        def save(audio: np.ndarray, path: str) -> None:
            Path(path).write_bytes(audio.tobytes())

    model = FakeStyleModel()
    engine = VieneuEngine(cfg)
    engine._model = model
    engine.synthesize(
        (EmotionSegment("Tin vui!", tag_ids=("excited",)),),
        tmp_path / "styled.wav",
        reference_path=None,
        builtin_voice="Adam",
        denoise=False,
        style_transfer=True,
    )

    assert isinstance(model.voice, dict)
    assert np.array_equal(model.voice["speaker_emb"], np.array([1.0]))
    assert np.array_equal(model.voice["codes"], np.array([22]))

