from __future__ import annotations

import time
import wave
from pathlib import Path
from typing import Sequence

from fastapi.testclient import TestClient

from teu_voice.app import create_app
from teu_voice.config import Settings
from teu_voice.emotions import EmotionSegment


LOCAL_BASE_URL = "http://127.0.0.1"


def make_wav(path: Path, duration: float = 4.0, sample_rate: int = 8_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * int(duration * sample_rate))


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def availability(self) -> tuple[bool, str]:
        return True, "fake engine ready"

    def synthesize(
        self,
        segments: Sequence[EmotionSegment],
        output_path: Path,
        *,
        reference_path: Path | None,
        builtin_voice: str,
        denoise: bool,
        speed: float = 1.0,
        style_transfer: bool = True,
    ) -> None:
        assert segments
        self.calls.append(
            {
                "segments": segments,
                "speed": speed,
                "style_transfer": style_transfer,
            }
        )
        make_wav(output_path, 0.2)


class FakeStyleEngine(FakeEngine):
    style_reference_names = ("excited", "funny")


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        cache_dir=tmp_path / ".cache",
        default_reference=tmp_path / "data" / "voice_reference.wav",
        precision="fp32",
        max_text_chars=2_000,
        max_upload_bytes=2 * 1024 * 1024,
    )


def test_config_and_preview(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path)
    make_wav(cfg.default_reference)
    app = create_app(cfg, FakeEngine())
    with TestClient(app, base_url=LOCAL_BASE_URL) as client:
        config = client.get("/api/config").json()
        assert config["engine"]["available"] is True
        assert config["reference"]["duration_seconds"] == 4.0
        assert "styles" not in config
        assert config["style_transfer"]["available"] is False
        assert config["style_transfer"]["default"] is False
        assert len(config["emotion_tags"]) >= 40
        assert config["limits"]["speed_min"] == 0.75
        assert config["limits"]["speed_max"] == 1.35

        response = client.post(
            "/api/preview",
            json={
                "text": "Xin chào. @hài hước Câu chốt đây!",
                "speed": 1.2,
                "style_transfer": True,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert "@hài_hước" in payload["performance_text"]
        assert "[" not in payload["performance_text"]
        assert payload["emotion_tags"] == ["funny"]
        assert payload["effects"] == {"speed": 1.2, "style_transfer": False}
        assert "engine_text" not in payload


def test_style_transfer_defaults_off_even_when_references_exist(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path)
    engine = FakeStyleEngine()
    app = create_app(cfg, engine)
    with TestClient(app, base_url=LOCAL_BASE_URL) as client:
        config = client.get("/api/config").json()
        assert config["style_transfer"] == {
            "available": True,
            "styles": ["excited", "funny"],
            "default": False,
        }

        response = client.post(
            "/api/jobs",
            data={"text": "@hài hước Một câu vui.", "reference_mode": "builtin"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"done", "error"}:
                break
            time.sleep(0.01)

        assert job["status"] == "done"
        assert job["effects"]["style_transfer"] is False
        assert engine.calls[0]["style_transfer"] is False


def test_clone_requires_consent(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path)
    make_wav(cfg.default_reference)
    app = create_app(cfg, FakeEngine())
    with TestClient(app, base_url=LOCAL_BASE_URL) as client:
        response = client.post(
            "/api/jobs",
            data={"text": "Xin chào", "reference_mode": "provided", "consent": "false"},
        )
        assert response.status_code == 422
        assert "quyền sử dụng" in response.json()["detail"]


def test_job_completes_and_audio_is_downloadable(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path)
    make_wav(cfg.default_reference)
    engine = FakeEngine()
    app = create_app(cfg, engine)
    with TestClient(app, base_url=LOCAL_BASE_URL) as client:
        response = client.post(
            "/api/jobs",
            data={
                "text": "@cười khẽ Một câu nói vui vẻ.",
                "speed": "1.20",
                "reference_mode": "provided",
                "consent": "true",
                "denoise": "false",
                "style_transfer": "false",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]

        job = None
        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"done", "error"}:
                break
            time.sleep(0.01)

        assert job is not None
        assert job["status"] == "done"
        assert job["speed"] == 1.2
        assert job["emotion_tags"] == ["chuckle"]
        assert "engine_segments" not in job
        assert engine.calls[0]["speed"] == 1.2
        assert engine.calls[0]["style_transfer"] is False
        assert job["effects"]["style_transfer"] is False
        assert engine.calls[0]["segments"][0].engine_text.startswith("[cười]")
        audio = client.get(job["audio_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert len(audio.content) > 44


def test_job_rejects_out_of_range_speed_and_unknown_tag(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path)
    app = create_app(cfg, FakeEngine())
    with TestClient(app, base_url=LOCAL_BASE_URL) as client:
        bad_speed = client.post(
            "/api/jobs",
            data={"text": "Xin chào", "speed": "1.8", "reference_mode": "builtin"},
        )
        assert bad_speed.status_code == 422

        bad_tag = client.post(
            "/api/jobs",
            data={"text": "@không_có Xin chào", "reference_mode": "builtin"},
        )
        assert bad_tag.status_code == 422
        assert "Không nhận ra tag" in bad_tag.json()["detail"]


def test_non_loopback_host_and_cross_site_voice_requests_are_blocked(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path)
    make_wav(cfg.default_reference)
    app = create_app(cfg, FakeEngine())
    with TestClient(app, base_url=LOCAL_BASE_URL) as client:
        hostile_host = client.get("/api/config", headers={"Host": "evil.example"})
        assert hostile_host.status_code == 403

        cross_site = client.get(
            "/reference/default",
            headers={
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        assert cross_site.status_code == 403

        same_origin = client.get(
            "/reference/default",
            headers={"Origin": LOCAL_BASE_URL, "Sec-Fetch-Site": "same-origin"},
        )
        assert same_origin.status_code == 200
        assert same_origin.headers["cache-control"] == "no-store"


def test_private_lan_requires_the_runtime_access_key(tmp_path: Path) -> None:
    cfg = Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        cache_dir=tmp_path / ".cache",
        default_reference=tmp_path / "data" / "voice_reference.wav",
        host="172.28.0.166",
        access_key="temporary-lan-key",
    )
    make_wav(cfg.default_reference)
    app = create_app(cfg, FakeEngine())
    with TestClient(app, base_url="http://172.28.0.166:8765") as client:
        blocked = client.get("/api/config")
        assert blocked.status_code == 401

        root = client.get("/?access_key=temporary-lan-key")
        assert root.status_code == 200

        config = client.get(
            "/api/config", headers={"X-Teu-Access-Key": "temporary-lan-key"}
        )
        assert config.status_code == 200
        assert config.json()["network"] == {
            "mode": "lan",
            "access_key_required": True,
        }

        audio = client.get(
            "/reference/default?access_key=temporary-lan-key",
            headers={"Origin": "http://172.28.0.166:8765", "Sec-Fetch-Site": "same-origin"},
        )
        assert audio.status_code == 200

        cross_site = client.get(
            "/api/config?access_key=temporary-lan-key",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert cross_site.status_code == 403
