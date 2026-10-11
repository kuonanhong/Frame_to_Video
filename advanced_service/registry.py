"""Allowlisted optional experts. Importing this module never imports ML libraries."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('FRAME_EXPERT_HOME', BASE / '.runtime')).expanduser().resolve()

EXPERTS = {
    'qwen-text': dict(label='Qwen2.5 0.5B · GGUF CPU', kind='text', requires_image=False,
        requires_driving=False, requirements='qwen.txt', packages=['llama-cpp-python'],
        cpu_note='Small CPU language model. Output is generated text; it does not render video.',
        repos=[dict(name='model', repo='Qwen/Qwen2.5-0.5B-Instruct-GGUF',
                    files=['qwen2.5-0.5b-instruct-q4_k_m.gguf'])],
        defaults=dict(max_tokens=256, seed=42)),
    'liveportrait': dict(label='LivePortrait · source + driving video', kind='video', requires_image=True,
        requires_driving=True, requirements='liveportrait.txt',
        packages=['torch','torchvision','onnxruntime','tyro','opencv-python-headless'],
        cpu_note='Experimental CPU path from upstream. Requires an actual driving video; Intel macOS compatibility is unverified.',
        repos=[dict(name='pretrained_weights',repo='KlingTeam/LivePortrait', files=['*'])],
        source='https://github.com/KlingAIResearch/LivePortrait.git',
        defaults=dict(seed=42, fps=25)),
    'controlnet-canny': dict(label='ControlNet Canny · SD1.5', kind='image', requires_image=True,
        requires_driving=False, requirements='diffusion.txt',
        packages=['torch','diffusers','transformers','accelerate','opencv-python-headless'],
        cpu_note='Real Canny conditioning on a local SD1.5 pipeline. CPU inference can take minutes.',
        repos=[dict(name='base',repo='stable-diffusion-v1-5/stable-diffusion-v1-5',files=['*']),
               dict(name='controlnet',repo='lllyasviel/control_v11p_sd15_canny',files=['*'])],
        defaults=dict(steps=20, width=512, height=512, seed=42, guidance=7.5)),
    'multidiffusion': dict(label='MultiDiffusion · panorama', kind='image', requires_image=False,
        requires_driving=False, requirements='diffusion.txt',
        packages=['torch','diffusers','transformers','accelerate'],
        cpu_note='StableDiffusionPanoramaPipeline with shared SD1.5-compatible weights; wider canvases are much slower on CPU.',
        repos=[dict(name='base',repo='stable-diffusion-v1-5/stable-diffusion-v1-5',files=['*'])],
        defaults=dict(steps=20, width=1024, height=512, seed=42, guidance=7.5)),
    'flux-klein': dict(label='FLUX.2 klein · 4B image edit', kind='image', requires_image=True,
        requires_driving=False, requirements='modern.txt', packages=['torch','diffusers','transformers','accelerate'],
        cpu_note='Large float32 CPU experiment. Requires substantial RAM; upstream GPU speed and VRAM claims do not apply.',
        repos=[dict(name='model',repo='black-forest-labs/FLUX.2-klein-4B',files=['*'])],
        defaults=dict(steps=4, width=512, height=512, seed=42, guidance=1.0)),
    'ltx-video': dict(label='LTX-Video 0.9.5 · image to video', kind='video', requires_image=True,
        requires_driving=False, requirements='modern.txt', packages=['torch','diffusers','transformers','accelerate','imageio-ffmpeg'],
        cpu_note='Large float32 CPU experiment. Small 9-frame preview by default; not tested on Intel Mac.',
        repos=[dict(name='model',repo='Lightricks/LTX-Video-0.9.5',files=['*'])],
        defaults=dict(steps=20, width=512, height=320, frames=9, fps=8, seed=42, guidance=3.0)),
    'cogvideox': dict(label='CogVideoX 5B I2V', kind='video', requires_image=True,
        requires_driving=False, requirements='modern.txt', packages=['torch','diffusers','transformers','accelerate','imageio-ffmpeg'],
        cpu_note='Very large float32 CPU experiment, 720×480. May require many hours and tens of GB of RAM. Custom model license.',
        repos=[dict(name='model',repo='zai-org/CogVideoX-5b-I2V',files=['*'])],
        defaults=dict(steps=50, width=720, height=480, frames=49, fps=8, seed=42, guidance=6.0)),
}

def expert_dir(expert):
    if expert not in EXPERTS:
        raise ValueError('Unknown expert')
    return RUNTIME / expert

def python_path(expert):
    return expert_dir(expert) / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')

def model_dir(expert, name='model'):
    return expert_dir(expert) / 'models' / name
