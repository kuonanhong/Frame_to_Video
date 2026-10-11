"""Native CPU image adapters. Heavy dependencies are imported only at inference time."""
import gc
import inspect
import io
import math
import os
import threading
from dataclasses import dataclass
from catalog import CATALOG, MODEL_ROOT, model_status

# No automatic network fallback during model loading.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
MAX_INPUT_BYTES = 12 * 1024 * 1024
MAX_INPUT_PIXELS = 24_000_000


class Cancelled(Exception):
    pass


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    expert: str
    prompt: str
    image: bytes
    mask: bytes | None
    steps: int
    strength: float
    guidance: float
    image_guidance: float
    seed: int
    max_side: int


def number(fields, name, default, low, high, integer=False):
    try:
        raw = str(fields.get(name, default))
        value = int(raw) if integer else float(raw)
    except (ValueError, TypeError):
        raise InputError(f'{name}: invalid number') from None
    if not math.isfinite(value) or not low <= value <= high:
        raise InputError(f'{name}: allowed range {low}–{high}')
    return value


def validate_request(fields, files):
    expert = fields.get('expert', '')
    if expert not in CATALOG:
        raise InputError('Unknown expert')
    prompt = fields.get('prompt', '').strip()
    if not prompt or len(prompt) > 1000:
        raise InputError('Prompt must contain 1–1000 characters')
    image = files.get('image')
    mask = files.get('mask')
    for value in (image, mask):
        if value is not None and (not value or len(value) > MAX_INPUT_BYTES):
            raise InputError('Each image/mask must be 1 byte–12 MiB')
    if image is None:
        raise InputError('An uploaded image is required')
    if expert == 'sd-inpaint' and mask is None:
        raise InputError('Inpainting needs a mask: white edits, black preserves')
    steps = number(fields, 'steps', CATALOG[expert]['default_steps'], 1, CATALOG[expert]['max_steps'], True)
    strength = number(fields, 'strength', .75, .1, 1)
    if expert == 'sd-turbo' and steps * strength < 1:
        raise InputError('SD-Turbo requires steps × strength ≥ 1')
    return Request(expert, prompt, image, mask, steps, strength,
                   number(fields, 'guidance', 0 if expert == 'sd-turbo' else 7.5, 0 if expert == 'sd-turbo' else 1, 15),
                   number(fields, 'image_guidance', 1.5, 1, 3),
                   number(fields, 'seed', 42, 0, 2**32-1, True),
                   number(fields, 'max_side', 512, 256, 512, True))


def open_image(data, mode='RGB'):
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in {'PNG', 'JPEG', 'WEBP', 'BMP'}:
            raise InputError('Use PNG, JPEG, WEBP or BMP')
        if image.width * image.height > MAX_INPUT_PIXELS:
            raise InputError('Input image exceeds 24 megapixels; resize it first')
        image.load()
        return ImageOps.exif_transpose(image).convert(mode)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise InputError('Invalid or oversized image') from None


def prepare_images(request):
    from PIL import Image, ImageOps
    image = open_image(request.image)
    source_size = image.size
    # Letterbox to multiples of 8, preserving aspect. No arbitrary stretching.
    ratio = min(1, request.max_side / max(image.size))
    scaled = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    target = tuple(min(request.max_side // 8 * 8, max(64, math.ceil(v / 8) * 8)) for v in scaled)
    image = ImageOps.pad(image, target, method=Image.Resampling.LANCZOS, color=(24, 24, 24))
    mask = None
    if request.expert == 'sd-inpaint':
        mask = open_image(request.mask, 'L')
        if mask.size != source_size:
            raise InputError('Mask dimensions must match the source image')
        mask = ImageOps.pad(mask, target, method=Image.Resampling.NEAREST, color=0)
        if mask.getextrema()[1] == 0:
            raise InputError('Mask is all black; paint the region to edit in white')
    return image, mask


def load_pipeline(expert, model_path):
    import torch
    from diffusers import (AutoPipelineForImage2Image, StableDiffusionInstructPix2PixPipeline,
                           StableDiffusionInpaintPipeline, EulerAncestralDiscreteScheduler)
    classes = {'sd-turbo': AutoPipelineForImage2Image,
               'instruct-pix2pix': StableDiffusionInstructPix2PixPipeline,
               'sd-inpaint': StableDiffusionInpaintPipeline}
    # On-disk fp16 Safetensors are upcast to float32; CPU is explicit.
    pipeline = classes[expert].from_pretrained(str(model_path), local_files_only=True,
                    torch_dtype=torch.float32, variant='fp16', use_safetensors=True)
    pipeline.to('cpu')
    pipeline.enable_attention_slicing('auto')
    pipeline.enable_vae_slicing()
    pipeline.set_progress_bar_config(disable=True)
    if expert == 'instruct-pix2pix':
        pipeline.scheduler = EulerAncestralDiscreteScheduler.from_config(pipeline.scheduler.config)
    # Retain any safety checker provided by the source pipeline.
    return pipeline


def run(request, cancel_event: threading.Event, progress, model_root=MODEL_ROOT):
    if cancel_event.is_set():
        raise Cancelled()
    if not model_status(request.expert, model_root)['installed']:
        raise InputError('Model is not installed. Run native_cpu/fetch_models.py explicitly first.')
    image, mask = prepare_images(request)
    progress(0, 'loading')
    import torch
    torch.set_num_threads(max(1, min(8, os.cpu_count() or 2)))
    pipe = None
    try:
        pipe = load_pipeline(request.expert, model_root / request.expert)
        if cancel_event.is_set():
            raise Cancelled()
        args = dict(prompt=request.prompt, image=image, num_inference_steps=request.steps,
                    generator=torch.Generator(device='cpu').manual_seed(request.seed), num_images_per_prompt=1)
        effective_steps = request.steps
        if request.expert == 'sd-turbo':
            args.update(strength=request.strength, guidance_scale=0.0)
            effective_steps = int(request.steps * request.strength)
        elif request.expert == 'instruct-pix2pix':
            args.update(guidance_scale=request.guidance, image_guidance_scale=request.image_guidance)
        else:
            # Inpaint defaults to the model's square sample size unless dimensions are explicit.
            # Preserve the prepared image/mask geometry, including non-square uploads.
            args.update(mask_image=mask, width=image.width, height=image.height,
                        strength=.99, guidance_scale=request.guidance)
            # Keep at least one step when a user explicitly selects a tiny step count.
            if request.steps == 1:
                args['strength'] = 1.0
            effective_steps = max(1, int(request.steps * args['strength']))

        def on_step_end(_pipeline, step, _time, values):
            if cancel_event.is_set():
                raise Cancelled()
            progress(min(95, round(5 + 90 * (step + 1) / max(1, effective_steps))), 'denoising')
            return values

        signature = inspect.signature(pipe.__call__).parameters
        if 'callback_on_step_end' in signature:
            args.update(callback_on_step_end=on_step_end, callback_on_step_end_tensor_inputs=['latents'])
        elif 'callback' in signature:
            def legacy(step, timestep, latent):
                on_step_end(pipe, step, timestep, {'latents': latent})
            args.update(callback=legacy, callback_steps=1)
        else:
            raise RuntimeError('Unsupported Diffusers callback API; install the pinned dependencies.')
        progress(5, 'denoising')
        with torch.inference_mode():
            result = pipe(**args)
        if cancel_event.is_set():
            raise Cancelled()
        if any(getattr(result, 'nsfw_content_detected', None) or []):
            raise InputError('The model safety checker rejected this result. Try a different image or prompt.')
        output_image = result.images[0].convert('RGB')
        if output_image.size != image.size:
            raise RuntimeError('Model output dimensions do not match the prepared image; refusing a misaligned composite.')
        if request.expert == 'sd-inpaint':
            # Guarantee pixels outside a black mask match the prepared input.
            from PIL import Image
            output_image = Image.composite(output_image, image, mask)
        output = io.BytesIO()
        output_image.save(output, format='PNG')
        progress(100, 'done')
        return output.getvalue(), {'expert': request.expert, 'width': output_image.width,
                                  'height': output_image.height, 'seed': request.seed,
                                  'device': 'cpu', 'dtype': 'float32', 'output_kind': 'still-image'}
    finally:
        del pipe
        gc.collect()
