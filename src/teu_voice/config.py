from __future__ import annotations

import os
from ipaddress import IPv4Address, ip_address
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# On Vercel (and other serverless platforms) the project root is read-only.
# Only /tmp is writable. Detect this and redirect mutable dirs accordingly.
_SERVERLESS_TMP = Path("/tmp/teu_voice")
_IS_SERVERLESS = os.getenv("VERCEL") == "1" or not os.access(PROJECT_ROOT, os.W_OK)
_WRITABLE_ROOT = _SERVERLESS_TMP if _IS_SERVERLESS else PROJECT_ROOT

# Pre-downloaded model cache bundled at build time (lives in project root).
# On Vercel this is read-only but already present in /var/task/model_cache/.
BUNDLED_MODEL_CACHE = PROJECT_ROOT / "model_cache"


def is_loopback_host(host: str) -> bool:
    return host.lower().rstrip(".") in LOOPBACK_HOSTS


def is_private_lan_ipv4(host: str) -> bool:
    """Allow one explicit private IPv4 address, never a wildcard bind."""

    try:
        address = ip_address(host)
    except ValueError:
        return False
    return isinstance(address, IPv4Address) and address.is_private and not address.is_loopback


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = _WRITABLE_ROOT / "data"
    output_dir: Path = _WRITABLE_ROOT / "outputs"
    cache_dir: Path = _WRITABLE_ROOT / ".cache"
    default_reference: Path = _WRITABLE_ROOT / "data" / "voice_reference.wav"
    # On Vercel use int8 by default (onnx_int8 is ~157MB vs onnx_update ~453MB).
    # This keeps model download within Vercel's /tmp limit (~512MB).
    precision: str = os.getenv(
        "TEU_VOICE_PRECISION",
        "int8" if _IS_SERVERLESS else "fp32",
    ).lower()
    # Bias builtin presets toward Saigon/Southern Vietnamese by default.
    voice_region: str = os.getenv("TEU_VOICE_REGION", "nam").lower()
    host: str = os.getenv("TEU_VOICE_HOST", "127.0.0.1")
    access_key: str | None = os.getenv("TEU_VOICE_ACCESS_KEY") or None
    ngrok_host: str | None = os.getenv("TEU_VOICE_NGROK_HOST") or None
    max_text_chars: int = int(
        os.getenv(
            "TEU_VOICE_MAX_TEXT_CHARS",
            # Cloud Hobby ~2GB: keep scripts short so ONNX decode never SIGKILL 137.
            "280" if _IS_SERVERLESS else "2000",
        )
    )
    max_upload_bytes: int = (
        3 * 1024 * 1024 if _IS_SERVERLESS else 20 * 1024 * 1024
    )
    @property
    def lan_enabled(self) -> bool:
        return is_private_lan_ipv4(self.host)

    @property
    def ngrok_enabled(self) -> bool:
        return bool(self.ngrok_host)

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # On serverless (Vercel), force HF Hub to use /tmp so it has write access.
        # Use a flat path directly in /tmp/teu_voice/.cache to avoid sub-dir creation
        # issues; the path must be writable for HF to store downloaded model chunks.
        hf_home = str(self.cache_dir / "huggingface")
        os.environ.setdefault("HF_HOME", hf_home)
        os.environ.setdefault("HF_HUB_CACHE", hf_home + "/hub")
        os.environ.setdefault("XDG_CACHE_HOME", str(self.cache_dir))
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        # Disable progress bars in serverless to reduce log noise
        if _IS_SERVERLESS:
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            # Cap BLAS / ONNX threads so activation peaks stay under Hobby 2GB.
            os.environ.setdefault("OMP_NUM_THREADS", "1")
            os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
            os.environ.setdefault("MKL_NUM_THREADS", "1")
            os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
            os.environ.setdefault("ORT_DISABLE_MEMORY_ARENA", "1")


settings = Settings()
