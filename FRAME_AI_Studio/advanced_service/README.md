# FRAME v5 optional CPU experts

These are real local model adapters, not browser simulations. Static Pages cannot execute them. Run this server and open its printed `http://127.0.0.1:8787/` address to use the optional experts and the existing native image API on one origin. No model weights are bundled.

## Start

From the project root:

```bash
python3 advanced_service/server.py
```

Or open `Launch_Mac.command`, run `Launch_Linux.sh`, or open `Launch_Windows.bat` inside this directory. The launchers prefer the project's `.venv-native` Python when it exists, so the existing native CPU image experts remain available. Otherwise the basic server works with Python 3.10–3.12; native image experts report their missing dependencies until native setup is completed. Do not run both local servers on port 8787 simultaneously.

## Install only the expert you choose

Use Python 3.11 where possible. Installation intentionally requires a terminal command with `--download`; the web API cannot run installers, download models or execute arbitrary commands.

```bash
python3 advanced_service/install.py qwen-text --download
python3 advanced_service/install.py controlnet-canny --download
python3 advanced_service/install.py multidiffusion --download
python3 advanced_service/install.py liveportrait --download
python3 advanced_service/install.py flux-klein --download
python3 advanced_service/install.py ltx-video --download
python3 advanced_service/install.py cogvideox --download
```

Each expert gets its own environment and model folder under `advanced_service/.runtime/`. To put these large files elsewhere, set `FRAME_EXPERT_HOME` to the same absolute directory before both installation and server launch. On Linux/Windows, installers select CPU PyTorch wheels. Modern experts do not modify the native Intel Mac environment. No account credentials are required or supplied by this service; public download access and the relevant model licenses must be available.

Qwen's pinned llama-cpp-python may compile locally. Install a C/C++ compiler and CMake build tools first (on macOS, Xcode Command Line Tools; on Windows, Visual Studio C++ Build Tools). A stale `CC`/`CXX` environment setting can block compilation. The build explicitly disables CUDA and Metal. LivePortrait also requires `git`, `ffmpeg` and `ffprobe` on PATH.

## What actually runs

| Expert ID | Real implementation and input | CPU preflight estimate | Native Intel Mac status |
| --- | --- | --- | --- |
| `qwen-text` | Official Qwen2.5 0.5B Q4_K_M GGUF, llama-cpp-python `Llama`, text prompt → text | 2 GiB available | Buildable CPU path; no Mac execution claim |
| `controlnet-canny` | SD1.5 + official ControlNet v1.1 Canny; image → Canny map → generated PNG | 12 GiB | Dedicated legacy PyTorch 2.2.2 profile; not executed on Mac |
| `multidiffusion` | `StableDiffusionPanoramaPipeline`, DDIM, circular padding, SD1.5-compatible weights; prompt → panorama PNG | 12 GiB | Same legacy profile; not executed on Mac |
| `liveportrait` | Upstream CLI, source portrait + actual driving video ≤10 seconds → generated MP4 | 4 GiB | This pinned modern profile is blocked on Intel macOS; upstream CPU path remains experimental |
| `flux-klein` | `Flux2KleinPipeline` with uploaded image and prompt → edited PNG | 48 GiB | Blocked: modern Torch requirements exceed official Intel macOS wheels |
| `ltx-video` | `LTXImageToVideoPipeline`, LTX-Video 0.9.5; image + prompt → generated MP4 | 32 GiB | This modern profile is blocked on Intel macOS |
| `cogvideox` | `CogVideoXImageToVideoPipeline`, 5B I2V; image + English prompt → generated 720×480, 49-frame MP4 | 48 GiB | This modern profile is blocked on Intel macOS |

These memory numbers are conservative engineering thresholds, not measured minimums or speed guarantees. Actual peak usage depends on resolution, model components and runtime version. The service considers Linux container memory limits. Low estimated available RAM blocks a run; an experienced operator can explicitly set `FRAME_EXPERT_ALLOW_LOW_MEMORY=1` to bypass this estimate, accepting possible process failure or exhaustion. Unknown available memory is reported as unknown. Close other workloads before large CPU jobs. GPU VRAM and speed claims do not describe CPU performance.

The modern profile is pinned to Torch 2.6.0, Diffusers 0.37.1 and Transformers 4.57.6. FLUX.2's Qwen3 text encoder and `torch.nn.RMSNorm` requirements are why this profile is separate. This does not turn a small Intel Mac into a practical video-generation workstation. Large-model CPU jobs may take hours; some require substantially more RAM than the estimates.

All inference uses local files, offline Hugging Face mode, `n_gpu_layers=0` for Qwen, and `torch.float32` on `cpu` for Diffusers. No GPU offload method is called. Diffusers requires safetensors. LivePortrait uses its upstream `.pth` and ONNX files, whose provenance and hashes are recorded. Its prompt field does not drive the animation; the driving video does.

## Reproducibility and licenses

An installation resolves each official model repository (the SD1.5 repository is a community mirror) to an immutable 40-character commit before downloading. The installation manifest records that revision, selected files, byte sizes and SHA-256 hashes. Downloaded LFS SHA-256 hashes are compared with upstream metadata. Pipeline downloads exclude `.bin`, `.ckpt`, alternative precision variants and duplicate root single-file checkpoints. Upstream licenses/model cards are retained. The resolved Python package list is saved with the installation.

```bash
python3 advanced_service/install.py qwen-text --verify
# To reproduce a known installed snapshot, use its recorded revision:
python3 advanced_service/install.py qwen-text --download --revision model=FULL_40_CHARACTER_COMMIT_SHA
```

`--verify` rehashes every installed file without downloading. The status API checks recorded files and sizes, then imports the actual runtime and model classes in a subprocess. It does not load multi-GB weights merely to display readiness. Same-size disk corruption can therefore require `--verify` to detect. A missing, incompatible, incomplete or memory-blocked expert reports a concrete blocked state; no sample output is substituted.

Read each upstream license before downloading/using it. CogVideoX 5B I2V has a custom model license. LivePortrait's InsightFace pretrained weights carry additional usage restrictions separate from the source-code license. FLUX.2 klein 4B and Qwen have their own model cards/licenses. This project does not grant model licenses.

Primary references:

- Qwen: https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF
- llama-cpp-python pinned API: https://pypi.org/project/llama-cpp-python/0.3.16/
- LivePortrait source/CPU configuration: https://github.com/KlingAIResearch/LivePortrait
- LivePortrait weights: https://huggingface.co/KlingTeam/LivePortrait
- ControlNet Canny: https://huggingface.co/lllyasviel/control_v11p_sd15_canny
- SD1.5 mirror: https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5
- Panorama pipeline: https://huggingface.co/docs/diffusers/api/pipelines/panorama
- FLUX.2 klein 4B: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- LTX 0.9.5: https://huggingface.co/Lightricks/LTX-Video-0.9.5
- CogVideoX 5B I2V: https://huggingface.co/zai-org/CogVideoX-5b-I2V

## API contract

- `GET /api/experts/status`: seven experts with `id`, `kind`, `defaults`, `requires_image`, `requires_driving`, `installed`, `dependencies_ready`, `hardware_ready`, `available`, `blocked_reason`, and memory estimates. Native `/api/status` and `/api/jobs` remain available.
- `POST /api/experts/jobs`: multipart fields `expert`, `prompt`, optional `image`/`driving`, `steps`, `seed`, `width`, `height`, `frames`, `fps`, `guidance`, `max_tokens`. Only allowlisted IDs and numeric limits are accepted. Image ≤12 MiB, driving file ≤64 MiB, total request ≤80 MiB. Uploaded names are ignored.
- `GET /api/experts/jobs/{id}`: `queued`, `running`, `completed`, `failed`, or `cancelled`, phase text, final metadata and `outputs: [{kind, name, mime, url}]`. Qwen also returns `result_text`.
- `POST /api/experts/jobs/{id}/cancel`: stops that subprocess and child process tree. Cancellation escalates if needed.
- `GET /api/experts/jobs/{id}/{output-name}`: serves only completed, manifest-declared result files. Private inputs, logs, environments and weights cannot be downloaded through the server.

Only loopback and same-origin requests are accepted. Native and advanced jobs share an admission lock, so only one can use the CPU at a time. Up to eight jobs remain in the in-memory history. Uploaded files and generated outputs are removed at clean shutdown unless `--keep-outputs` is explicitly used. A crash can leave files in `.runtime/jobs`; with the server stopped, run `python3 advanced_service/cleanup.py --delete` to remove these job inputs, outputs and logs. It never removes installed models/environments. Download outputs you want to keep before closing the server.

## Validation

```bash
python3 -m unittest discover -s advanced_service/tests -v
```

The service tests use clearly labeled fake subprocesses for request validation, manifest handling, failed jobs, cancellation, one-job admission, installation filtering and same-origin guards. They are not model-inference tests. Real-model results, if produced during release validation, are documented separately in `VALIDATION.md`. No Intel Mac execution is claimed by these tests.

## 中文快速说明

这七项是调用真实模型的本地可选适配器，静态网页不能计算。先为所选模型执行 `install.py 模型ID --download`，再启动此目录中的系统启动器，打开终端给出的本机地址。安装前阅读上游模型许可；高级权重不随 ZIP 打包。Qwen 输出文本，LivePortrait 必须有真人像与驱动视频，ControlNet 输出受边缘控制的图像，MultiDiffusion 输出全景，FLUX 输出图像编辑，LTX/CogVideoX 输出模型生成视频。未安装、依赖错误或内存不足时明确显示不可运行，绝不以假视频代替。现代大模型环境与原来的 Intel Mac CPU 环境隔离；本版本不宣称这些大型模型已在 Intel Mac 上验证。
