from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from .audio import AudioValidationError, prepare_clone_reference
from .config import Settings, _IS_SERVERLESS
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
# Clone identity comes from speaker_emb + ref_codes. VieNeu's stock defaults
# (temp≈0.8, top_k=25) keep natural Vietnamese prosody; over-lowering temp
# flattens “nhấn nhá”, while pitch/speed DSP warps the enrolled timbre.
_CLONE_TEMPERATURE = 0.78
_CLONE_TOP_K = 25
_CLONE_TOP_P = 0.95
_CLONE_REPETITION_PENALTY = 1.2
_BUILTIN_TEMPERATURE = 0.8
_PRECLEAN_TOP_DB = 28
# Serverless (Hobby ~2GB) OOMs above ~200 chars/decode; keep under that.
_INFER_MAX_CHARS = 100 if _IS_SERVERLESS else 384
_SERVERLESS_MAX_GROUPS = 6
_SERVERLESS_MAX_GROUP_CHARS = 100
# Per HTTP job on cloud — UI stitches many of these for ~60s scripts.
_SERVERLESS_CLONE_MAX_CHARS = 140
_SERVERLESS_BUILTIN_MAX_CHARS = 220

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


def _time_stretch(audio: np.ndarray, rate: float, sample_rate: int = 48_000) -> np.ndarray:
    """Change playback duration without librosa/STFT (STFT OOMs on Vercel 2GB).

    Uses soxr resampling: slight pitch shift with speed is acceptable for TTS tags
    and stays within serverless memory.
    """

    if abs(rate - 1.0) <= 0.001:
        return audio
    # rate < 1 → slower → more samples; rate > 1 → fewer samples.
    target_rate = max(1_000, int(round(sample_rate / rate)))
    try:
        import soxr

        return np.asarray(
            soxr.resample(audio, sample_rate, target_rate),
            dtype=np.float32,
        )
    except Exception:  # noqa: BLE001 - keep synthesis alive on slim runtimes
        new_len = max(1, int(round(len(audio) / rate)))
        positions = np.linspace(0, len(audio) - 1, new_len, dtype=np.float64)
        return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def _pitch_shift(audio: np.ndarray, sample_rate: int, steps: float) -> np.ndarray:
    """Shift pitch without librosa by resampling around a soxr rate change."""

    if abs(steps) <= 0.01:
        return audio
    import soxr

    factor = float(2 ** (steps / 12.0))
    # Raise/lower by resampling, then restore duration with time stretch.
    shifted = np.asarray(
        soxr.resample(audio, sample_rate, int(round(sample_rate * factor))),
        dtype=np.float32,
    )
    restored = _time_stretch(shifted, rate=factor, sample_rate=sample_rate)
    # Keep output length stable for callers that expect formant-only changes.
    if len(restored) == len(audio):
        return restored
    if len(restored) > len(audio):
        return restored[: len(audio)].copy()
    padded = np.zeros(len(audio), dtype=np.float32)
    padded[: len(restored)] = restored
    return padded


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
        if abs(pitch_steps) > 0.01:
            result = _pitch_shift(result, sample_rate, pitch_steps)
        if abs(speed - 1.0) > 0.001:
            result = _time_stretch(result, speed, sample_rate=sample_rate)
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
    temperatures: tuple[float, ...] = ()
    speed_multipliers: tuple[float, ...] = ()
    pitch_steps: tuple[float, ...] = ()
    gain_dbs: tuple[float, ...] = ()


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
    current_temperatures: list[float] = []
    current_speeds: list[float] = []
    current_pitches: list[float] = []
    current_gains: list[float] = []
    current_pause_ms = 0

    def flush() -> None:
        nonlocal current_text, current_pause_ms, current_tag_ids, current_temperatures
        nonlocal current_speeds, current_pitches, current_gains
        if current_text:
            groups.append(
                _InferenceGroup(
                    engine_text=" ".join(current_text),
                    pause_before_ms=current_pause_ms,
                    tag_ids=tuple(current_tag_ids),
                    temperatures=tuple(current_temperatures),
                    speed_multipliers=tuple(current_speeds),
                    pitch_steps=tuple(current_pitches),
                    gain_dbs=tuple(current_gains),
                )
            )
        current_text = []
        current_tag_ids = []
        current_temperatures = []
        current_speeds = []
        current_pitches = []
        current_gains = []
        current_pause_ms = 0

    for segment in segments:
        if current_text and segment.pause_before_ms:
            flush()
            current_pause_ms = segment.pause_before_ms
        elif not current_text and segment.pause_before_ms:
            current_pause_ms = segment.pause_before_ms
        current_text.append(segment.engine_text)
        current_tag_ids.extend(segment.tag_ids)
        current_temperatures.append(segment.temperature)
        current_speeds.append(segment.speed_multiplier)
        current_pitches.append(segment.pitch_steps)
        current_gains.append(segment.gain_db)
    flush()
    return tuple(groups)


def _group_speed_multiplier(multipliers: Sequence[float]) -> float:
    if not multipliers:
        return 1.0
    product = 1.0
    for value in multipliers:
        product *= value
    return product ** (1.0 / len(multipliers))


def _group_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _split_text_by_limit(text: str, max_chars: int) -> list[str]:
    """Split long prose at sentence / clause boundaries for low-memory inference."""

    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return [cleaned] if cleaned else []

    parts: list[str] = []
    remaining = cleaned
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        window = remaining[: max_chars + 1]
        split_at = -1
        for marker in (". ", "! ", "? ", "; ", ", ", " "):
            index = window.rfind(marker)
            if index >= max(24, max_chars // 3):
                split_at = index + len(marker)
                break
        if split_at <= 0:
            split_at = max_chars
        chunk = remaining[:split_at].strip()
        if chunk:
            parts.append(chunk)
        remaining = remaining[split_at:].strip()
    return parts


def _prepare_inference_groups(
    segments: Sequence[EmotionSegment],
) -> tuple[_InferenceGroup, ...]:
    """Group for delivery, then (on serverless) shatter into tiny ONNX-safe pieces."""

    groups = _group_segments_for_natural_delivery(segments)
    if not _IS_SERVERLESS:
        return groups

    shattered: list[_InferenceGroup] = []
    for group in groups:
        pieces = _split_text_by_limit(group.engine_text, _SERVERLESS_MAX_GROUP_CHARS)
        if not pieces:
            continue
        for index, piece in enumerate(pieces):
            shattered.append(
                _InferenceGroup(
                    engine_text=piece,
                    pause_before_ms=group.pause_before_ms if index == 0 else 40,
                    tag_ids=group.tag_ids,
                    temperatures=group.temperatures,
                    speed_multipliers=group.speed_multipliers,
                    pitch_steps=group.pitch_steps,
                    gain_dbs=group.gain_dbs,
                )
            )
    return tuple(shattered)


def _sampling_temperature(
    temperatures: Sequence[float],
    *,
    cloning: bool,
) -> float:
    """Prefer identity-stable sampling when a personal reference is enrolled."""

    if not cloning:
        if temperatures:
            return round(max(0.70, min(0.95, sum(temperatures) / len(temperatures))), 2)
        return _BUILTIN_TEMPERATURE
    if not temperatures:
        return _CLONE_TEMPERATURE
    # Soft nudge only — stay near VieNeu's natural-prosody band.
    average = sum(temperatures) / len(temperatures)
    nudged = _CLONE_TEMPERATURE + (average - 0.8) * 0.35
    return round(max(0.70, min(0.88, nudged)), 2)


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


def _write_wav_from_f32_dump(dump_path: Path, output_path: Path, sample_rate: int) -> None:
    """Stream float32 PCM dump → 16-bit WAV with light gain, low peak RAM."""

    import wave

    chunk_samples = sample_rate  # ~1 second
    sum_sq = 0.0
    total = 0
    peak = 0.0
    with dump_path.open("rb") as source:
        while True:
            raw = source.read(chunk_samples * 4)
            if not raw:
                break
            block = np.frombuffer(raw, dtype=np.float32)
            sum_sq += float(np.dot(block, block))
            total += len(block)
            peak = max(peak, float(np.max(np.abs(block))))
    if total <= 0:
        raise RuntimeError("Engine không tạo được mẫu âm thanh.")

    rms = float(np.sqrt(sum_sq / total))
    gain = 1.0
    if rms > 1e-8:
        current_rms_db = 20 * np.log10(rms)
        makeup_db = min(_MASTER_MAX_MAKEUP_DB, _MASTER_TARGET_RMS_DB - current_rms_db)
        gain = 10 ** (makeup_db / 20)
    if peak * gain > _PEAK_CEILING and peak > 1e-8:
        gain *= _PEAK_CEILING / (peak * gain)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with dump_path.open("rb") as source, wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        while True:
            raw = source.read(chunk_samples * 4)
            if not raw:
                break
            block = np.frombuffer(raw, dtype=np.float32) * np.float32(gain)
            pcm = np.clip(block * 32767.0, -32768, 32767).astype(np.int16)
            wav_file.writeframes(pcm.tobytes())


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
                        # Pass local dirs directly to vieneu so it skips HF download
                        kwargs["onnx_dir"] = str(vieneu_onnx_dir)
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

        def local_preclean(ref_audio, *, top_db: int = _PRECLEAN_TOP_DB, out_path=None):
            # Softer than VieNeu's stock top_db=30 so quiet onsets and breath
            # that carry speaker identity are not stripped before embedding.
            effective_top_db = min(top_db, _PRECLEAN_TOP_DB)
            if out_path is None:
                descriptor, generated_path = tempfile.mkstemp(
                    prefix="temp_clone_optimized_",
                    suffix=".wav",
                    dir=str(temp_dir),
                )
                os.close(descriptor)
                out_path = generated_path
            return original_preclean(
                ref_audio,
                top_db=effective_top_db,
                out_path=out_path,
            )

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
        prepared_reference: Path | None = None
        dump_path: Path | None = None
        with self._infer_lock:
            try:
                speaker_emb = None
                ref_codes = None
                cloning = reference_path is not None
                if cloning:
                    prepared_dir = self.settings.cache_dir / "vieneu" / "prepared"
                    prepared_dir.mkdir(parents=True, exist_ok=True)
                    prepared_reference = prepared_dir / f"{uuid.uuid4().hex}.wav"
                    try:
                        prepare_clone_reference(reference_path, prepared_reference)
                    except AudioValidationError:
                        raise
                    speaker_emb, ref_codes = model._resolve_ref(
                        None,
                        str(prepared_reference),
                        denoise,
                        True,
                    )
                    base_voice: str | dict[str, object] = {
                        "speaker_emb": speaker_emb,
                        "codes": ref_codes,
                    }
                else:
                    base_voice = builtin_voice

                groups = _prepare_inference_groups(segments)
                if _IS_SERVERLESS and len(groups) > _SERVERLESS_MAX_GROUPS:
                    raise ValueError(
                        "Đoạn văn quá dài cho môi trường cloud (giới hạn bộ nhớ 2GB). "
                        f"Hãy rút xuống còn khoảng {_SERVERLESS_MAX_GROUPS} câu ngắn "
                        "(khoảng dưới 500 ký tự mỗi lượt)."
                    )

                # Stream pieces to a temp float32 dump so long scripts do not keep
                # every chunk resident in RAM at once (Vercel OOM → SIGKILL 137).
                dump_path = (
                    self.settings.cache_dir / "vieneu" / "tmp" / f"{uuid.uuid4().hex}.f32"
                )
                dump_path.parent.mkdir(parents=True, exist_ok=True)
                total_samples = 0
                sample_rate = int(model.sample_rate)
                with dump_path.open("wb") as dump:
                    for group in groups:
                        voice = base_voice
                        style_name = (
                            _style_for_tags(group.tag_ids) if style_transfer else None
                        )
                        style_codes = (
                            self._get_style_codes(model, style_name)
                            if style_name is not None
                            else None
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
                        temperature = _sampling_temperature(
                            group.temperatures,
                            cloning=cloning and style_codes is None,
                        )
                        infer_kwargs: dict[str, object] = {
                            "voice": voice,
                            "temperature": temperature,
                            "top_k": _CLONE_TOP_K if cloning else 25,
                            "top_p": _CLONE_TOP_P if cloning else 0.95,
                            "max_chars": _INFER_MAX_CHARS,
                            "apply_watermark": False,
                        }
                        if cloning:
                            # Match VieNeu defaults so prosody stays in the
                            # reference's natural reading style.
                            infer_kwargs["repetition_penalty"] = _CLONE_REPETITION_PENALTY
                            infer_kwargs["denoise"] = False
                        audio = model.infer(group.engine_text, **infer_kwargs)
                        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                        if not len(audio):
                            raise RuntimeError("Engine trả về một đoạn âm thanh rỗng.")
                        if cloning:
                            # Pitch/speed DSP changes formants and kills identity.
                            # Emotion for clones = native cues + punctuation only.
                            effective_speed = max(0.97, min(1.03, speed))
                            pitch = 0.0
                            gain = 0.0
                        else:
                            effective_speed = max(
                                _MIN_EFFECTIVE_SPEED,
                                min(
                                    _MAX_EFFECTIVE_SPEED,
                                    speed * _group_speed_multiplier(group.speed_multipliers),
                                ),
                            )
                            pitch = _group_mean(group.pitch_steps)
                            gain = _group_mean(group.gain_dbs)
                        audio = _safe_audio_effects(
                            audio,
                            sample_rate,
                            speed=effective_speed,
                            pitch_steps=pitch,
                            gain_db=gain,
                            limit_peak=False,
                        )
                        audio = _trim_generated_edges(audio, sample_rate)
                        audio = _fade_edges(audio, sample_rate, milliseconds=6)
                        if group.pause_before_ms:
                            pause = np.zeros(
                                round(sample_rate * group.pause_before_ms / 1000),
                                dtype=np.float32,
                            )
                            dump.write(pause.tobytes())
                            total_samples += len(pause)
                            del pause
                        dump.write(audio.tobytes())
                        total_samples += len(audio)
                        del audio
                        if _IS_SERVERLESS:
                            import gc

                            gc.collect()

                    tail = np.zeros(round(sample_rate * 0.12), dtype=np.float32)
                    dump.write(tail.tobytes())
                    total_samples += len(tail)

                if total_samples <= 0:
                    raise RuntimeError("Engine không tạo được mẫu âm thanh.")
                if _IS_SERVERLESS:
                    # Avoid loading the full float32 program into RAM (OOM → SIGKILL).
                    _write_wav_from_f32_dump(dump_path, output_path, sample_rate)
                    dump_path.unlink(missing_ok=True)
                    dump_path = None
                else:
                    final_audio = np.fromfile(str(dump_path), dtype=np.float32)
                    dump_path.unlink(missing_ok=True)
                    dump_path = None
                    final_audio = _master_speech(final_audio)
                    model.save(final_audio, str(output_path))
                    del final_audio
            finally:
                if dump_path is not None:
                    dump_path.unlink(missing_ok=True)
                if prepared_reference is not None:
                    prepared_reference.unlink(missing_ok=True)
