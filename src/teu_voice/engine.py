from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from .config import Settings
from .emotions import EmotionSegment


MIN_SPEED = 0.75
MAX_SPEED = 1.35
DEFAULT_SPEED = 1.0
_MIN_EFFECTIVE_SPEED = 0.65
_MAX_EFFECTIVE_SPEED = 1.55
_PEAK_CEILING = 10 ** (-1.5 / 20)
_EDGE_TRIM_ABS_THRESHOLD = 2 / 32768
_EDGE_TRIM_GUARD_MS = 24
_MASTER_TARGET_RMS_DB = -16.5
_MASTER_MAX_MAKEUP_DB = 4.0
_LIMITER_KNEE = 10 ** (-4.0 / 20)
_STYLE_TAGS = {
    "excited": frozenset(
        {
            "happy",
            "excited",
            "delighted",
            "giddy",
            "amazed",
            "curious",
            "surprised",
            "mock_gasp",
            "dramatic",
            "nervous",
            "scared",
            "angry",
            "shout",
            "rushed",
            "gasp",
        }
    ),
    "funny": frozenset(
        {
            "funny",
            "teasing",
            "smug",
            "cocky",
            "sarcastic",
            "deadpan",
            "mischievous",
            "laugh",
            "chuckle",
            "giggle",
            "laugh_loud",
            "hearty_laugh",
            "burst_laugh",
        }
    ),
}


class SpeechEngine(Protocol):
    def availability(self) -> tuple[bool, str]: ...

    def synthesize(
        self,
        segments: Sequence[EmotionSegment],
        output_path: Path,
        *,
        reference_path: Path | None,
        builtin_voice: str,
        denoise: bool,
        speed: float = DEFAULT_SPEED,
        style_transfer: bool = False,
    ) -> None: ...


def _safe_audio_effects(
    audio: np.ndarray,
    sample_rate: int,
    *,
    speed: float,
    pitch_steps: float,
    gain_db: float,
    limit_peak: bool = True,
) -> np.ndarray:
    """Apply restrained DSP while preserving the model's perceived level."""

    result = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not len(result):
        return result
    original_rms = float(np.sqrt(np.mean(np.square(result, dtype=np.float64))))
    needs_spectral_dsp = abs(speed - 1.0) > 0.001 or abs(pitch_steps) > 0.01
    if needs_spectral_dsp:
        import librosa

        if abs(pitch_steps) > 0.01:
            result = librosa.effects.pitch_shift(
                result,
                sr=sample_rate,
                n_steps=pitch_steps,
                res_type="soxr_hq",
            )
        if abs(speed - 1.0) > 0.001:
            result = librosa.effects.time_stretch(result, rate=speed)
        result = np.asarray(result, dtype=np.float32)
        processed_rms = float(np.sqrt(np.mean(np.square(result, dtype=np.float64))))
        if original_rms > 1e-8 and processed_rms > 1e-8:
            result *= original_rms / processed_rms

    if abs(gain_db) > 0.01:
        result *= 10 ** (gain_db / 20)
    if limit_peak:
        peak = float(np.max(np.abs(result)))
        if peak > _PEAK_CEILING:
            result *= _PEAK_CEILING / peak
    return np.asarray(result, dtype=np.float32)


def _fade_edges(audio: np.ndarray, sample_rate: int, milliseconds: int = 8) -> np.ndarray:
    fade_samples = min(int(sample_rate * milliseconds / 1000), len(audio) // 2)
    if fade_samples <= 1:
        return audio
    result = audio.copy()
    ramp = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    result[:fade_samples] *= ramp
    result[-fade_samples:] *= ramp[::-1]
    return result


def _trim_generated_edges(
    audio: np.ndarray,
    sample_rate: int,
    *,
    absolute_threshold: float = _EDGE_TRIM_ABS_THRESHOLD,
    guard_ms: int = _EDGE_TRIM_GUARD_MS,
) -> np.ndarray:
    """Remove only digital/near-digital model padding at clip boundaries.

    VieNeu adds its own leading/trailing zero padding to each inference.  Emotion
    tags create several inferences, so leaving that padding in place produces a
    stop-start cadence and then the joiner adds a second pause on top.  A
    relative dB trim can mistake a soft breath for silence when the same clip
    contains a loud exclamation.  VieNeu's padding is actually zero-valued, so
    an absolute PCM-scale threshold is both safer and sufficient.
    """

    result = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(result) < round(sample_rate * 0.08):
        return result

    active = np.flatnonzero(np.abs(result) > absolute_threshold)
    if not active.size:
        return result
    start, end = int(active[0]), int(active[-1]) + 1
    guard = round(sample_rate * guard_ms / 1000)
    start = max(0, start - guard)
    end = min(len(result), end + guard)
    if end - start < round(sample_rate * 0.06):
        return result
    return result[start:end].copy()


@dataclass(frozen=True, slots=True)
class _InferenceGroup:
    """One continuous performance, optionally preceded by an explicit pause."""

    engine_text: str
    pause_before_ms: int = 0
    tag_ids: tuple[str, ...] = ()


def _group_segments_for_natural_delivery(
    segments: Sequence[EmotionSegment],
) -> tuple[_InferenceGroup, ...]:
    """Keep context across semantic tags and split only on deliberate pauses.

    VieNeu derives delivery from the reference and surrounding text. Calling it
    once per ``@tag`` resets that context, which is far more audible than the
    subtle tag DSP. Explicit pause tags remain deterministic boundaries; all
    other directed clauses become one coherent model inference.
    """

    groups: list[_InferenceGroup] = []
    current_text: list[str] = []
    current_tag_ids: list[str] = []
    current_pause_ms = 0

    def flush() -> None:
        nonlocal current_text, current_pause_ms, current_tag_ids
        if current_text:
            groups.append(
                _InferenceGroup(
                    engine_text=" ".join(current_text),
                    pause_before_ms=current_pause_ms,
                    tag_ids=tuple(current_tag_ids),
                )
            )
        current_text = []
        current_tag_ids = []
        current_pause_ms = 0

    for segment in segments:
        if current_text and segment.pause_before_ms:
            flush()
            current_pause_ms = segment.pause_before_ms
        elif not current_text and segment.pause_before_ms:
            current_pause_ms = segment.pause_before_ms
        current_text.append(segment.engine_text)
        current_tag_ids.extend(segment.tag_ids)
    flush()
    return tuple(groups)


def _style_for_tags(tag_ids: Sequence[str]) -> str | None:
    """Pick the dominant available performance reference for one group."""

    scores = {
        style: sum(tag_id in candidates for tag_id in tag_ids)
        for style, candidates in _STYLE_TAGS.items()
    }
    best_style, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score == 0:
        return None
    # A tie follows the most recent relevant direction, which matches how the
    # script compiler scopes successive tags in conversational text.
    winners = {style for style, score in scores.items() if score == best_score}
    if len(winners) > 1:
        for tag_id in reversed(tag_ids):
            for style in winners:
                if tag_id in _STYLE_TAGS[style]:
                    return style
    return best_style


def _master_speech(audio: np.ndarray) -> np.ndarray:
    """Apply restrained whole-program level matching and a soft peak ceiling.

    Per-segment peak normalization makes quiet clauses jump and lets a single
    transient lower an entire line.  Mastering once after assembly keeps the
    relative performance intact.  The 4 dB makeup cap also prevents long pauses
    from causing excessive gain.
    """

    result = np.asarray(audio, dtype=np.float32).reshape(-1).copy()
    if not len(result):
        return result
    rms = float(np.sqrt(np.mean(np.square(result, dtype=np.float64))))
    if rms <= 1e-8:
        return result
    current_rms_db = 20 * np.log10(rms)
    makeup_db = min(_MASTER_MAX_MAKEUP_DB, _MASTER_TARGET_RMS_DB - current_rms_db)
    result *= 10 ** (makeup_db / 20)

    magnitude = np.abs(result)
    limited = magnitude > _LIMITER_KNEE
    if np.any(limited):
        headroom = _PEAK_CEILING - _LIMITER_KNEE
        excess = (magnitude[limited] - _LIMITER_KNEE) / headroom
        result[limited] = np.sign(result[limited]) * (
            _LIMITER_KNEE + headroom * np.tanh(excess)
        )
    return np.asarray(result, dtype=np.float32)


class VieneuEngine:
    """Lazy, serialized adapter around the local VieNeu v3 Turbo model."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._style_codes: dict[str, np.ndarray | None] = {}

    @property
    def style_reference_names(self) -> tuple[str, ...]:
        style_dir = self.settings.data_dir / "style_references"
        return tuple(
            name for name in _STYLE_TAGS if (style_dir / f"{name}.wav").is_file()
        )

    def availability(self) -> tuple[bool, str]:
        if importlib.util.find_spec("vieneu") is None:
            return False, "Chưa cài gói vieneu. Hãy chạy setup.ps1."
        style_note = " · chuyển phong cách local" if self.style_reference_names else ""
        return True, (
            "VieNeu-TTS v3 Turbo · local CPU/ONNX · dữ liệu không rời máy"
            + style_note
        )

    def _get_model(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from vieneu import Vieneu
                    from .config import BUNDLED_MODEL_CACHE, _IS_SERVERLESS

                    precision = self.settings.precision
                    kwargs: dict = {"backend": "onnx"}
                    if precision == "int8":
                        kwargs["precision"] = "int8"

                    # On serverless (Vercel), disable denoiser to save ~40MB of /tmp.
                    # denoiser.onnx is 40.7MB — skipping it keeps us within /tmp limits.
                    if _IS_SERVERLESS:
                        kwargs["denoiser"] = False
                        print(
                            f"⏳ Loading VieNeu-TTS v3 Turbo (ONNX/{precision.upper()}/serverless) "
                            f"— denoiser disabled to conserve /tmp space",
                            flush=True,
                        )
                    else:
                        print(
                            f"⏳ Loading VieNeu-TTS v3 Turbo (ONNX/{precision.upper()})",
                            flush=True,
                        )

                    # If the model was pre-downloaded at build time (Vercel),
                    # point vieneu directly at the bundled files to avoid
                    # re-downloading into /tmp (which is too small).
                    subfolder = "onnx_int8" if precision == "int8" else "onnx_update"
                    vieneu_dir = BUNDLED_MODEL_CACHE / "vieneu"
                    vieneu_onnx_dir = vieneu_dir / subfolder
                    codec_dir = BUNDLED_MODEL_CACHE / "codec"
                    # Check for actual model files (not just empty directories)
                    bundled_config = vieneu_onnx_dir / "config.json"
                    bundled_codec_meta = codec_dir / "codec_browser_onnx_meta.json"
                    if bundled_config.exists() and bundled_config.stat().st_size > 0:
                        print(
                            f"📦 Using bundled model cache at {BUNDLED_MODEL_CACHE}",
                            flush=True,
                        )
                        # Pass local dirs directly to vieneu so it skips ALL HF downloads:
                        # - onnx_dir: backbone ONNX graphs (int8/fp32)
                        # - backbone_repo: local dir so speaker_encoder.onnx is found locally
                        #   (OnnxSpeakerEncoder.from_pretrained checks os.path.isdir first)
                        # - moss_tokenizer: codec ONNX files
                        kwargs["onnx_dir"] = str(vieneu_onnx_dir)
                        kwargs["backbone_repo"] = str(vieneu_dir)
                        if bundled_codec_meta.exists():
                            kwargs["moss_tokenizer"] = str(codec_dir)
                    else:
                        print(
                            f"🌐 No bundled model files found — downloading from HuggingFace (int8={precision == 'int8'})",
                            flush=True,
                        )

                    self._model = Vieneu(**kwargs)
                    self._redirect_reference_temp(self._model)
        return self._model

    def _redirect_reference_temp(self, model) -> None:
        """Keep VieNeu's pre-cleaned voice clip inside the project sandbox.

        VieNeu 3.4.0 otherwise hard-codes ``Path.home()/.cache/vieneu/tmp``.
        Its helper accepts an explicit output path, so this adapter supplies one
        without changing the installed third-party package or the HOME variable.
        """

        original_preclean = model._preclean_reference_audio
        temp_dir = self.settings.cache_dir / "vieneu" / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        def local_preclean(ref_audio, *, top_db: int = 30, out_path=None):
            if out_path is None:
                descriptor, generated_path = tempfile.mkstemp(
                    prefix="temp_clone_optimized_",
                    suffix=".wav",
                    dir=str(temp_dir),
                )
                os.close(descriptor)
                out_path = generated_path
            return original_preclean(ref_audio, top_db=top_db, out_path=out_path)

        model._preclean_reference_audio = local_preclean

    def _get_style_codes(self, model, style_name: str) -> np.ndarray | None:
        if style_name in self._style_codes:
            return self._style_codes[style_name]
        path = self.settings.data_dir / "style_references" / f"{style_name}.wav"
        if not path.is_file():
            self._style_codes[style_name] = None
            return None
        _, codes = model._resolve_ref(None, str(path), False, True)
        self._style_codes[style_name] = codes
        return codes

    def synthesize(
        self,
        segments: Sequence[EmotionSegment],
        output_path: Path,
        *,
        reference_path: Path | None,
        builtin_voice: str,
        denoise: bool,
        speed: float = DEFAULT_SPEED,
        style_transfer: bool = False,
    ) -> None:
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise ValueError(f"Tốc độ phải từ {MIN_SPEED:.2f}× đến {MAX_SPEED:.2f}×.")
        if not segments:
            raise ValueError("Kịch bản không có đoạn nào để tổng hợp.")
        model = self._get_model()
        with self._infer_lock:
            speaker_emb = None
            ref_codes = None
            if reference_path is not None:
                speaker_emb, ref_codes = model._resolve_ref(
                    None,
                    str(reference_path),
                    denoise,
                    True,
                )
                base_voice: str | dict[str, object] = {
                    "speaker_emb": speaker_emb,
                    "codes": ref_codes,
                }
            else:
                base_voice = builtin_voice

            groups = _group_segments_for_natural_delivery(segments)
            rendered: list[np.ndarray] = []
            for group in groups:
                voice = base_voice
                style_name = _style_for_tags(group.tag_ids) if style_transfer else None
                style_codes = (
                    self._get_style_codes(model, style_name) if style_name is not None else None
                )
                if style_codes is not None:
                    if speaker_emb is None:
                        speaker_emb, ref_codes = model._resolve_ref(
                            builtin_voice,
                            None,
                            False,
                            True,
                        )
                        base_voice = {
                            "speaker_emb": speaker_emb,
                            "codes": ref_codes,
                        }
                    voice = {
                        "speaker_emb": speaker_emb,
                        "codes": style_codes,
                    }
                audio = model.infer(
                    group.engine_text,
                    voice=voice,
                    # VieNeu v3 derives its style from reference codes. Keeping
                    # one stable sampling profile prevents clause-to-clause
                    # timbre drift and pronunciation glitches.
                    temperature=0.8,
                )
                audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                if not len(audio):
                    raise RuntimeError("Engine trả về một đoạn âm thanh rỗng.")
                effective_speed = max(_MIN_EFFECTIVE_SPEED, min(_MAX_EFFECTIVE_SPEED, speed))
                audio = _safe_audio_effects(
                    audio,
                    model.sample_rate,
                    speed=effective_speed,
                    # A constant pitch shift changes timbre but does not create
                    # human prosody.  Preserve VieNeu's formants and let the
                    # reference, punctuation and sampling drive the contour.
                    pitch_steps=0.0,
                    gain_db=0.0,
                    limit_peak=False,
                )
                audio = _trim_generated_edges(audio, model.sample_rate)
                audio = _fade_edges(audio, model.sample_rate, milliseconds=6)
                if group.pause_before_ms:
                    rendered.append(
                        np.zeros(
                            round(model.sample_rate * group.pause_before_ms / 1000),
                            dtype=np.float32,
                        )
                    )
                rendered.append(audio)

            rendered.append(np.zeros(round(model.sample_rate * 0.12), dtype=np.float32))
            final_audio = np.concatenate(rendered)
            final_audio = _master_speech(final_audio)
            model.save(final_audio, str(output_path))
