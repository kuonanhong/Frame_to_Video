#!/usr/bin/env python3
"""One real expert invocation per process; weights are strictly local/offline."""
import argparse
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import time

from registry import EXPERTS, expert_dir, model_dir

def cpu_threads():
    return max(1,min(32,int(os.environ.get('FRAME_CPU_THREADS',min(4,os.cpu_count() or 2)))))

def check(expert):
    versions, missing = {}, []
    for package in EXPERTS[expert]['packages']:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package)
    if EXPERTS[expert]['requirements'] in {'modern.txt','liveportrait.txt'} and platform.system() == 'Darwin' and platform.machine() in {'x86_64','AMD64'}:
        missing.append('This isolated modern profile has no supported Intel macOS torch wheel')
    if expert == 'liveportrait':
        for binary in ('ffmpeg','ffprobe'):
            if not shutil.which(binary):
                missing.append(binary)
        if not (expert_dir(expert)/'source'/'inference.py').is_file():
            missing.append('LivePortrait source')
    if not missing:
        try:
            if expert == 'qwen-text':
                from llama_cpp import Llama
            else:
                import numpy as np
                import torch
                # Exercise the binary bridge, not just package metadata.
                torch.from_numpy(np.zeros(1,dtype=np.float32)).numpy()
                if expert == 'liveportrait':
                    import onnxruntime
                    import cv2
                    import torchvision
                    import tyro
                    if 'CPUExecutionProvider' not in onnxruntime.get_available_providers():
                        raise RuntimeError('ONNX CPU execution provider missing')
                    source = expert_dir(expert)/'source'
                    sys.path.insert(0,str(source))
                    os.chdir(source)
                    importlib.import_module('src.live_portrait_pipeline')
                else:
                    import diffusers
                    expected = {'controlnet-canny':'StableDiffusionControlNetPipeline',
                        'multidiffusion':'StableDiffusionPanoramaPipeline','flux-klein':'Flux2KleinPipeline',
                        'ltx-video':'LTXImageToVideoPipeline','cogvideox':'CogVideoXImageToVideoPipeline'}
                    getattr(diffusers,expected[expert])
        except Exception as exc:
            missing.append(f'{type(exc).__name__}: runtime binary or pipeline import failed')
    return dict(ready=not missing, versions=versions, missing=missing)

def image_input(path, size=None):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 24_000_000
    with Image.open(path) as source:
        if source.width*source.height > Image.MAX_IMAGE_PIXELS:
            raise ValueError('Input image exceeds 24 million pixels')
        image = ImageOps.exif_transpose(source).convert('RGB')
    if size:
        image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
    return image

def phase(job, text):
    target = job/'progress.json'
    temporary = job/'progress.tmp'
    temporary.write_text(json.dumps(dict(phase=text)), encoding='utf-8')
    temporary.replace(target)

def qwen(request, job):
    from llama_cpp import Llama
    model = model_dir('qwen-text')/'qwen2.5-0.5b-instruct-q4_k_m.gguf'
    phase(job,'Loading Qwen GGUF on CPU')
    engine = Llama(model_path=str(model), n_gpu_layers=0, n_ctx=4096,
        n_threads=cpu_threads(), verbose=False)
    phase(job,'Generating text')
    output = engine.create_chat_completion(messages=[{'role':'user','content':request['prompt']}],
        max_tokens=request['max_tokens'], temperature=0.7, seed=request['seed'])
    text = output['choices'][0]['message']['content'] or ''
    (job/'result.txt').write_text(text,encoding='utf-8')
    return [dict(kind='text',name='result.txt',mime='text/plain; charset=utf-8')], dict(
        result_text=text, usage=output.get('usage',{}), backend='llama-cpp-python', device='cpu')

def diffusion(request, job):
    import torch
    from diffusers.utils import export_to_video
    expert = request['expert']
    torch.set_num_threads(cpu_threads())
    dtype = torch.float32
    options = dict(torch_dtype=dtype, local_files_only=True, use_safetensors=True)
    phase(job,'Loading local model weights on CPU (float32)')
    if expert == 'controlnet-canny':
        import cv2
        import numpy as np
        from PIL import Image
        from diffusers import ControlNetModel, StableDiffusionControlNetPipeline
        control = ControlNetModel.from_pretrained(str(model_dir(expert,'controlnet')), **options)
        pipe = StableDiffusionControlNetPipeline.from_pretrained(str(model_dir(expert,'base')),controlnet=control,**options)
        source = image_input(request['image_path'], (request['width'],request['height']))
        edges = cv2.Canny(np.asarray(source),100,200)
        conditioning = Image.fromarray(np.repeat(edges[:,:,None],3,axis=2))
        conditioning.save(job/'canny.png')
        extra = dict(image=conditioning,controlnet_conditioning_scale=1.0)
    elif expert == 'multidiffusion':
        from diffusers import DDIMScheduler, StableDiffusionPanoramaPipeline
        pipe = StableDiffusionPanoramaPipeline.from_pretrained(str(model_dir(expert,'base')),**options)
        pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config)
        extra = dict(circular_padding=True,view_batch_size=1)
    elif expert == 'flux-klein':
        from diffusers import Flux2KleinPipeline
        pipe = Flux2KleinPipeline.from_pretrained(str(model_dir(expert)),**options)
        extra = dict(image=image_input(request['image_path'])) if request.get('image_path') else {}
    elif expert == 'ltx-video':
        from diffusers import LTXImageToVideoPipeline
        pipe = LTXImageToVideoPipeline.from_pretrained(str(model_dir(expert)),**options)
        extra = dict(image=image_input(request['image_path'],(request['width'],request['height'])),
            num_frames=request['frames'],frame_rate=request['fps'],decode_timestep=0.05,decode_noise_scale=0.025,negative_prompt='')
    elif expert == 'cogvideox':
        from diffusers import CogVideoXImageToVideoPipeline
        pipe = CogVideoXImageToVideoPipeline.from_pretrained(str(model_dir(expert)),**options)
        extra = dict(image=image_input(request['image_path'],(720,480)),num_frames=49)
    else:
        raise ValueError('No diffusion adapter for this expert')
    pipe.to('cpu')
    if hasattr(pipe,'enable_attention_slicing'):
        pipe.enable_attention_slicing()
    if hasattr(pipe,'enable_vae_slicing'):
        pipe.enable_vae_slicing()
    elif hasattr(getattr(pipe,'vae',None),'enable_slicing'):
        pipe.vae.enable_slicing()
    phase(job,'Running real CPU inference; this can take a long time')
    with torch.inference_mode():
        result = pipe(prompt=request['prompt'],width=request['width'],height=request['height'],
            num_inference_steps=request['steps'],guidance_scale=request['guidance'],
            generator=torch.Generator('cpu').manual_seed(request['seed']),**extra)
    if EXPERTS[expert]['kind'] == 'video':
        phase(job,'Encoding generated frames as MP4')
        export_to_video(result.frames[0],str(job/'result.mp4'),fps=request['fps'])
        outputs = [dict(kind='video',name='result.mp4',mime='video/mp4')]
    else:
        result.images[0].save(job/'result.png')
        outputs = [dict(kind='image',name='result.png',mime='image/png')]
        if expert == 'controlnet-canny':
            outputs.append(dict(kind='image',name='canny.png',mime='image/png'))
    return outputs, dict(backend='diffusers',device='cpu',dtype='float32',seed=request['seed'])

def liveportrait(request, job):
    source = expert_dir('liveportrait')/'source'
    image_input(request['image_path']).save(job/'source.png')
    # Do not pass an uploaded name or user-provided argument to upstream's CLI.
    probe = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
        '-of','json',request['driving_path']],check=True,capture_output=True,text=True,timeout=30)
    duration = float(json.loads(probe.stdout)['format']['duration'])
    if not 0 < duration <= 10:
        raise ValueError('LivePortrait driving video must be at most 10 seconds')
    output_dir = job/'liveportrait-output'
    output_dir.mkdir()
    phase(job,'Running upstream LivePortrait source + driving video, experimental CPU')
    subprocess.run([sys.executable,str(source/'inference.py'),'-s',str(job/'source.png'),
        '-d',request['driving_path'],'-o',str(output_dir), '--flag-force-cpu',
        '--no-flag-use-half-precision'],cwd=str(source),check=True)
    movies = sorted(output_dir.glob('*.mp4'))
    preferred = [p for p in movies if 'concat' not in p.stem]
    if not preferred:
        raise RuntimeError('LivePortrait produced no generated MP4')
    shutil.copy2(preferred[0],job/'result.mp4')
    return [dict(kind='video',name='result.mp4',mime='video/mp4')], dict(
        backend='upstream LivePortrait',device='cpu',experimental=True,driving_duration=duration,
        prompt_used=False)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check',choices=list(EXPERTS))
    parser.add_argument('--request',type=Path)
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check(args.check)))
        return
    if not args.request:
        parser.error('--request is required')
    # CPU execution and offline loading are explicit. No tokens or remote-code loading.
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
        CUDA_VISIBLE_DEVICES='',PYTORCH_ENABLE_MPS_FALLBACK='0',TOKENIZERS_PARALLELISM='false')
    request = json.loads(args.request.read_text(encoding='utf-8'))
    expert = request['expert']
    if expert not in EXPERTS:
        raise ValueError('Unknown expert')
    job = args.request.resolve().parent
    started = time.time()
    outputs,metadata = (qwen(request,job) if expert == 'qwen-text' else
        liveportrait(request,job) if expert == 'liveportrait' else diffusion(request,job))
    for output in outputs:
        path = job/output['name']
        if path.parent != job or not path.is_file() or not path.stat().st_size:
            raise RuntimeError('Expert returned a missing or empty output')
    metadata.update(elapsed_seconds=round(time.time()-started,3),model=expert)
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        metadata['process_peak_rss_bytes'] = rss if platform.system() == 'Darwin' else rss*1024
    except ImportError:
        pass
    (job/'result.json').write_text(json.dumps(dict(outputs=outputs,metadata=metadata),ensure_ascii=False),encoding='utf-8')
    phase(job,'Complete')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Last line is useful locally, but request prompts are never intentionally logged.
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
