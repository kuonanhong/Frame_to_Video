> 歷史資料：此文件記錄 Story 3.0。Story 4 的功能與本輪測試請以根目錄「使用與部署說明.html」及「VALIDATION_V4.html」為準。

# FRAME Story 工作台：實際 UI 驗證

驗證日期：2026-10-09（UTC）。這份紀錄只描述实际執行的測試，不將瀏覽器模擬視窗當作真實手機測試。

## 環境與重現

- Linux、Chromium 153.0.8010.0、Playwright Core。
- 桌面視窗：1280 × 900；手機模擬視窗：390 × 844。
- 在同一 Node 程序啟動本機 HTTP 伺服器與瀏覽器。
- Chromium 啟動時停用 GPU / WebGPU；神經模型使用 CPU WASM。此選項不代表所有終端瀏覽器的畫布或編碼器一定不用硬體加速。
- 測試腳本：`story/tests/workbench-smoke.cjs`。用 `FRAME_QA_PLAYWRIGHT`、`FRAME_QA_CHROMIUM` 指定當地已安裝的 Playwright Core 與 Chromium 路徑。

```bash
FRAME_QA_PLAYWRIGHT=/path/to/playwright-core \
FRAME_QA_CHROMIUM=/path/to/chromium \
node story/tests/workbench-smoke.cjs
```

JSON 紀錄在 `qa/story-ui-validation.json`，樣本匯出與截圖在 `qa/`。

## 已通過的主要流程

| 真實操作 | 證據 |
|---|---|
| 載入 3 幕示範 | 分鏡數為 3；畫布取樣約 93.8% 像素非黑色，照片確實繪製 |
| 22 個介面語言切換 | 每一語系的 `html.lang` 和主要按鈕文字更新；阿拉伯語 `dir=rtl` |
| 匯入本機 PNG | 使用實際檔案輸入，未模擬圖片讀取函式 |
| 分鏡名稱、敘事、字幕、秒數、運鏡、轉場、色彩 | UI 編輯後檢查實際場景資料；名稱欄位映射問題已修正 |
| 排序、複製、刪除 | UI 操作後場景次序與數目符合預期 |
| 中文神經配音 | 按「生成可匯出配音」；華燕模型生成「你好。」約 0.720 秒 WAV，非系統試聽替代 |
| 配樂上傳 | 透過媒體模組建立測試正弦 WAV，再用實際音檔輸入解碼 |
| 專案存檔與開啟 | 真正下載 JSON，再上傳該 JSON；分鏡內容、神經旁白與配樂資料保留 |
| 匯出取消 | 開始真正錄製，再按取消；恢復可編輯狀態與匯出按鈕 |
| SRT 字幕 | 字幕文字包含 UI 輸入的內容 |
| 手機模擬排版 | 頁面水平溢出為 0；預設 360p、12 fps；示範照片仍顯示 |

神經配音初次生成於這次環境約耗時 2.50 秒，這是短句、Linux headless Chromium 的單次紀錄，不能推算真實手機速度。

## 匯出檔案實體檢查

使用 `ffprobe` 讀取真正下载的檔案，並以 FFmpeg 解碼音訊計算 RMS，未只檢查下載副檔名。

| 匯出 | 實際視訊／音訊 codec | 長度 | 大小 | 解碼音訊 RMS |
|---|---|---:|---:|---:|
| `qa/story-ui-export.webm` | VP8 / Opus | 2.000 秒 | 69,437 bytes | 約 0.0812 |
| `qa/story-ui-export.mp4` | VP9 / Opus | 2.026 秒 | 63,119 bytes | 約 0.0815 |

MP4 是實際 MP4 容器，但本環境沒有輸出 H.264/AAC。VP9/Opus 的 MP4 不保證在所有舊手機、Safari 或播放器支援；工作台顯示實際 codec 和相容性提示。不同瀏覽器能產生的格式由其 MediaRecorder 實作決定。

主要流程的外部 HTTP/HTTPS 請求為 0、未捕捉到的頁面錯誤為 0、console error 為 0、遺失資源為 0。地圖、定位與系統線上聲音沒有被啟動。

## 邊界

- 這裡的影片是照片運鏡、轉場、字幕與混音；沒有將靜止人物生成新肢體動作。
- 本次主要流程只讓中文神經聲庫經 UI 完成一次合成；其他模型推論另見模型驗證紀錄。
- 手機部分為窄視窗模擬。仍需要實際 iPhone、Android、低記憶體裝置的手動試用。
- 首次 QA 的極簡 Linux 容器沒有中文系統字型，因此發現畫布字幕缺字。最終產品已內附約 4 MiB 的 jf open huninn 中文字型及官方授權檔，介面與 Canvas 均可使用本機字型；匯出前明確等待字型載入。最終字型 QA 未注入任何測試字型。
- 長片、高解析度、瀏覽器切換至背景、手機鎖屏、麥克風權限及 Google 地圖定位不屬於這次成功測試的範圍。

## 完整離線與原音補充流程：字型加入前已通過

以全新的瀏覽器 context 執行以下指令；詳細紀錄在 `qa/story-offline-validation.json`。

```bash
FRAME_QA_PLAYWRIGHT=/path/to/playwright-core \
FRAME_QA_CHROMIUM=/path/to/chromium \
node story/tests/workbench-smoke.cjs --offline-only
```

1. 從 UI 按「準備離線使用」，完成 **88 個檔案、約 385 MiB** 的本機快取。測試使用的 Service Worker 快取版本為 `frame-story-v3-20261009-d`。
2. Playwright 設定 `context.setOffline(true)`，重新載入根工作台，頁面仍能啟動。示範照片也從快取載入。
3. 在斷網狀態下按 UI 生成中文神經旁白「你好。」；實際聲音約 0.697 秒。
4. 在斷網狀態下匯出 2 秒 WebM。`ffprobe` 確認有真正視訊與音訊，檔案 81,872 bytes；解碼音訊 RMS 約 0.0841。工作台中的播放器亦成功播放，`readyState=4`、沒有播放錯誤。
5. 斷網切換至 `/story/` 入口，仍能啟動。
6. 匯入上述有音訊影片，**關閉「保留影片原音」**後，匯出檔只有視訊、沒有音軌；打開該選項後，匯出檔保留可解碼、非靜音的音軌。
7. 專案存檔後刻意改變格式、旁白自動延長、原音保留選項，再重新開啟存檔；三個選項均成功還原。
8. 專案內 `audioData` 改為外部 HTTPS 網址時，立即拒絕輸入，未發出外部請求，沒有破壞既有分鏡。
9. 斷網、390px 手機模擬入口仍顯示示範，沒有水平溢出，預設為 360p / 12fps。

這個補充流程的外部請求、遺失資源、未捕捉頁面錯誤、console error 均為 0。快取只證明這次瀏覽器在空間足夠的情況可離線運行；瀏覽器仍可能因裝置空間不足、私人模式或使用者清除資料而刪除快取。

## 最終中文字型補充驗證

紀錄為 `qa/story-font-validation.json`，測試使用新的瀏覽器 context，沒有 `FRAME_QA_CJK_FONT` 注入。

- 產品內附字型 `story/assets/fonts/jf-openhuninn.woff` 為 4,062,464 bytes，使用官方 OFL 授權。
- 確認 `document.fonts.check()` 已載入 `FRAME CJK`。以畫布繪製「聰、動、海、風」，四個字的位元圖 hash 均不同，證明實際中文字形不是共同方框。
- 完整離線模型測試是前述版本 d 的既有結果；此次最後流程只針對新版 shell、字型与中文渲染。最初發現新 context 的 shell 缺少靜態 `edge/detector-client.mjs`，已加入 precache 並驗證離線 root 與 `/story/` 均能啟動。
- 中文介面的 fallback 顯示亦經 CDP 平台字型檢查；極簡 Linux 的部分 DejaVu Sans glyph 不能正確回退，已將中文介面本機字型置前。 最後版本 `frame-story-v3-20261009-f` 實測「免費匯出影片」「生成可匯出配音」、標語、狀態與標題全部使用實際 `jf-openhuninn-1.1` custom font；不再使用缺字的 DejaVu Sans。
- `qa/story-desktop.png`、`qa/story-mobile.png` 為最終產品字型的實際截圖；未使用注入字型掩蓋缺字。手機視窗仍為模擬。

## 實際三幕中文樣片

`qa/FRAME_Story_demo.webm` 為真實瀏覽器錄製，使用原有示範海岸照片、三個中文神經旁白、運鏡、轉場、燒錄中文字幕及內建配樂。不是預先剪輯的外部示範影片。

| 分鏡 | 旁白 | 實際生成聲音長度 | 分鏡長度 |
|---|---|---:|---:|
| 海風出發 | 清晨，海風陪我們出發。 | 2.090 秒 | 3.5 秒 |
| 珍藏美景 | 慢下腳步，看看眼前的美景。 | 2.461 秒 | 3.5 秒 |
| 回憶前行 | 帶著回憶，我們繼續前行。 | 2.218 秒 | 3.5 秒 |

樣片總長 **10.5 秒**、960 × 540、VP8 / Opus、檔案 **2,572,678 bytes**；解碼混音 RMS 約 **0.0984**。`qa/story-demo-frame.png` 是从實際樣片擷取的畫面，已人工確認中文字幕字形正常。可編輯專案為 `qa/FRAME_Story_demo_project.json`。
