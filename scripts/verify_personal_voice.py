"""Generate an identity-first sample and record reproducible audio metrics."""
import json
import os
from datetime import datetime

import numpy as np
import soundfile as sf

from teu_voice.config import settings
from teu_voice.emotions import compile_emotion_script
from teu_voice.engine import VieneuEngine


def metrics(path):
    y, sr = sf.read(path)
    return {"seconds": len(y) / sr, "peak_dbfs": float(20 * np.log10(max(np.max(np.abs(y)), 1e-12))),
            "rms_dbfs": float(20 * np.log10(max(np.sqrt(np.mean(y * y)), 1e-12))),
            "clipped_fraction": float(np.mean(np.abs(y) >= 0.999))}


def main():
    os.environ["HF_HUB_OFFLINE"] = "1"
    settings.prepare()
    engine = VieneuEngine(settings)
    text = "Xin chào, đây là giọng nói của tôi. Hôm nay tôi thử kể một câu chuyện thật tự nhiên, như đang trò chuyện với bạn."
    output = settings.output_dir / ("personal-voice-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".wav")
    np.random.seed(42)
    engine.synthesize(compile_emotion_script(text).segments, output,
                      reference_path=settings.default_reference, builtin_voice="Adam",
                      denoise=False, speed=1.0, style_transfer=False)
    model = engine._get_model()
    a, _ = model._resolve_ref(None, str(settings.default_reference), False, False)
    b, _ = model._resolve_ref(None, str(output), False, False)
    a, b = np.asarray(a).ravel(), np.asarray(b).ravel()
    report = {"text": text, "reference": metrics(settings.default_reference), "output": metrics(output),
              "speaker_cosine_not_similarity_percent": float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))),
              "output_path": str(output), "style_transfer": False, "denoise": False, "speed": 1.0}
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
