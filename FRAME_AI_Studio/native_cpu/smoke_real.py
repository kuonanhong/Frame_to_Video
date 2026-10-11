#!/usr/bin/env python3
"""Explicit, measured real-weight smoke test AFTER local model installation."""
import argparse
from dataclasses import asdict
import datetime
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import threading
import time
from catalog import CATALOG, MODEL_ROOT, model_status, sha256
from inference import prepare_images, run, validate_request


def main():
    parser = argparse.ArgumentParser(description='Run real native CPU inference using already-installed weights. May take minutes or longer.')
    parser.add_argument('--model', choices=CATALOG, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--mask', type=Path)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--steps', type=int)
    parser.add_argument('--max-side', type=int, default=512)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--strength', type=float, default=.75)
    parser.add_argument('--guidance', type=float)
    parser.add_argument('--image-guidance', type=float, default=1.5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report_path = args.output.with_suffix('.report.json')
    if args.output.exists() or report_path.exists():
        parser.error('Output or report exists; choose a new filename to avoid overwriting it')
    state = model_status(args.model, verify_hashes=True)
    if not state['installed']:
        parser.error('Model is absent or failed SHA-256 verification. Use fetch_models.py first.')
    fields = {'expert': args.model, 'prompt': args.prompt, 'max_side': args.max_side,
              'seed': args.seed, 'strength': args.strength, 'image_guidance': args.image_guidance}
    for field in ['steps', 'guidance']:
        if getattr(args, field) is not None:
            fields[field] = getattr(args, field)
    files = {'image': args.image.read_bytes()}
    if args.mask:
        files['mask'] = args.mask.read_bytes()
    request = validate_request(fields, files)
    prepared, mask = prepare_images(request)
    memory = {}
    stop = threading.Event()
    sampler = None
    if platform.system() not in {'Linux', 'Darwin'}:
        import psutil
        process = psutil.Process()
        memory['sampled_peak_rss_bytes'] = process.memory_info().rss
        def sample_memory():
            while not stop.wait(.025):
                memory['sampled_peak_rss_bytes'] = max(memory['sampled_peak_rss_bytes'], process.memory_info().rss)
        sampler = threading.Thread(target=sample_memory, daemon=True)
        sampler.start()
    started = time.perf_counter()
    events = []
    def progress(value, phase):
        events.append({'phase': phase, 'progress': value, 'elapsed_seconds': round(time.perf_counter() - started, 3)})
        print(f'{phase}: {value}%', flush=True)
    try:
        output, metadata = run(request, threading.Event(), progress)
    finally:
        stop.set()
        if sampler is not None:
            sampler.join()
    elapsed = time.perf_counter() - started
    # getrusage measures THIS process in the kernel even in a PID namespace;
    # psutil may read a different PID from a host-mounted /proc in containers.
    if platform.system() in {'Linux', 'Darwin'}:
        import resource
        memory = {'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if platform.system() == 'Linux' else 1)}
        memory_metric = 'Kernel RUSAGE_SELF ru_maxrss, including imports and pipeline weights'
    else:
        memory_metric = 'Process RSS sampled every 25 ms; may miss brief peaks'
    import torch
    import numpy as np
    from PIL import Image
    actual = np.asarray(Image.open(io.BytesIO(output)).convert('RGB')).astype(np.int16)
    original = np.asarray(prepared).astype(np.int16)
    difference = np.abs(actual - original)
    checks = {'output_matches_prepared_dimensions': tuple(actual.shape) == tuple(original.shape),
              'mean_absolute_pixel_change': float(difference.mean()),
              'changed_pixel_count': int(np.any(difference != 0, axis=2).sum())}
    if mask is not None:
        outside = np.asarray(mask) == 0
        inside = np.asarray(mask) > 0
        checks.update(outside_mask_pixel_count=int(outside.sum()),
                      outside_mask_max_channel_difference=int(difference[outside].max()) if outside.any() else None,
                      outside_mask_preserved_exactly=bool(np.all(difference[outside] == 0)),
                      inside_mask_mean_absolute_pixel_change=float(difference[inside].mean()) if inside.any() else None)
        if not checks['outside_mask_preserved_exactly']:
            raise RuntimeError('Outside-mask preservation failed')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    request_record = {key: value for key, value in asdict(request).items() if key not in {'image', 'mask'}}
    report = {'schema': 2, 'real_neural_inference_executed': True,
              'run_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'elapsed_including_pipeline_load_seconds': elapsed,
              **memory, 'memory_metric': memory_metric,
              'platform': platform.platform(), 'python': platform.python_version(),
              'torch': torch.__version__, 'torch_threads': torch.get_num_threads(),
              'cuda_available': torch.cuda.is_available(),
              'packages': {name: importlib.metadata.version(name) for name in ['diffusers', 'transformers', 'accelerate', 'huggingface-hub', 'safetensors', 'numpy', 'Pillow']},
              'source_repo': CATALOG[args.model]['repo'], 'source_revision': state['revision'],
              'weights_bytes': state['bytes'], 'input_sha256': hashlib.sha256(request.image).hexdigest(),
              'mask_sha256': hashlib.sha256(request.mask).hexdigest() if request.mask else None,
              'source_code_sha256': {name: sha256(Path(__file__).parent / name) for name in ['inference.py', 'catalog.py', 'smoke_real.py']},
              'request': request_record, 'events': events, 'checks': checks,
              'output_file': args.output.name, 'output_sha256': hashlib.sha256(output).hexdigest(),
              'scope': 'One real static image edit on the recorded Linux CPU. No video generation, model-quality benchmark, or Mac/Windows performance claim.',
              **metadata}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
