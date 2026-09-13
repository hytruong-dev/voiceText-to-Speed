"""
Build-time script: pre-download VieNeu ONNX model files (int8) so they are bundled
into the Vercel deployment instead of being downloaded at cold-start runtime
(which fails because /tmp is too small on Vercel).

Vercel calls this via [tool.vercel.scripts] build in pyproject.toml.
The script runs after 'uv sync', so huggingface_hub is available.

IMPORTANT — bundle size:
  Python deps (vieneu/onnxruntime/librosa/gradio/…) + int8 models are ~900MB–1GB.
  That exceeds the standard 500MB Python function limit. Enable Large Functions
  (up to 5GB) by setting the project env var:

      VERCEL_SUPPORT_LARGE_FUNCTIONS=1

  then redeploy. Fluid compute must be on (default for new projects).

Files downloaded:
  - pnnbao-ump/VieNeu-TTS-v3-Turbo (onnx_int8 subfolder only) — ~157MB
  - OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX (codec) — ~86MB
  Total models: ~243MB (plus runtime packages in the same function bundle)
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Target: sits next to pyproject.toml, gets bundled into /var/task/model_cache/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = PROJECT_ROOT / "model_cache"
VIENEU_DIR = BUNDLE_DIR / "vieneu"
CODEC_DIR = BUNDLE_DIR / "codec"

# Keep HuggingFace's own download cache OUT of the project tree so Vercel does
# not double-count blob copies inside the function bundle.
_HF_SCRATCH = PROJECT_ROOT / ".cache" / "hf-download"
os.environ.setdefault("HF_HOME", str(_HF_SCRATCH))
os.environ.setdefault("HF_HUB_CACHE", str(_HF_SCRATCH / "hub"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(_HF_SCRATCH / "hub"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# Only download int8 (smaller) to keep the Large Function payload lean
VIENEU_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
CODEC_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"

VIENEU_INT8_FILES = [
    "onnx_int8/config.json",
    "onnx_int8/tokenizer.json",
    "onnx_int8/vieneu_acoustic_cached.onnx",
    "onnx_int8/vieneu_backbone_shared.data",
    "onnx_int8/vieneu_decode_step.onnx",
    "onnx_int8/vieneu_prefill.onnx",
    "onnx_int8/vieneu_v3_heads.npz",
    "config.json",
    "speaker_encoder.onnx",
]

CODEC_FILES = [
    "codec_browser_onnx_meta.json",
    "moss_audio_tokenizer_decode_full.onnx",
    "moss_audio_tokenizer_decode_shared.data",
    "moss_audio_tokenizer_decode_step.onnx",
    "moss_audio_tokenizer_encode.onnx",
    "moss_audio_tokenizer_encode.data",
]


def _purge_nested_hub_junk(root: Path) -> None:
    """Remove HF hub metadata clones that inflate the deploy bundle."""

    for name in (".cache", ".huggingface", ".locks"):
        junk = root / name
        if junk.exists():
            shutil.rmtree(junk, ignore_errors=True)
            print(f"[download_models] Removed nested {junk.relative_to(PROJECT_ROOT)}", flush=True)


def _dir_size_mb(root: Path) -> int:
    if not root.exists():
        return 0
    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    return total // 1024 // 1024


def download():
    try:
        from huggingface_hub import hf_hub_download
        print("[download_models] huggingface_hub imported OK", flush=True)
    except ImportError as e:
        print(f"[download_models] ERROR: cannot import huggingface_hub: {e}", flush=True)
        print("[download_models] Models will be downloaded at runtime instead.", flush=True)
        sys.exit(0)  # Don't fail the build — runtime will handle it

    hf_token = os.getenv("HF_TOKEN")
    common_kwargs: dict = {
        # Flat files only — avoid symlink farms that leave duplicate blobs behind.
        "local_dir_use_symlinks": False,
    }
    if hf_token:
        common_kwargs["token"] = hf_token
        print("[download_models] Using HF_TOKEN for authenticated downloads.", flush=True)
    else:
        print("[download_models] No HF_TOKEN — using unauthenticated (rate-limited).", flush=True)

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    _HF_SCRATCH.mkdir(parents=True, exist_ok=True)

    print(f"[download_models] Downloading VieNeu int8 + codec to: {BUNDLE_DIR}", flush=True)

    # ── VieNeu-TTS v3 Turbo (int8 ONNX) ─────────────────────────────────────
    for hf_path in VIENEU_INT8_FILES:
        # local_dir layout: model_cache/vieneu/<hf_path> (preserving subfolder)
        dest = VIENEU_DIR / hf_path
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  [skip] {hf_path} ({dest.stat().st_size // 1024}KB)", flush=True)
            continue
        print(f"  [dl]   {hf_path} ...", flush=True)
        try:
            hf_hub_download(
                repo_id=VIENEU_REPO,
                filename=hf_path,
                local_dir=str(VIENEU_DIR),
                **common_kwargs,
            )
            dest_check = VIENEU_DIR / hf_path
            size = dest_check.stat().st_size if dest_check.exists() else 0
            print(f"  [ok]   {hf_path} ({size // 1024}KB)", flush=True)
        except Exception as e:
            print(f"  [ERR]  {hf_path}: {e}", flush=True)
            sys.exit(1)

    # ── MOSS Audio Tokenizer (codec) ─────────────────────────────────────────
    CODEC_DIR.mkdir(parents=True, exist_ok=True)
    for fname in CODEC_FILES:
        dest = CODEC_DIR / fname
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  [skip] {fname} ({dest.stat().st_size // 1024}KB)", flush=True)
            continue
        print(f"  [dl]   {fname} ...", flush=True)
        try:
            hf_hub_download(
                repo_id=CODEC_REPO,
                filename=fname,
                local_dir=str(CODEC_DIR),
                **common_kwargs,
            )
            dest_check = CODEC_DIR / fname
            size = dest_check.stat().st_size if dest_check.exists() else 0
            print(f"  [ok]   {fname} ({size // 1024}KB)", flush=True)
        except Exception as e:
            print(f"  [ERR]  {fname}: {e}", flush=True)
            sys.exit(1)

    _purge_nested_hub_junk(BUNDLE_DIR)
    _purge_nested_hub_junk(VIENEU_DIR)
    _purge_nested_hub_junk(CODEC_DIR)

    total_mb = _dir_size_mb(BUNDLE_DIR)
    print(f"[download_models] ✅ Done. Total model cache: {total_mb}MB", flush=True)
    print(
        "[download_models] Reminder: set VERCEL_SUPPORT_LARGE_FUNCTIONS=1 "
        "(Large Functions / up to 5GB) — deps+models exceed the 500MB Python limit.",
        flush=True,
    )


if __name__ == "__main__":
    download()
