"""
Build-time script: pre-download VieNeu ONNX model files so they are bundled
into the Vercel deployment instead of being downloaded at cold-start runtime
(which fails because /tmp is too small on Vercel).

Vercel calls this via [tool.vercel.scripts] build in pyproject.toml.
The script runs after dependencies are installed, so vieneu and
huggingface_hub are available.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Target: sits next to pyproject.toml, gets bundled into /var/task/model_cache/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = PROJECT_ROOT / "model_cache"

# Subfolder structure expected by engine.py
VIENEU_DIR = BUNDLE_DIR / "vieneu"
CODEC_DIR = BUNDLE_DIR / "codec"


def _try_import_hf():
    """Try to import huggingface_hub from installed packages or vendor path."""
    try:
        from huggingface_hub import hf_hub_download
        return hf_hub_download
    except ImportError:
        pass
    # Vercel bundles packages into _vendor/
    vendor = Path("/var/task/_vendor")
    if vendor.exists():
        sys.path.insert(0, str(vendor))
        try:
            from huggingface_hub import hf_hub_download
            return hf_hub_download
        except ImportError:
            pass
    return None


def download():
    hf_hub_download = _try_import_hf()
    if hf_hub_download is None:
        print("[download_models] ERROR: huggingface_hub not found. Skipping.", flush=True)
        return

    hf_token = os.getenv("HF_TOKEN")
    common_kwargs: dict = {}
    if hf_token:
        common_kwargs["token"] = hf_token
        print("[download_models] Using HF_TOKEN for authenticated downloads.", flush=True)
    else:
        print("[download_models] WARNING: No HF_TOKEN set. Using unauthenticated (rate-limited).", flush=True)

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    VIENEU_DIR.mkdir(parents=True, exist_ok=True)
    CODEC_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[download_models] Target directory: {BUNDLE_DIR}", flush=True)

    # ── VieNeu-TTS v3 Turbo (ONNX fp32 subfolder) ───────────────────────────
    vieneu_onnx_dir = VIENEU_DIR / "onnx_update"
    vieneu_onnx_dir.mkdir(parents=True, exist_ok=True)

    vieneu_onnx_files = [
        ("onnx_update/config.json",                    vieneu_onnx_dir / "config.json"),
        ("onnx_update/tokenizer.json",                 vieneu_onnx_dir / "tokenizer.json"),
        ("onnx_update/vieneu_prefill.onnx",            vieneu_onnx_dir / "vieneu_prefill.onnx"),
        ("onnx_update/vieneu_decode_step.onnx",        vieneu_onnx_dir / "vieneu_decode_step.onnx"),
        ("onnx_update/vieneu_acoustic_cached.onnx",    vieneu_onnx_dir / "vieneu_acoustic_cached.onnx"),
        ("onnx_update/vieneu_backbone_shared.data",    vieneu_onnx_dir / "vieneu_backbone_shared.data"),
        ("onnx_update/vieneu_v3_heads.npz",            vieneu_onnx_dir / "vieneu_v3_heads.npz"),
    ]
    vieneu_root_files = [
        ("config.json",          VIENEU_DIR / "config.json"),
        ("speaker_encoder.onnx", VIENEU_DIR / "speaker_encoder.onnx"),
    ]

    for hf_path, dest in vieneu_onnx_files + vieneu_root_files:
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  [skip] {hf_path} ({dest.stat().st_size // 1024}KB cached)", flush=True)
            continue
        print(f"  [dl]   {hf_path} ...", flush=True)
        try:
            # Download directly to dest to avoid HF cache temp dir overhead
            subfolder = "onnx_update" if hf_path.startswith("onnx_update/") else None
            filename = hf_path.split("/")[-1]
            hf_hub_download(
                repo_id="pnnbao-ump/VieNeu-TTS-v3-Turbo",
                filename=hf_path,
                local_dir=str(VIENEU_DIR),
                **common_kwargs,
            )
            print(f"  [ok]   {hf_path}", flush=True)
        except Exception as e:
            print(f"  [ERR]  {hf_path}: {e}", flush=True)
            sys.exit(1)

    # ── MOSS Audio Tokenizer (codec) ─────────────────────────────────────────
    codec_files = [
        "codec_browser_onnx_meta.json",
        "moss_audio_tokenizer_decode_full.onnx",
        "moss_audio_tokenizer_decode_step.onnx",
        "moss_audio_tokenizer_decode_shared.data",
        "moss_audio_tokenizer_encode.onnx",
        "moss_audio_tokenizer_encode.data",
    ]
    for fname in codec_files:
        dest = CODEC_DIR / fname
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  [skip] {fname} ({dest.stat().st_size // 1024}KB cached)", flush=True)
            continue
        print(f"  [dl]   {fname} ...", flush=True)
        try:
            hf_hub_download(
                repo_id="OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX",
                filename=fname,
                local_dir=str(CODEC_DIR),
                **common_kwargs,
            )
            print(f"  [ok]   {fname}", flush=True)
        except Exception as e:
            print(f"  [ERR]  {fname}: {e}", flush=True)
            sys.exit(1)

    # Verify total size
    total = sum(
        f.stat().st_size for f in BUNDLE_DIR.rglob("*") if f.is_file()
    )
    print(f"[download_models] Done. Total model cache: {total // 1024 // 1024}MB", flush=True)


if __name__ == "__main__":
    download()
