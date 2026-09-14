from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


# Preferred order for a Saigon-leaning studio: Southern first, then Central.
# Custom voices (from data/custom_voices.json) appear first.
_SOUTHERN_FIRST = (
    "Vlogger",
    "Adam",
    "Xuân Vĩnh",
    "Thái Sơn",
    "Minh Triết",
    "Đức Trí",
    "Thùy Dung",
    "Mỹ Duyên",
    "Thục Đoan",
    "Kim Thanh",
    "Quang Sơn",
    "Ngọc Trân",
    "Phạm Tuyên",
    "Minh Đức",
    "Trúc Ly",
    "Mai Anh",
    "Quỳnh Anh",
    "Ngọc Huyền",
    "Thanh Bình",
    "Ngọc Linh",
    "Đoan Trang",
)

_REGION_RANK = {"Nam": 0, "Trung": 1, "Bắc": 2}


@dataclass(frozen=True, slots=True)
class BuiltinVoice:
    id: str
    region: str
    gender: str
    style: str
    description: str

    @property
    def label(self) -> str:
        region_label = {
            "Nam": "Miền Nam",
            "Bắc": "Miền Bắc",
            "Trung": "Miền Trung",
        }.get(self.region, self.region)
        gender_label = {"male": "giọng nam", "female": "giọng nữ"}.get(self.gender, "")
        bits = [part for part in (region_label, gender_label) if part]
        suffix = " · ".join(bits)
        return f"{self.id} ({suffix})" if suffix else self.id

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "region": self.region,
            "gender": self.gender,
            "style": self.style,
            "description": self.description,
        }


def preferred_region() -> str:
    value = (os.getenv("TEU_VOICE_REGION") or "nam").strip().lower()
    if value in {"nam", "south", "saigon", "sài gòn", "sai gon", "mien nam"}:
        return "nam"
    if value in {"bac", "north", "hanoi", "hà nội", "ha noi", "mien bac"}:
        return "bac"
    if value in {"trung", "central", "mien trung"}:
        return "trung"
    return "all"


@lru_cache(maxsize=1)
def _custom_voice_metadata() -> dict[str, dict[str, str]]:
    """Load metadata for user-defined voices.

    Looks for custom_voices.json next to this module (bundled into the package
    on Vercel) first, then falls back to data/custom_voices.json for local dev.
    """
    try:
        # 1) Bundled alongside the package (Vercel deployment)
        pkg_path = Path(__file__).resolve().parent / "custom_voices.json"
        # 2) Local dev: data/ at project root
        data_dir = Path(__file__).resolve().parents[2] / "data"
        custom_path = pkg_path if pkg_path.is_file() else data_dir / "custom_voices.json"
        if custom_path.is_file():
            payload = json.loads(custom_path.read_text(encoding="utf-8"))
            presets = payload.get("presets") or {}
            return {
                name: {
                    "region": str(meta.get("region") or ""),
                    "gender": str(meta.get("gender") or ""),
                    "style": str(meta.get("style") or ""),
                    "description": str(meta.get("description") or name),
                }
                for name, meta in presets.items()
                if isinstance(meta, dict)
            }
    except Exception:  # noqa: BLE001
        pass
    return {}


@lru_cache(maxsize=1)
def _preset_metadata() -> dict[str, dict[str, str]]:
    # Start with custom voices so they can override or extend builtins
    result: dict[str, dict[str, str]] = dict(_custom_voice_metadata())
    try:
        import vieneu

        asset = Path(vieneu.__file__).resolve().parent / "assets" / "voices_v3_turbo.json"
        if asset.is_file():
            payload = json.loads(asset.read_text(encoding="utf-8"))
            presets = payload.get("presets") or {}
            for name, meta in presets.items():
                if isinstance(meta, dict) and name not in result:
                    result[name] = {
                        "region": str(meta.get("region") or ""),
                        "gender": str(meta.get("gender") or ""),
                        "style": str(meta.get("style") or ""),
                        "description": str(meta.get("description") or ""),
                    }
    except Exception:  # noqa: BLE001
        pass
    return result


def _voice_from_name(name: str) -> BuiltinVoice:
    meta = _preset_metadata().get(name, {})
    return BuiltinVoice(
        id=name,
        region=meta.get("region") or "",
        gender=meta.get("gender") or "",
        style=meta.get("style") or "",
        description=meta.get("description") or name,
    )


def list_builtin_voices(*, region: str | None = None) -> tuple[BuiltinVoice, ...]:
    bias = (region or preferred_region()).lower()
    by_id = {_voice_from_name(name).id: _voice_from_name(name) for name in _SOUTHERN_FIRST}
    for name in _preset_metadata():
        by_id[name] = _voice_from_name(name)
    voices = list(by_id.values())

    def sort_key(voice: BuiltinVoice) -> tuple[int, int, str]:
        try:
            curated = _SOUTHERN_FIRST.index(voice.id)
        except ValueError:
            curated = len(_SOUTHERN_FIRST) + _REGION_RANK.get(voice.region, 9)
        region_rank = _REGION_RANK.get(voice.region, 9)
        if bias == "nam":
            return (region_rank, curated, voice.id)
        if bias == "bac":
            return (0 if voice.region == "Bắc" else 1, curated, voice.id)
        if bias == "trung":
            return (0 if voice.region == "Trung" else 1, curated, voice.id)
        return (curated, region_rank, voice.id)

    voices.sort(key=sort_key)

    if bias == "nam":
        southern = [voice for voice in voices if voice.region == "Nam"]
        if southern:
            others = [voice for voice in voices if voice.region in {"", "Trung"}]
            return tuple(southern + others)
    if bias == "bac":
        northern = [voice for voice in voices if voice.region == "Bắc"]
        if northern:
            return tuple(northern)
    if bias == "trung":
        central = [voice for voice in voices if voice.region == "Trung"]
        if central:
            return tuple(central)
    return tuple(voices)


def default_builtin_voice(region: str | None = None) -> str:
    voices = list_builtin_voices(region=region)
    return voices[0].id if voices else "Adam"


def builtin_voice_ids(region: str | None = None) -> tuple[str, ...]:
    return tuple(voice.id for voice in list_builtin_voices(region=region))
