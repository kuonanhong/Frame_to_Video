# FRAME Story Studio 4.0

修正 Story 3.0 的 file:// 入口，整合照片動態、平面設計圖層、既有全景檢視及選配本機 CPU 圖片生成介面。完整繁中教學：`使用與部署說明.html`。

## 開啟

- 快速編輯：先解壓縮整包，雙擊 `index.html`。基本編輯不再依賴外部 ES module 載入。
- 瀏覽器 AI 全功能：Mac/Linux 執行 `python3 serve.py`；Windows 執行 `py -3 serve.py`，開啟 `http://127.0.0.1:8000/`。
- GitHub Pages：上傳本資料夾的內部內容至 Pages 根目錄，訪客直接開啟 HTTPS 網址，不必安裝 Python。詳見 `GITHUB_PAT_GUIDE.html`。
- 選配本機 CPU 圖片生成：依 `native_cpu/README.html` 安裝 Python 套件及 GB 級權重，再執行 `python native_cpu/server.py --port 8787`。

## 實際功能

- 最多 20 幕照片／影片，排序、複製、刪除、時長、影片裁切、運鏡、轉場、色彩、配樂、字幕與 SRT。
- 新增獨立影像效果提示，局部水波／搖動、雨／雪；有限關鍵字規則有可見結果與不支援動作提示。
- 每幕最多 8 層沙發、燈、植物、鳥魚等原創向量物件／透明 PNG，可調位置、尺寸、顏色、透明度、旋轉、順序。
- 真正已有的 2:1 全景圖可投影檢視與掃視；不推測照片背後的空間。
- 保留內附 COCO-SSD 物件辨識、SmolLM2 135M q8 英文敘事、Piper 中文／英語三種配音及實際權重。
- 上傳錄音、麥克風錄音、WAV、JSON 專案，瀏覽器支援時輸出 MP4/WebM；圖層與動態进入影片。
- 28 語核心介面，瀏覽器語言偏好與手動選擇；Arabic RTL。語系不代表模型支援同樣語言。
- 可選 native_cpu 三個真實 Diffusers 圖片 adapter：SD-Turbo、InstructPix2Pix、SD Inpainting。模型需另外下載，並不在 ZIP／Pages 預設資源內。

## 能力範圍

照片像素動態不會生成「讀書後大笑」等新動作。原生圖片模型輸出新圖片，不是生成式影片；Qwen／LivePortrait／LTX／CogVideoX 等列入研究說明但未整合。不能保證任意提示詞精準、所有手機流暢或完整取代 CapCut/CAD。

所有神經模型與 Worker 在 localhost／HTTPS 使用；file:// 模式明確停用相關按鈕。系統語音只試聽，錄入影片要用神經配音或實際音檔。Google 地圖仅使用者同意定位後開啟，語言偵測不需要定位。

## 開發／重建

使用預先打包的程式不需要 npm install。修改 `story/*.mjs` 後需重建 classic bundle：

```sh
npm install --omit=dev
npm run build:story
```

這會產生 `story/app-v4.bundle.js`、`story/index.html` 和 `offline-files.json`。只改原始 mjs 而未重建，不會反映在 index.html。原版 `build:cpu` 保留用於重建舊 CPU 單檔，現在預設不覆寫 Story 根入口；只有明確加 `--legacy-root` 才覆寫。

原生模型放 `native_cpu/models/`（已 gitignore），不要上傳 Pages。內附 WASM 模型的 40 MiB 分片必須完整保留，不使用 Git LFS。`dist/`／`backend/` 為原版雲端服務參考，主頁不依賴它們。

## 文件／測試

- `VALIDATION_V4.html`：本輪驗證，明確區分 DOM 模擬、實際 Canvas、API 模擬與實際模型推論。
- `MODEL_REALITY_GUIDE.html`：10 種候選模型／管線、CPU 条件、授權、未完成範圍。
- `docs/STORY_V3_GUIDE_ARCHIVE.html` 和其他 V3 驗證文件：歷史資料，不代表 V4 已做相同瀏覽器測試。
- `node --test story/tests/*.test.mjs edge/tests/motion-core.test.mjs`
- `python3 tools/verify-story-package.py`
- `python3 -m unittest discover -s native_cpu/tests -v`

原創程式 MIT；模型／第三方 runtime 遵循各自授權。Huayan 訓練資料 MODEL_CARD 的 Unknown 標記保留，不承諾所有權重可無限制商業再散布。
