# v5 optional expert validation

Validation date: 2026-10-10. No Intel Mac or Windows execution is claimed.

## Real model test completed

`qwen-text` was installed from the public official repository, built with CPU-only llama-cpp-python 0.3.16, and invoked through the real HTTP service. This test used no mocks and no preset output.

| Measurement | Observed result |
| --- | --- |
| Host | Linux 6.18.44 x86_64, Python 3.12.14, glibc 2.39 |
| Runtime | llama-cpp-python 0.3.16, `n_gpu_layers=0`, 2 CPU threads |
| Model | `Qwen/Qwen2.5-0.5B-Instruct-GGUF`, Q4_K_M |
| Revision | `9217f5db79a29953eb74d5343926648285ec7e67` |
| GGUF size | 491,400,032 bytes |
| GGUF SHA-256 | `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db` |
| Request/result | Real multipart POST → subprocess inference → completed job → result text GET |
| Tokens | 48 prompt + 46 generated = 94 total |
| Elapsed | 2.222 seconds end-to-end; 1.762 seconds inside worker |
| Worker peak RSS | 672,718,848 bytes, approximately 642 MiB |
| Integrity | Installer SHA-256 verification passed for all 3 downloaded files |

The prompt requested two brief sentences about a cinematic lakeside sunrise. The actual generated text and complete machine-readable evidence are in `evidence/qwen-real.txt` and `evidence/qwen-real.json`. These measurements describe one short test in this Linux environment, not performance on the user's computer. No model weights or environments are included in the deliverable.

A second real HTTP inference used the Traditional Chinese prompt `請用繁體中文，為清晨湖邊的照片寫兩句旁白，不要標題。` It completed in 2.004 seconds end-to-end (1.588 seconds in the worker), generated 32 tokens, and peaked at 675,160,064 RSS bytes. The actual output was `清晨湖畔，微風拂面，湖水清澈，湖中倒映着蓝天白云，湖边人影斑斑，令人陶醉。` The small model returned one sentence with mixed Traditional/Simplified characters, so this test demonstrates real Chinese generation but does **not** demonstrate reliable format or Traditional Chinese compliance. Evidence is in `evidence/qwen-zh-real.json` and `evidence/qwen-zh-real.txt`.

Reproduce after installing Qwen:

```bash
FRAME_CPU_THREADS=2 python3 advanced_service/smoke_qwen.py --evidence-dir /path/to/evidence
FRAME_CPU_THREADS=2 python3 advanced_service/smoke_qwen.py --language zh --evidence-dir /path/to/evidence
```

The initial local compilation attempt failed because the execution environment pointed `CC` at an absent `clang`. Repeating with available `CC=gcc CXX=g++` built the package successfully. This is documented as an environment prerequisite, not hidden as a model failure.

## Service contract checks completed

Ten stdlib tests passed. They cover strict request validation, unknown-command rejection, required media and dimensions, malformed multipart input, selected safetensors download filtering, success/failure result manifests, cancellation, one-job concurrency, same-origin guards, inaccessible private runtime paths and the existing native API remaining available. The subprocess lifecycle tests intentionally use test programs with the visible string `TEST HARNESS`; they do not count as model inference.

All Python files compiled successfully. The real Qwen smoke also exercised the immutable installation manifest, actual binary imports, memory preflight, subprocess execution, output manifest handling and HTTP download path.

## Implemented but not real-model-tested in this release session

LivePortrait, ControlNet Canny, MultiDiffusion panorama, FLUX.2 klein 4B, LTX-Video 0.9.5 and CogVideoX 5B I2V have concrete upstream model/CLI adapters and explicit installers. Their APIs and checkpoint layouts were checked against primary upstream sources. Their weights were not installed and inference was not executed here. Their availability must be determined on the target machine; this report makes no generated-image/video quality claim for them.

FLUX/LTX/CogVideoX and the selected LivePortrait dependency profile explicitly block Intel macOS because their pinned modern Torch environment has no supported official Intel Mac wheel. This is not a claim that CPU inference on every other operating system or machine is practical. Large models can exceed RAM/time limits. The server reports missing dependencies, missing weights and conservative memory blocks instead of fabricating outputs.
