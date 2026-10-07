"""Real, lazy Diffusers inference. GPU recipes have not been hardware-tested here."""
from __future__ import annotations

import gc
import math
import threading
from pathlib import Path

from app import JobCancelled, JobSpec, Settings

MODEL_REVISIONS = {
    "sd-turbo": ("stabilityai/sd-turbo", "b261bac6fd2cf515557d5d0707481eafa0485ec2"),
    "ltx-2b": ("Lightricks/LTX-Video-0.9.5", "e58e28c39631af4d1468ee57a853764e11c1d37e"),
    "wan-5b": ("Wan-AI/Wan2.2-TI2V-5B-Diffusers", "b8fff7315c768468a5333511427288870b2e9635"),
}
FPS = 24
# LTX draft dimensions preserve the requested ratio and satisfy its 32px grid.
LTX_SIZES = {"16:9": (512, 288), "9:16": (288, 512), "1:1": (512, 512)}
# Wan 5B's documented landscape/portrait dimensions. Its native 704px side
# makes the wide/tall presets approximate, rather than exact, 16:9 / 9:16.
WAN_SIZES = {"16:9": (1280, 704), "9:16": (704, 1280), "1:1": (896, 896)}


def frame_count(duration: float, temporal_stride: int) -> int:
    """Round upward to the model's k*stride+1 temporal grid."""
    return int(math.ceil(max(0, duration * FPS - 1) / temporal_stride)) * temporal_stride + 1


class InferenceEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pipeline = None
        self.loaded_key = None

    @staticmethod
    def _check_cancel(cancel: threading.Event):
        if cancel.is_set():
            raise JobCancelled()

    def _device(self, torch, spec: JobSpec) -> str:
        available = torch.cuda.is_available()
        requested = self.settings.device
        device = "cuda" if (requested == "cuda" or requested == "auto" and available) else "cpu"
        if device == "cuda" and not available:
            raise RuntimeError("CUDA is unavailable. Install the NVIDIA driver and a compatible CUDA PyTorch wheel.")
        if spec.workflow != "text-image" and device != "cuda":
            raise RuntimeError("Video inference requires a CUDA GPU. This server does not substitute a simulated video.")
        return device

    def _load(self, torch, spec: JobSpec, device: str, report, cancel):
        key = (spec.model, device)
        if self.pipeline is not None and self.loaded_key == key:
            return self.pipeline
        # Only one pipeline is retained, so changing models does not accumulate VRAM.
        self.pipeline, self.loaded_key = None, None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        self._check_cancel(cancel)
        model_id, revision = MODEL_REVISIONS[spec.model]
        load_kwargs = {"revision": revision, "cache_dir": self.settings.model_cache}
        if spec.model == "sd-turbo":
            from diffusers import AutoPipelineForText2Image
            pipeline = AutoPipelineForText2Image.from_pretrained(
                model_id, **load_kwargs, variant="fp16",
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            )
        else:
            # BF16 is the officially documented recipe. FP16 lets older CUDA
            # hardware attempt LTX, without promising equal stability or quality.
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            if spec.model == "ltx-2b":
                from diffusers import LTXConditionPipeline
                pipeline = LTXConditionPipeline.from_pretrained(model_id, **load_kwargs, torch_dtype=dtype)
            else:
                from diffusers import AutoencoderKLWan, WanImageToVideoPipeline
                vae = AutoencoderKLWan.from_pretrained(model_id, **load_kwargs, subfolder="vae", torch_dtype=torch.float32)
                pipeline = WanImageToVideoPipeline.from_pretrained(
                    model_id, **load_kwargs, vae=vae, torch_dtype=dtype, expand_timesteps=True,
                )
            pipeline.vae.enable_tiling()
        self._check_cancel(cancel)
        if self.settings.low_memory and device == "cuda":
            pipeline.enable_model_cpu_offload()
        else:
            pipeline.to(device)
        pipeline.set_progress_bar_config(disable=True)
        self.pipeline, self.loaded_key = pipeline, key
        report(18, "Model loaded")
        return pipeline

    @staticmethod
    def _image(source: Path, size: tuple[int, int]):
        from PIL import Image, ImageOps
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)

    def _video_frames(self, source: Path, count: int, size, report, cancel):
        """Decode only the requested opening clip and sample it at 24fps.

        Bounds decoding work by duration and rejects excessive source frames.
        Short clips are padded by repeating their last frame; audio is omitted.
        """
        import imageio.v2 as imageio
        from PIL import Image, ImageOps
        frames = []
        try:
            reader = imageio.get_reader(str(source), format="FFMPEG")
            try:
                metadata = reader.get_meta_data()
                source_fps = float(metadata.get("fps") or FPS)
                if not math.isfinite(source_fps) or not 1 <= source_fps <= 240:
                    raise RuntimeError("Source video must use a frame rate between 1 and 240 fps.")
                for index in range(count):
                    self._check_cancel(cancel)
                    source_index = int(round(index * source_fps / FPS))
                    try:
                        pixels = reader.get_data(source_index)
                    except (IndexError, StopIteration):
                        if not frames:
                            raise RuntimeError("Video contains no decodable frames.")
                        frames.extend([frames[-1].copy() for _ in range(count - len(frames))])
                        break
                    if pixels.shape[0] * pixels.shape[1] > 25_000_000:
                        raise RuntimeError("Source video frames must be at most 25 megapixels.")
                    im = Image.fromarray(pixels).convert("RGB")
                    frames.append(ImageOps.fit(im, size, method=Image.Resampling.LANCZOS))
                    report(19 + int((index + 1) / count * 3), "Reading source video")
            finally:
                reader.close()
        except JobCancelled:
            raise
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError("Cannot decode source video. Use a valid MP4, WebM, or MOV with a supported codec.") from exc
        return frames

    def _encode_video(self, frames, output, report, cancel):
        import imageio.v2 as imageio
        import numpy as np
        report(94, "Encoding MP4")
        writer = imageio.get_writer(
            str(output), format="FFMPEG", fps=FPS, codec="libx264",
            pixelformat="yuv420p", macro_block_size=1,
            output_params=["-movflags", "+faststart"],
        )
        try:
            for index, frame in enumerate(frames):
                self._check_cancel(cancel)
                writer.append_data(np.asarray(frame))
                report(94 + int((index + 1) / len(frames) * 5), "Encoding MP4")
        finally:
            writer.close()

    def run(self, spec: JobSpec, source: Path | None, output: Path, report, cancel: threading.Event):
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("Inference dependencies are missing. Install the backend requirements and CUDA PyTorch.") from exc
        device = self._device(torch, spec)
        pipeline = self._load(torch, spec, device, report, cancel)
        generator = torch.Generator(device=device).manual_seed(spec.seed)
        steps = 1 if spec.workflow == "text-image" else 50 if spec.model == "wan-5b" else 40

        def callback(_pipeline, index, _timestep, callback_kwargs):
            self._check_cancel(cancel)
            report(23 + int((index + 1) / steps * 69), "Generating image" if spec.workflow == "text-image" else "Generating video")
            return callback_kwargs

        self._check_cancel(cancel)
        with torch.inference_mode():
            if spec.workflow == "text-image":
                # SD-Turbo's reliable baseline is square 512px; aspect applies
                # to video workflows only. Negative prompt is ignored by Turbo.
                result = pipeline(
                    prompt=spec.prompt, height=512, width=512, num_inference_steps=1,
                    guidance_scale=0.0, generator=generator, callback_on_step_end=callback,
                ).images[0]
                self._check_cancel(cancel)
                report(95, "Saving image")
                result.save(output, format="PNG")
                return
            if source is None:
                raise RuntimeError("Source upload is missing")
            if spec.model == "wan-5b":
                size = WAN_SIZES[spec.aspect]
                frames = pipeline(
                    image=self._image(source, size), prompt=spec.prompt,
                    negative_prompt=spec.negative_prompt or None,
                    width=size[0], height=size[1], num_frames=frame_count(spec.duration, 4),
                    num_inference_steps=steps, guidance_scale=5.0, generator=generator,
                    output_type="pil", callback_on_step_end=callback,
                ).frames[0]
            else:
                from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
                size = LTX_SIZES[spec.aspect]
                count = frame_count(spec.duration, 8)
                if spec.workflow == "image-video":
                    condition = LTXVideoCondition(image=self._image(source, size), frame_index=0, strength=1.0)
                else:
                    source_frames = self._video_frames(source, count, size, report, cancel)
                    # Below 1 preserves useful source motion while allowing edits.
                    # Keeping this at 1 hard-copies every source latent frame.
                    condition = LTXVideoCondition(video=source_frames, frame_index=0, strength=spec.strength)
                frames = pipeline(
                    conditions=[condition], prompt=spec.prompt,
                    negative_prompt=spec.negative_prompt or None,
                    width=size[0], height=size[1], num_frames=count, frame_rate=FPS,
                    num_inference_steps=steps, guidance_scale=3.0, denoise_strength=1.0,
                    generator=generator, output_type="pil", callback_on_step_end=callback,
                ).frames[0]
        self._check_cancel(cancel)
        self._encode_video(frames, output, report, cancel)
