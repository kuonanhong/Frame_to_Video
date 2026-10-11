# FRAME：本次實際附帶的 CPU 神經模型

核對及下載日期：2026-10-09。這一版的神經模型負責「英語敘事草稿」與「中文／英文語音波形」；照片影片由工作台的分鏡、影像變換、轉場、字幕與音軌合成。沒有把縮放運鏡稱為擴散式生成影片。

## 已附的模型及真實範圍

| 功能 | 固定來源及版本 | 核心權重大小 | 語言與限制 |
|---|---|---:|---|
| 敘事 | `onnx-community/SmolLM2-135M-Instruct-ONNX-MHA`；revision `5b6682c7c9df18f004bfb7e635cba3f3d98537d8`；q8 | 137,479,710 bytes | 英語。這是 135M 小模型；輸出是可修改的創作草稿，可能增添虛構場景，不能保證每次忠於照片。不是世界上「最準」的模型。 |
| 華燕中文 | `rhasspy/piper-voices`；revision `c10ece1aade47bb51c153c893d14e5bf8e5b7117`；`zh_CN-huayan-medium` | 63,201,294 bytes | 中文普通話；22,050 Hz。繁體中文以 OpenCC 做模型前處理；原字幕文字不因語音前處理而修改。 |
| Amy 美式英語 | 同上；`en_US-amy-low` | 63,104,526 bytes | 英語女性聲線；16,000 Hz。 |
| Alan 英式英語 | 同上；`en_GB-alan-low` | 63,104,526 bytes | 英語男性聲線；16,000 Hz。 |

模型、詞表、設定及音素前處理資源合計 **347,687,495 bytes**；不含瀏覽器執行時、GPL 元件源碼與網站其他檔案。確切每個檔案和分片的 bytes、SHA-256 與下載 URL 都在 `story/models/manifest.json`。19 個邏輯下載項目都已實際取得，不是空資料夾或只附下載連結。

22 個介面語系與這裡的模型語言是不同層次。介面可以顯示使用者語言，這份包的神經語音只提供中文、英文三個聲庫，英語小敘事模型只產生英語草稿。其他語言仍可自行輸入字幕與上傳旁白錄音。沒有假稱具備所有語系的離線生成模型。

## 執行方式

`story/ai/client.mjs` 對主畫面提供：

```js
import {
  generateNarration, synthesizeSpeech, voiceCatalog,
  supportedLanguages, releaseModels,
} from './story/ai/client.mjs';

const draft = await generateNarration({
  prompt: 'A cat sits beside a sunlit window.',
  objects: ['cat'], language: 'en', maxTokens: 96,
  onProgress: p => console.log(p.stage, p.loaded, p.total),
});

const { audio, sampleRate } = await synthesizeSpeech({
  text: '聰動成長協會，歡迎一起動手動腦。',
  voice: 'zh_CN-huayan-medium', language: 'zh-Hant', rate: 1,
});
// audio 是可混音、存成 WAV 或寫入影片音軌的 Float32Array。
```

兩個接口都接受 `AbortSignal`。取消會終止 worker，確實中斷 WASM 推論。為避免在手机同時堆疊兩個模型，切換敘事／語音會釋放上一個 ONNX session。同一 worker 一次只接受一項模型任務；多位網站使用者各在自己的裝置執行，不共享伺服器上的模型工作佇列。

Transformers.js **3.8.1** 與 ONNX Runtime Web **1.22.0** 都已附本地瀏覽器程式及 WASM。敘事 `device: 'wasm'`、語音 `executionProviders: ['wasm']`，`numThreads: 1`。沒有 WebGPU，也不要求 GitHub Pages 設定 COOP／COEP。单线程讓沒有 cross-origin isolation 的 Pages 也能工作，但相較可用多线程的本機程式可能較慢。

大於 40 MiB 的權重由下載程式分成 `*.part000` 等檔案。自訂 loader 依 manifest 重組 ArrayBuffer 並校驗各片 SHA-256，再交給 ONNX Runtime。**這是本專案的 loader 功能；不是任意 ONNX 檔案拆片後都可直接使用。** 不要刪掉 `*.parts.json`／`manifest.json` 或更改分片名稱。最大模型單片不超過 40 MiB，適合普通 Git 上傳；不需要依賴 Git LFS 來讓 Pages 讀取模型。

下載包中的 `story/ai/smoke.html` 是獨立實測頁。以 HTTP 本機伺服器開啟即可依次測試中文、英文及敘事。不支援直接雙擊 `file://` 載入 module worker 和模型。

GitHub Pages 首次開啟仍要下載靜態程式及所選模型；若只用中文旁白，無須先載入英文聲庫或敘事模型。完整離線操作的前提是所需 UI、runtime、模型各片先下載／快取完成；本機 HTTP 伺服器則直接讀已解壓檔案，不需要對外網路。瀏覽器快取可被使用者或系統清除，不能承諾永久離線保存。

## 實測結果及界線

`story/ai/model-smoke-report.json` 記錄在此工作環境的 headless Chromium 測試，並不是對您 Mac、iPhone 或所有手機的速度承諾：

- 中文測試生成 67,072 samples，22,050 Hz，約 3.04 秒音軌；含載入約 2.43 秒。
- 英語 Amy 測試生成 33,536 samples，16,000 Hz，約 2.10 秒音軌；含切換載入約 1.51 秒。
- Alan 英語測試生成 32,000 samples，16,000 Hz，約 2.00 秒音軌；含切換載入約 1.47 秒。
- 36 個 token 的英語敘事測試含載入约 4.66 秒。
- 所有模型請求均為本機檔案，沒有遠端請求；沒有 uncaught page error 或 console error。

不同 CPU、記憶體、瀏覽器會有不同結果。下載大小不是實際執行的 RAM 用量：WASM 堆、活化張量、模型、影片與圖片另需記憶體。低記憶體手機可能無法載入模型，應使用手寫敘事、上傳錄音及基本影片編輯模式；不能單憑 `navigator.deviceMemory` 推論裝置一定能執行。

本模型聲庫代表三個固定說話聲線。聲音速度可調 **0.6～1.6**，不代表模型能準確改變說話者年齡、身分或人格。上傳自己的錄音是使用原錄音作旁白，不會讓 Piper 自動學會該聲線。

## 授權與對應源碼

不要把整个附件包稱為「所有東西都 MIT」。

- SmolLM2 原作者 [HuggingFaceTB](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct) 宣告 Apache-2.0；ONNX 轉換來源、固定 revision 已保留。`story/models/smollm2/LICENSE` 附 Apache-2.0 文本。
- [Piper 官方聲库](https://huggingface.co/rhasspy/piper-voices) 標示 MIT。但每個聲庫的 dataset 資訊仍須個別核對。**huayan 的原始 `MODEL_CARD` 明列訓練資料授權 `Unknown`；Amy、Alan 指向 Mimic3 來源。** 本包保留原始模型卡，不據此保證 huayan 的商用或再授權，也不把 Unknown 自動解讀成禁止使用。公開發布此模型前，應核對相應權利。
- Transformers.js 是 Apache-2.0；ONNX Runtime Web、OpenCC 與 Piper Web 外層套件宣告 MIT。保留 `story/vendor/` 中的原始 license 與 package metadata。
- Piper 音素處理包含 **eSpeak NG GPL-3.0** 元件，不能以外層 npm 套件 MIT 標示覆蓋它。`story/vendor/piper-wasm/piper-wasm-GPL.txt` 是完整 GPL 文本；对应源碼、建置說明與來源 manifest 均附于該資料夾。

`story/vendor/piper-wasm/` 內附：

1. `piper-phonemize-source.tar.gz`：wide-video 的完整源碼 archive（commit 固定於 `sources-manifest.json`）。
2. `espeak-ng-source.tar.gz`：上游 Piper CMake 所固定的 eSpeak NG commit `0f65aa301e0d6bae5e172cc74197d32a6182200f` 完整源碼。
3. `piper-wasm-build-source.tar.gz`：diffusion-studio 音素 WASM 的建置專案源碼，原始 README 保留 Emscripten 3.1.47 等建置步驟。
4. `sources-manifest.json`：下載源碼 URL、實際 bytes／SHA-256。
5. `README.md`：npm 1.0.0 原始建置说明。

本包保留公開上游源碼與建置指令；**本次未重新編譯音素 WASM，也沒有宣稱已证明與上游 npm 二進位逐 byte 可重現**。若另行修改或分發此 GPL 元件，要保留其授权和源碼。

## 為何沒有把候選模型全部塞進網站

- [Kokoro 原作者的 JavaScript 版本](https://github.com/hexgrad/kokoro/tree/main/kokoro.js) 当前 `_validate_voice` 限定英美英語 `a/b`，中文 Python 載入方式則需要 Misaki 中文 G2P。不能只因 ONNX 仓庫有 `zf_xiaobei` 檔名，就聲稱这份浏览器 runtime 已具备正确中文音素前處理。
- [Supertonic 3 官方存檔](https://github.com/supertone-oss-archive/supertonic/blob/main/web/README.md) 提供 31 語與十種聲線，能走 CPU WASM，但这 31 語沒有中文；其四份 ONNX 約 398 MB，本包沒有附此模型，也没有称其已安装。
- [Qwen2.5 0.5B ONNX](https://huggingface.co/onnx-community/Qwen2.5-0.5B-Instruct/tree/main/onnx) 的 q8 權重仍约 512 MB。它可作为日后桌機多語敘事升級候選，但本次未附、未在此工作台實測，不當作現成能力。
- [NeuTTS 官方](https://github.com/neuphonic/neutts) 有可在 CPU 执行的 GGUF 声音克隆流程，需要参考錄音、其逐字稿、声码器及 Python／llama.cpp 執行環境。其 Air 与 Nano 等不同模型授权不同。這不是本包內的手機浏览器功能；也不將上传錄音操作稱為克隆。若要此功能，應另建本机 helper 并实测，而不能靠 GitHub Pages 后台執行 Python。

## 重下載或恢復模型

```bash
python3 tools/fetch-story-models.py
```

此指令只用 Python 标准库，不需付费 API key；使用固定版本公開下載 URL。已经完成的分片會复用，結果写回 `story/models/manifest.json`。供開發者扩展的其他小聲庫目标也列在该脚本中；下载其他聲库后，还须相应扩充 `voiceCatalog()`、语言匹配及 UI，不能把「仅下載」称为已接入。
