"""
Build-time script: pre-download VieNeu ONNX model files into the project so
they get bundled into the Vercel deployment instead of being downloaded at
runtime (which fails because /tmp is too small).

Run automatically via [tool.vercel.scripts] build in pyproject.toml.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Target directory — committed into the repo so Vercel bundles it
BUNDLE_DIR = Path(__file__).resolve().parents[1] / "model_cache"


def download():
    try:
        from huggingface_hub import snapshot_download, hf_hub_download
    except ImportError:
        print("[download_models] huggingface_hub not available, skipping.", flush=True)
        return

    hf_token = os.getenv("HF_TOKEN")  # optional, raises rate limits

    common_kwargs: dict = {}
    if hf_token:
        common_kwargs["token"] = hf_token

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(BUNDLE_DIR / "hf_home")

    print(f"[download_models] Downloading models into {BUNDLE_DIR} ...", flush=True)

    # ── VieNeu-TTS v3 Turbo (ONNX) ──────────────────────────────────────────
    vieneu_files = [
        "onnx_update/config.json",
        "onnx_update/tokenizer.json",
        "onnx_update/vieneu_prefill.onnx",
        "onnx_update/vieneu_decode_step.onnx",
        "onnx_update/vieneu_acoustic_cached.onnx",
        "onnx_update/vieneu_backbone_shared.data",
        "onnx_update/vieneu_v3_heads.npz",
        "config.json",
        "speaker_encoder.onnx",
        # denoiser skipped — not used in builtin-voice mode on Vercel
    ]
    vieneu_dir = BUNDLE_DIR / "vieneu"
    vieneu_dir.mkdir(parents=True, exist_ok=True)
    for fname in vieneu_files:
        dest = vieneu_dir / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            print(f"  [skip] {fname}", flush=True)
            continue
        print(f"  [dl]   {fname}", flush=True)
        try:
            path = hf_hub_download(
                repo_id="pnnbao-ump/VieNeu-TTS-v3-Turbo",
                filename=fname,
                local_dir=str(vieneu_dir),
                **common_kwargs,
            )
            print(f"  [ok]   {path}", flush=True)
        except Exception as e:
            print(f"  [ERR]  {fname}: {e}", flush=True)
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
    codec_dir = BUNDLE_DIR / "codec"
    codec_dir.mkdir(parents=True, exist_ok=True)
    for fname in codec_files:
        dest = codec_dir / fname
        if dest.exists():
            print(f"  [skip] {fname}", flush=True)
            continue
        print(f"  [dl]   {fname}", flush=True)
        try:
            path = hf_hub_download(
                repo_id="OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX",
                filename=fname,
                local_dir=str(codec_dir),
                **common_kwargs,
            )
            print(f"  [ok]   {path}", flush=True)
        except Exception as e:
            print(f"  [ERR]  {fname}: {e}", flush=True)
            sys.exit(1)

    print("[download_models] Done.", flush=True)


if __name__ == "__main__":
    download()
