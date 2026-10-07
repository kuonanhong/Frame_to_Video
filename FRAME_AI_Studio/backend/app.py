"""Frame's local inference API. Importing this module never imports torch."""
from __future__ import annotations

import hmac
import math
import os
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

IMAGE_LIMIT = 20 * 1024 * 1024
VIDEO_LIMIT = 80 * 1024 * 1024
BODY_LIMIT = VIDEO_LIMIT + 256 * 1024
MODELS = {
    "sd-turbo": "stabilityai/sd-turbo",
    "ltx-2b": "Lightricks/LTX-Video-0.9.5",
    "wan-5b": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
}
TERMINAL = {"succeeded", "failed", "cancelled"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("FRAME_DATA_DIR", "./data")).resolve())
    api_key: str = field(default_factory=lambda: os.getenv("FRAME_API_KEY", ""))
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.strip() for x in os.getenv(
            "FRAME_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080",
        ).split(",") if x.strip()
    ))
    keep_hours: float = field(default_factory=lambda: float(os.getenv("FRAME_KEEP_HOURS", "24")))
    max_jobs: int = field(default_factory=lambda: int(os.getenv("FRAME_MAX_JOBS", "100")))
    keep_inputs: bool = field(default_factory=lambda: os.getenv("FRAME_KEEP_INPUTS", "0") == "1")
    device: str = field(default_factory=lambda: os.getenv("FRAME_DEVICE", "auto"))
    low_memory: bool = field(default_factory=lambda: os.getenv("FRAME_LOW_MEMORY", "1") == "1")
    model_cache: str | None = field(default_factory=lambda: os.getenv("FRAME_MODEL_CACHE") or None)

    def validate(self) -> None:
        if "*" in self.allowed_origins:
            raise ValueError("FRAME_ALLOWED_ORIGINS must list explicit origins; '*' is unsupported.")
        if not math.isfinite(self.keep_hours) or self.keep_hours <= 0:
            raise ValueError("FRAME_KEEP_HOURS must be a positive finite number.")
        if self.max_jobs < 1 or self.max_jobs > 10000:
            raise ValueError("FRAME_MAX_JOBS must be between 1 and 10000.")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("FRAME_DEVICE must be auto, cpu, or cuda.")


@dataclass(frozen=True)
class JobSpec:
    id: str
    workflow: str
    model: str
    prompt: str
    negative_prompt: str
    duration: float
    aspect: str
    seed: int
    strength: float


class JobCancelled(Exception):
    """Raised cooperatively from the model's step callback."""


@dataclass
class Job:
    spec: JobSpec
    source: Path | None
    output: Path
    status: str = "queued"
    progress: int = 0
    message: str = "Queued for the local worker"
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


# Hook for contract testing: no framework, torch, or model weights are needed.
InferenceRunner = Callable[[JobSpec, Path | None, Path, Callable[[int, str], None], threading.Event], None]


class JobManager:
    def __init__(self, settings: Settings, runner: InferenceRunner | None = None):
        self.settings = settings
        self.runner = runner
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.pending: queue.Queue[str] = queue.Queue()
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.engine = None
        self.upload_dir = settings.data_dir / "uploads"
        self.output_dir = settings.data_dir / "outputs"

    def start(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup(orphan_files=True)
        self.stop.clear()
        self.worker = threading.Thread(target=self._work, name="frame-inference", daemon=True)
        self.worker.start()

    def close(self) -> None:
        self.stop.set()
        with self.lock:
            for job in self.jobs.values():
                if job.status not in TERMINAL:
                    job.cancel.set()
                    if job.status == "queued":
                        job.status, job.message = "cancelled", "Server is shutting down"
                        job.finished_at = time.time()
                        self._remove_source(job)
        if self.worker:
            self.worker.join(timeout=2)

    def _remove_source(self, job: Job) -> None:
        if job.source and not self.settings.keep_inputs:
            job.source.unlink(missing_ok=True)

    def cleanup(self, orphan_files: bool = False) -> None:
        cutoff = time.time() - self.settings.keep_hours * 3600
        with self.lock:
            expired = [jid for jid, job in self.jobs.items()
                       if job.finished_at is not None and job.finished_at < cutoff]
            for jid in expired:
                job = self.jobs.pop(jid)
                job.output.unlink(missing_ok=True)
                if job.source:
                    job.source.unlink(missing_ok=True)
            if orphan_files:
                active_paths = {path for job in self.jobs.values() if job.status not in TERMINAL
                                for path in (job.source, job.output) if path is not None}
                for directory in (self.upload_dir, self.output_dir):
                    for path in directory.glob("*"):
                        if path not in active_paths and path.is_file() and path.stat().st_mtime < cutoff:
                            path.unlink(missing_ok=True)

    def submit(self, spec: JobSpec, source: Path | None) -> dict:
        self.cleanup()
        with self.lock:
            if len(self.jobs) >= self.settings.max_jobs:
                raise HTTPException(429, "Local job capacity reached. Wait for retention cleanup or restart after clearing data.")
            suffix = ".png" if spec.workflow == "text-image" else ".mp4"
            job = Job(spec=spec, source=source, output=self.output_dir / (spec.id + suffix))
            self.jobs[spec.id] = job
            self.pending.put(spec.id)
            return self._serialize(job)

    def _serialize(self, job: Job) -> dict:
        return {
            "id": job.spec.id, "workflow": job.spec.workflow, "model": job.spec.model,
            "status": job.status, "progress": job.progress, "message": job.message,
            "error": job.error, "created_at": job.created_at,
            "cancel_requested": job.cancel.is_set(),
            "output_url": f"/api/files/{job.spec.id}" if job.status == "succeeded" else None,
            "output_type": "image" if job.spec.workflow == "text-image" else "video",
        }

    def get(self, jid: str) -> dict:
        self.cleanup()
        with self.lock:
            if jid not in self.jobs:
                raise HTTPException(404, "Job not found or expired")
            return self._serialize(self.jobs[jid])

    def cancel_job(self, jid: str) -> dict:
        with self.lock:
            job = self.jobs.get(jid)
            if job is None:
                raise HTTPException(404, "Job not found or expired")
            if job.status in TERMINAL:
                return self._serialize(job)
            job.cancel.set()
            if job.status == "queued":
                job.status, job.message = "cancelled", "Cancelled before inference"
                job.finished_at = time.time()
                self._remove_source(job)
            else:
                job.message = "Cancellation requested; stopping at the next model step"
            return self._serialize(job)

    def _work(self) -> None:
        last_cleanup = 0.0
        while not self.stop.is_set():
            if time.time() - last_cleanup > 60:
                self.cleanup(orphan_files=True)
                last_cleanup = time.time()
            try:
                jid = self.pending.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                with self.lock:
                    job = self.jobs.get(jid)
                    if job is None or job.cancel.is_set():
                        continue
                    job.status, job.message = "running", "Preparing inference"

                def report(progress: int, message: str) -> None:
                    if job.cancel.is_set() or self.stop.is_set():
                        raise JobCancelled()
                    with self.lock:
                        job.progress = max(job.progress, min(99, max(0, int(progress))))
                        job.message = message

                report(1, "Loading model; first use downloads weights")
                if self.runner is not None:
                    self.runner(job.spec, job.source, job.output, report, job.cancel)
                else:
                    if self.engine is None:
                        from infer import InferenceEngine
                        self.engine = InferenceEngine(self.settings)
                    self.engine.run(job.spec, job.source, job.output, report, job.cancel)
                if job.cancel.is_set() or self.stop.is_set():
                    raise JobCancelled()
                if not job.output.is_file() or job.output.stat().st_size == 0:
                    raise RuntimeError("Inference did not produce an output file")
                with self.lock:
                    job.status, job.progress, job.message = "succeeded", 100, "Ready"
            except JobCancelled:
                with self.lock:
                    job.status, job.message = "cancelled", "Cancelled"
                job.output.unlink(missing_ok=True)
            except Exception as exc:
                # Never return tracebacks, bearer credentials, or user filesystem paths.
                import logging
                logging.getLogger("frame").exception("Inference failed for job %s", jid)
                message = str(exc) or type(exc).__name__
                for sensitive in (self.settings.api_key, str(self.settings.data_dir), self.settings.model_cache):
                    if sensitive:
                        message = message.replace(sensitive, "[redacted]")
                with self.lock:
                    job.status, job.message, job.error = "failed", "Inference failed", message[:700]
                job.output.unlink(missing_ok=True)
            finally:
                with self.lock:
                    job = self.jobs.get(jid)
                    if job is not None and job.status in TERMINAL:
                        job.finished_at = time.time()
                        self._remove_source(job)
                self.pending.task_done()


class UploadTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Bounds streamed multipart bodies before FastAPI spools uploaded files."""
    def __init__(self, app, limit: int = BODY_LIMIT):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        if length > self.limit:
            return await JSONResponse({"detail": "Request exceeds the 80 MB upload limit"}, status_code=413)(scope, receive, send)
        total = 0
        oversized = False
        response_started = False
        replacement_sent = False
        error_body = b'{"detail":"Request exceeds the 80 MB upload limit"}'

        async def bounded_receive():
            nonlocal total, oversized
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.limit:
                oversized = True
                raise UploadTooLarge()
            return message

        async def limited_send(message):
            # FastAPI translates body-parser exceptions to HTTP 400. Preserve a
            # clear 413 contract for streamed bodies whose size was undeclared.
            nonlocal response_started, replacement_sent
            if message["type"] == "http.response.start":
                response_started = True
                if oversized:
                    message = {"type": "http.response.start", "status": 413,
                               "headers": [(b"content-type", b"application/json"),
                                           (b"content-length", str(len(error_body)).encode())]}
            elif oversized and message["type"] == "http.response.body":
                if replacement_sent:
                    return
                replacement_sent = True
                message = {"type": "http.response.body", "body": error_body, "more_body": False}
            await send(message)

        try:
            await self.app(scope, bounded_receive, limited_send)
        except UploadTooLarge:
            if not response_started:
                await JSONResponse({"detail": "Request exceeds the 80 MB upload limit"}, status_code=413)(scope, receive, send)


def _validate_spec(workflow, model, prompt, negative_prompt, duration, aspect, seed, strength) -> JobSpec:
    if workflow not in {"text-image", "image-video", "video-video"}:
        raise HTTPException(422, "Unsupported workflow")
    model = model or ("sd-turbo" if workflow == "text-image" else "ltx-2b")
    supported = {"text-image": {"sd-turbo"}, "image-video": {"ltx-2b", "wan-5b"}, "video-video": {"ltx-2b"}}
    if model not in supported[workflow]:
        raise HTTPException(422, "Model does not support this workflow")
    prompt = prompt.strip()
    if not prompt or len(prompt) > 1800 or len(negative_prompt) > 1800:
        raise HTTPException(422, "Prompt must contain 1–1800 characters; negative prompt at most 1800")
    if not math.isfinite(duration) or not 1 <= duration <= 5:
        raise HTTPException(422, "Duration must be between 1 and 5 seconds")
    if aspect not in {"16:9", "9:16", "1:1"}:
        raise HTTPException(422, "Aspect must be 16:9, 9:16, or 1:1")
    if seed < 0 or seed > 4294967295:
        raise HTTPException(422, "Seed must be between 0 and 4294967295")
    if not math.isfinite(strength) or not .05 <= strength <= .95:
        raise HTTPException(422, "Strength must be between 0.05 and 0.95")
    return JobSpec(uuid.uuid4().hex, workflow, model, prompt, negative_prompt.strip(), duration, aspect, seed, strength)


async def _save_upload(upload: UploadFile, spec: JobSpec, directory: Path) -> Path:
    limit = IMAGE_LIMIT if spec.workflow == "image-video" else VIDEO_LIMIT
    path = directory / (spec.id + ".upload")
    size = 0
    try:
        with path.open("xb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit")
                target.write(chunk)
        if not size:
            raise HTTPException(422, "Uploaded file is empty")
        if spec.workflow == "image-video":
            from PIL import Image, UnidentifiedImageError
            try:
                with Image.open(path) as im:
                    if im.format not in {"PNG", "JPEG", "WEBP"}:
                        raise HTTPException(415, "Use a PNG, JPEG, or WebP image")
                    if min(im.size) < 16 or im.width * im.height > 25_000_000:
                        raise HTTPException(422, "Image must be at least 16 px per side and at most 25 megapixels")
                    suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[im.format]
                    im.verify()
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
                raise HTTPException(415, "Cannot decode this image") from exc
        else:
            with path.open("rb") as source:
                header = source.read(32)
            if header.startswith(b"\x1aE\xdf\xa3"):
                suffix = ".webm"
            elif len(header) >= 12 and header[4:8] in {b"ftyp", b"moov", b"mdat", b"wide", b"free"}:
                suffix = ".mp4"
            else:
                raise HTTPException(415, "Use an MP4, WebM, or MOV video")
        final = path.with_suffix(suffix)
        path.rename(final)
        return final
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def create_app(inference_runner: InferenceRunner | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.validate()
    manager = JobManager(settings, inference_runner)

    @asynccontextmanager
    async def lifespan(_app):
        manager.start()
        try:
            yield
        finally:
            manager.close()

    app = FastAPI(title="Frame local inference", version="1.0.0", lifespan=lifespan)
    app.state.manager = manager
    app.state.settings = settings
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_credentials=False, allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], expose_headers=["Content-Disposition"])

    async def authenticate(request: Request):
        if not settings.api_key:
            return
        value = request.headers.get("authorization", "")
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), settings.api_key.encode()):
            raise HTTPException(401, "A valid Bearer token is required", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "models": MODELS, "auth_required": bool(settings.api_key),
                "worker_running": bool(manager.worker and manager.worker.is_alive()),
                "device": settings.device, "inference_state": "loaded" if manager.engine else "lazy",
                "max_image_mb": 20, "max_video_mb": 80}

    @app.post("/api/jobs", status_code=202, dependencies=[Depends(authenticate)])
    async def submit_job(
        workflow: str = Form(...), prompt: str = Form(...), model: str | None = Form(None),
        file: UploadFile | None = File(None), duration: float = Form(3), aspect: str = Form("16:9"),
        seed: int = Form(0), strength: float = Form(.65), negative_prompt: str = Form(""),
    ):
        source = None
        try:
            spec = _validate_spec(workflow, model, prompt, negative_prompt, duration, aspect, seed, strength)
            if workflow == "text-image" and file is not None:
                raise HTTPException(422, "text-image does not accept an uploaded file")
            if workflow != "text-image":
                if file is None:
                    raise HTTPException(422, "This workflow requires an uploaded file")
                source = await _save_upload(file, spec, manager.upload_dir)
            return manager.submit(spec, source)
        except Exception:
            if source:
                source.unlink(missing_ok=True)
            raise
        finally:
            if file is not None:
                await file.close()

    @app.get("/api/jobs/{jid}", dependencies=[Depends(authenticate)])
    async def get_job(jid: str):
        return manager.get(jid)

    @app.delete("/api/jobs/{jid}", dependencies=[Depends(authenticate)])
    async def cancel_job(jid: str):
        return manager.cancel_job(jid)

    @app.get("/api/files/{jid}", dependencies=[Depends(authenticate)])
    async def get_file(jid: str):
        manager.get(jid)
        with manager.lock:
            job = manager.jobs.get(jid)
            if job is None:
                raise HTTPException(404, "Job not found or expired")
            if job.status != "succeeded" or not job.output.is_file():
                raise HTTPException(409, "Output is not ready")
            mime = "image/png" if job.spec.workflow == "text-image" else "video/mp4"
            return FileResponse(job.output, media_type=mime, filename=f"frame-{jid}{job.output.suffix}",
                                content_disposition_type="inline", headers={"Cache-Control": "private, max-age=3600"})

    return app


app = create_app()
