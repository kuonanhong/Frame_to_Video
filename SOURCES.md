# 來源與查核｜2026-10-07

- 功能參考：https://deevid.ai/ ，免費試用額度：https://deevid.ai/pricing
- ZeroGPU免費運算、每日額度與排隊：https://huggingface.co/docs/hub/spaces-zerogpu
- 官方LTX公開模型：https://huggingface.co/spaces/Lightricks/ltx-video-distilled
- 官方FLUX公開模型：https://huggingface.co/spaces/black-forest-labs/FLUX.1-schnell
- 社群Wan公開模型：https://huggingface.co/spaces/zerogpu-aoti/wan2-2-fp8da-aoti-faster
- API端點及參數已透過各Space的 `/gradio_api/info` 與GradioJS1.19.0文件查核。
- LTX Space程式：https://huggingface.co/spaces/Lightricks/ltx-video-distilled/blob/main/app.py
- Diffusers0.35.1 LTX：https://huggingface.co/docs/diffusers/v0.35.1/api/pipelines/ltx_video
- Diffusers0.35.1 Wan：https://huggingface.co/docs/diffusers/v0.35.1/api/pipelines/wan
- LTX2B0.9.5：https://huggingface.co/Lightricks/LTX-Video-0.9.5
- Wan5B：https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers
- SD-Turbo：https://huggingface.co/stabilityai/sd-turbo
- GradioJS：https://github.com/gradio-app/gradio/tree/main/client/js
- 自架模型完整revision已固定於後端，維持可重現下載。公開Space為服務，版本及可用性由其提供者維護，不能固定。

本專案不宣称免费无限云端生成。AI生成输出品质依模型、提示词、输入素材及随机种子而异，不保证满足商业成片标准。
# CPU 照片動畫新增來源（2026-10-07）

- TensorFlow 官方 COCO-SSD 文件（80類、lite_mobilenet_v2、自訂modelUrl）：https://github.com/tensorflow/tfjs-models/blob/master/coco-ssd/README.md
- TensorFlow.js CPU後端：https://www.tensorflow.org/js/guide/platform_environment
- 官方 SSDLite 模型頁及 Apache-2.0 授權：https://www.kaggle.com/models/tensorflow/ssdlite-mobilenet-v2/tfJs/default/1?tfhub-redirect=true
- OpenCV幾何轉換：https://docs.opencv.org/4.x/dd/d52/tutorial_js_geometric_transformations.html
- OpenCV光流（需要連續影格）：https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html
- MediaRecorder容器支援：https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder
- GitHub Pages限制：https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits

CPU模式實際採用原生JavaScript像素算法，沒有載入OpenCV.js、深度模型或生成式影片模型。官方模型JSON／權重檔的來源、實際大小與SHA-256見 `edge/model/coco-ssd-lite/manifest.json`；授權見 `docs/MODEL_NOTICES.md`。

本次使用者提供的三個ChatGPT網址，以及Google搜尋結果網址，無法透過讀取服務取得完整內容。實作依據本次上傳檔案、使用者貼出的需求與官方技術文件，不宣稱已讀到這些連結的完整對話或搜尋結果。
