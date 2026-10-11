"""Fixed model allowlist. No model IDs or filesystem paths accepted from HTTP clients."""
from pathlib import Path
import hashlib
import json
import os

ROOT = Path(__file__).resolve().parent
MODEL_ROOT = Path(os.environ.get('FRAME_NATIVE_MODEL_DIR', ROOT / 'models')).expanduser().resolve()
CATALOG = {
    'sd-turbo': {
        'name': 'SD-Turbo · image-to-image',
        'repo': 'stabilityai/sd-turbo',
        'task': 'image-to-image', 'default_steps': 4, 'max_steps': 4,
        'license': 'Stability AI model license; see upstream LICENSE.md',
        'source': 'https://huggingface.co/stabilityai/sd-turbo',
    },
    'instruct-pix2pix': {
        'name': 'InstructPix2Pix · instruction editing',
        'repo': 'timbrooks/instruct-pix2pix',
        'task': 'instruction-image-edit', 'default_steps': 15, 'max_steps': 30,
        'license': 'Model card: MIT; also review inherited Stable Diffusion terms',
        'source': 'https://huggingface.co/timbrooks/instruct-pix2pix',
    },
    'sd-inpaint': {
        'name': 'Stable Diffusion · masked inpainting',
        'repo': 'stable-diffusion-v1-5/stable-diffusion-inpainting',
        'task': 'masked-inpainting', 'default_steps': 20, 'max_steps': 30,
        'license': 'CreativeML Open RAIL-M; community mirror of deprecated Runway repository',
        'source': 'https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-inpainting',
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def model_status(expert, root=MODEL_ROOT, verify_hashes=False):
    spec = CATALOG[expert]
    state = dict(id=expert, **spec, installed=False, verification='not-installed',
                 weights_bundled=False, inference_tested=False)
    path = root / expert
    try:
        install = json.loads((path / 'FRAME_INSTALL.json').read_text('utf-8'))
        if install['repo'] != spec['repo'] or install['variant'] != 'fp16':
            raise ValueError('install metadata mismatch')
        if len(install.get('files', [])) < 8:
            raise ValueError('incomplete file manifest')
        for item in install['files']:
            relative = Path(item['path'])
            target = (path / relative).resolve()
            if relative.is_absolute() or not target.is_relative_to(path.resolve()):
                raise ValueError('invalid manifest path')
            if not target.is_file() or target.stat().st_size != item['bytes']:
                raise ValueError('missing or changed file')
            if verify_hashes and sha256(target) != item['sha256']:
                raise ValueError('SHA-256 mismatch')
        for required in ('model_index.json', 'unet/diffusion_pytorch_model.fp16.safetensors',
                         'vae/diffusion_pytorch_model.fp16.safetensors', 'text_encoder/model.fp16.safetensors'):
            if not (path / required).is_file():
                raise ValueError('missing core component')
        state.update(installed=True, verification='sha256' if verify_hashes else 'file-sizes',
                     revision=install['revision'], bytes=sum(x['bytes'] for x in install['files']))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return state
