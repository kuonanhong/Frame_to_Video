#!/usr/bin/env python3
"""Import and execute a small CPU operation, without loading model weights."""
import importlib.metadata
import json
import platform
import sys


def main():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("This setup requires Python 3.11; create a fresh environment with Python 3.11.")
    import numpy
    import torch
    from diffusers import (AutoPipelineForImage2Image, StableDiffusionInstructPix2PixPipeline,
                           StableDiffusionInpaintPipeline)
    from PIL import Image
    pins = {'diffusers': '0.30.3', 'transformers': '4.44.2', 'accelerate': '0.34.2',
            'huggingface-hub': '0.25.2', 'safetensors': '0.4.5', 'numpy': '1.26.4', 'Pillow': '10.4.0'}
    for package, expected in pins.items():
        if importlib.metadata.version(package) != expected:
            raise RuntimeError(f'{package} must be {expected}; rerun setup_native.py --repair.')
    expected_torch = '2.2.2' if platform.system() == 'Darwin' and platform.machine() == 'x86_64' else '2.6.0'
    if torch.__version__.split('+')[0] != expected_torch:
        raise RuntimeError(f'Torch must be {expected_torch} on this platform; rerun setup_native.py --repair.')
    output = torch.tensor([1.0, 2.0], dtype=torch.float32, device='cpu').numpy()
    if output.tolist() != [1.0, 2.0] or numpy.__version__ != '1.26.4':
        raise RuntimeError('CPU/NumPy bridge failed or NumPy pin changed; rerun setup_native.py --repair.')
    report = {'python': platform.python_version(), 'platform': platform.platform(),
              'machine': platform.machine(), 'torch': torch.__version__, 'device': 'cpu',
              'dtype': str(torch.float32), 'numpy_bridge_tested': True,
              'pipelines_imported': 3, 'real_model_inference_executed': False,
              'packages': {name: importlib.metadata.version(name) for name in
                           ['diffusers', 'transformers', 'accelerate', 'huggingface-hub', 'safetensors', 'numpy', 'Pillow']}}
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    main()
