"""Create one real local sample for installation verification."""

from __future__ import annotations

import sys
from datetime import datetime

from teu_voice.config import settings
from teu_voice.emotions import compile_emotion_script
from teu_voice.engine import VieneuEngine


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings.prepare()
    if not settings.default_reference.exists():
        raise SystemExit("Missing data/voice_reference.wav")

    text = (
        "@hài_hước Người ta nói tiền không mua được hạnh phúc. "
        "@tỉnh_bơ Chắc là vì họ chưa thấy phí giao hàng! @cười_khẽ Hê hê."
    )
    plan = compile_emotion_script(text)
    output = settings.output_dir / "demo-voice.wav"
    if output.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = settings.output_dir / f"demo-voice-{stamp}.wav"

    print(f"Performance script: {plan.display_text}")
    print("Loading the local model and synthesizing...")
    engine = VieneuEngine(settings)
    engine.synthesize(
        plan.segments,
        output,
        reference_path=settings.default_reference,
        builtin_voice="Adam",
        denoise=False,
        speed=1.0,
    )
    print(f"Created: {output}")


if __name__ == "__main__":
    main()
