from __future__ import annotations

import os
import uuid
from hmac import compare_digest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audio import AudioValidationError, inspect_wav, validate_reference
from .config import Settings, is_loopback_host, settings as default_settings
from .emotions import compile_emotion_script, tag_catalog
from .engine import DEFAULT_SPEED, MAX_SPEED, MIN_SPEED, SpeechEngine, VieneuEngine
from .jobs import JobManager, JobQueueFull


STATIC_DIR = Path(__file__).resolve().parent / "static"
BUILTIN_VOICES = (
    "Adam",
    "Phạm Tuyên",
    "Minh Đức",
    "Trúc Ly",
    "Mai Anh",
    "Quỳnh Anh",
    "Quang Sơn",
    "Ngọc Trân",
    "Xuân Vĩnh",
    "Thái Sơn",
    "Thùy Dung",
    "Mỹ Duyên",
)


class PreviewRequest(BaseModel):
    text: str = Field(min_length=1)
    speed: float = Field(default=DEFAULT_SPEED, ge=MIN_SPEED, le=MAX_SPEED)
    style_transfer: bool = False


def create_app(
    app_settings: Settings | None = None,
    engine: SpeechEngine | None = None,
) -> FastAPI:
    cfg = app_settings or default_settings
    cfg.prepare()
    speech_engine = engine or VieneuEngine(cfg)
    manager = JobManager(speech_engine, cfg.output_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.close()

    app = FastAPI(
        title="Tếu Voice Studio",
        version="0.3.3",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.engine = speech_engine
    app.state.jobs = manager

    def current_style_names() -> tuple[str, ...]:
        return tuple(getattr(speech_engine, "style_reference_names", ()) or ())

    def request_hostname(value: str) -> str | None:
        try:
            hostname = urlsplit(value if "://" in value else f"//{value}").hostname
        except ValueError:
            return None
        return (hostname or "").lower().rstrip(".") or None

    def is_allowed_host(value: str) -> bool:
        hostname = request_hostname(value)
        if hostname is None:
            return False
        if is_loopback_host(hostname):
            return True
        if cfg.lan_enabled and hostname == cfg.host:
            return True
        if cfg.ngrok_enabled and hostname == cfg.ngrok_host:
            return True
        # Allow Vercel deployment domains (*.vercel.app and custom domains via VERCEL_URL)
        if hostname.endswith(".vercel.app"):
            return True
        vercel_url = os.getenv("VERCEL_URL", "")
        if vercel_url and hostname == request_hostname(vercel_url):
            return True
        return False

    def has_access_key(request: Request) -> bool:
        expected = cfg.access_key
        supplied = request.headers.get("x-teu-access-key") or request.query_params.get(
            "access_key", ""
        )
        return bool(expected) and compare_digest(supplied, expected)

    @app.middleware("http")
    async def protect_local_voice_data(request: Request, call_next):
        if not is_allowed_host(request.headers.get("host", "")):
            return JSONResponse(
                status_code=403,
                content={"detail": "Host bị từ chối: không phải địa chỉ đã cấu hình cho ứng dụng."},
            )

        sensitive_path = request.url.path.startswith(("/api", "/audio", "/reference"))
        # LAN mode và ngrok mode đều yêu cầu access key (trừ /static)
        needs_key = (cfg.lan_enabled or cfg.ngrok_enabled) and not request.url.path.startswith("/static")
        if needs_key:
            if not has_access_key(request):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Thiếu hoặc sai khóa truy cập."},
                )
        if sensitive_path:
            fetch_site = request.headers.get("sec-fetch-site", "").lower()
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            cross_origin = fetch_site == "cross-site"
            cross_origin = cross_origin or bool(origin and not is_allowed_host(origin))
            cross_origin = cross_origin or bool(referer and not is_allowed_host(referer))
            if cross_origin:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Yêu cầu khác nguồn đã bị chặn để bảo vệ mẫu giọng."},
                )

        response = await call_next(request)
        if sensitive_path:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/config")
    def get_config() -> dict[str, object]:
        available, engine_detail = speech_engine.availability()
        style_names = current_style_names()
        reference: dict[str, object] = {"available": False}
        if cfg.default_reference.exists():
            try:
                info = inspect_wav(cfg.default_reference)
                reference = {
                    "available": True,
                    "url": "/reference/default",
                    **info.to_dict(),
                }
            except AudioValidationError as exc:
                reference = {"available": False, "error": str(exc)}
        return {
            "app_name": "Tếu Voice Studio",
            "engine": {
                "id": "vieneu-v3-turbo",
                "available": available,
                "detail": engine_detail,
                "precision": cfg.precision,
                "private": True,
            },
            "network": {
                "mode": "lan" if cfg.lan_enabled else "local",
                "access_key_required": cfg.lan_enabled,
            },
            "reference": reference,
            "emotion_tags": tag_catalog(),
            "style_transfer": {
                "available": bool(style_names),
                "styles": list(style_names),
                "default": False,
            },
            "builtin_voices": list(BUILTIN_VOICES),
            "limits": {
                "max_text_chars": cfg.max_text_chars,
                "max_upload_mb": cfg.max_upload_bytes // (1024 * 1024),
                "speed_min": MIN_SPEED,
                "speed_max": MAX_SPEED,
                "speed_default": DEFAULT_SPEED,
            },
        }

    @app.post("/api/preview")
    def preview(request: PreviewRequest) -> dict[str, object]:
        if len(request.text.strip()) > cfg.max_text_chars:
            raise HTTPException(
                status_code=422,
                detail=f"Nội dung tối đa {cfg.max_text_chars} ký tự mỗi lượt.",
            )
        try:
            plan = compile_emotion_script(request.text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = plan.preview_dict()
        payload["effects"] = {
            "speed": request.speed,
            "style_transfer": bool(
                request.style_transfer and current_style_names()
            ),
        }
        return payload

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        text: Annotated[str, Form()],
        speed: Annotated[float, Form(ge=MIN_SPEED, le=MAX_SPEED)] = DEFAULT_SPEED,
        reference_mode: Annotated[str, Form()] = "provided",
        builtin_voice: Annotated[str, Form()] = "Adam",
        denoise: Annotated[bool, Form()] = False,
        style_transfer: Annotated[bool, Form()] = False,
        consent: Annotated[bool, Form()] = False,
        reference_file: Annotated[UploadFile | None, File()] = None,
    ) -> dict[str, object]:
        normalized_text = text.strip()
        if not normalized_text:
            raise HTTPException(status_code=422, detail="Vui lòng nhập nội dung cần đọc.")
        if len(normalized_text) > cfg.max_text_chars:
            raise HTTPException(
                status_code=422,
                detail=f"Nội dung tối đa {cfg.max_text_chars} ký tự mỗi lượt.",
            )
        if builtin_voice not in BUILTIN_VOICES:
            raise HTTPException(status_code=422, detail="Giọng dựng sẵn không hợp lệ.")

        try:
            plan = compile_emotion_script(normalized_text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        reference_path: Path | None = None
        cleanup_reference = False
        if reference_mode == "provided":
            if not consent:
                raise HTTPException(
                    status_code=422,
                    detail="Bạn cần xác nhận quyền sử dụng mẫu giọng trước khi clone.",
                )
            if not cfg.default_reference.exists():
                raise HTTPException(status_code=409, detail="Chưa có mẫu giọng mặc định.")
            reference_path = cfg.default_reference
        elif reference_mode == "upload":
            if not consent:
                raise HTTPException(
                    status_code=422,
                    detail="Bạn cần xác nhận quyền sử dụng mẫu giọng trước khi clone.",
                )
            if reference_file is None:
                raise HTTPException(status_code=422, detail="Vui lòng chọn một tệp WAV.")
            suffix = Path(reference_file.filename or "").suffix.lower()
            if suffix != ".wav":
                raise HTTPException(status_code=422, detail="Mẫu giọng tải lên phải là WAV.")
            content = await reference_file.read(cfg.max_upload_bytes + 1)
            if len(content) > cfg.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Tệp mẫu giọng vượt quá giới hạn.")
            upload_dir = cfg.cache_dir / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            reference_path = upload_dir / f"{uuid.uuid4().hex}.wav"
            reference_path.write_bytes(content)
            cleanup_reference = True
            try:
                # Allow longer source clips; the engine picks the densest 3–8 s
                # speech window before enrollment.
                validate_reference(reference_path, strict_duration=False)
            except AudioValidationError as exc:
                reference_path.unlink(missing_ok=True)
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif reference_mode != "builtin":
            raise HTTPException(status_code=422, detail="Nguồn giọng không hợp lệ.")

        if reference_path is not None:
            try:
                validate_reference(reference_path, strict_duration=False)
            except AudioValidationError as exc:
                if cleanup_reference:
                    reference_path.unlink(missing_ok=True)
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        available, detail = speech_engine.availability()
        if not available:
            if cleanup_reference and reference_path is not None:
                reference_path.unlink(missing_ok=True)
            raise HTTPException(status_code=503, detail=detail)

        effective_style_transfer = bool(style_transfer and current_style_names())
        try:
            job = manager.submit(
                text=normalized_text,
                performance_text=plan.display_text,
                engine_segments=plan.segments,
                emotion_tags=plan.tag_ids,
                warnings=plan.warnings,
                speed=speed,
                reference_path=reference_path,
                builtin_voice=builtin_voice,
                denoise=denoise,
                style_transfer=effective_style_transfer,
                cleanup_reference=cleanup_reference,
            )
        except JobQueueFull as exc:
            if cleanup_reference and reference_path is not None:
                reference_path.unlink(missing_ok=True)
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return manager.get_public(job.id) or job.public_dict()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        job = manager.get_public(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy lượt tạo giọng.")
        return job

    @app.get("/audio/{filename}")
    def get_audio(filename: str) -> FileResponse:
        safe_name = Path(filename).name
        if safe_name != filename or not safe_name.endswith(".wav"):
            raise HTTPException(status_code=404, detail="Không tìm thấy âm thanh.")
        output_path = cfg.output_dir / safe_name
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Không tìm thấy âm thanh.")
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename=safe_name,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/reference/default")
    def get_default_reference() -> FileResponse:
        if not cfg.default_reference.exists():
            raise HTTPException(status_code=404, detail="Chưa có mẫu giọng mặc định.")
        return FileResponse(
            cfg.default_reference,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    @app.get("/favicon.png", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
