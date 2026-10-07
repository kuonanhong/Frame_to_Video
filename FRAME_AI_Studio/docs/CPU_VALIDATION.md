# CPU 瀏覽器模式驗證

本文件由獨立 QA 根據實際瀏覽器執行結果更新。目前執行環境為 Linux x86_64、Chromium 153，使用 `--disable-gpu`；不代表所有平台與裝置的結果。

## 验证范围

- 透過本機 HTTP 提供完整靜態目錄，使用真實 Chromium 與 JavaScript CPU 模型推論。模型不是 WASM 後端，也不使用 WebGL／WebGPU。
- 無上傳 API、無外部模型 CDN 請求；模型與依賴同源載入。
- 輸入驗證、原圖上傳、物件辨識、手動局部區域、提示詞規則規劃。
- Canvas 動畫與瀏覽器 MediaRecorder 輸出的實際影片載入及元資訊。
- 使用者取消、重複點擊、worker／MediaStream／Object URL 清理。
- 22 種語言切換、阿拉伯語 RTL、390 px 手機寬度版面。

## 未验证范围

- iPhone／Safari、Android 實機，以及其他 Windows／macOS／Linux 瀏覽器仍需實機測試。
- 不以此測試承諾每張照片都能正確辨識、即時渲染、固定幀率或指定的輸出速度。
- 不驗證大型生成式影片模型；本模式是物件辨識加確定性圖形動畫。
- 不聲稱低記憶體 MCU 可以執行此完整網頁。
- 沒有十萬名同時使用者的容量測試。

## 执行记录

直接 detector client 的真實瀏覽器測試已完成：

| 圖片 | 模型載入 | 推論 | 真實結果 |
|---|---:|---:|---|
| 套件 coast 示例，1672×941 | 約2.21秒 | 約1.67秒 | 置信度門檻0.45，沒有檢出物件 |
| 官方 COCO-SSD 開發用 cat.jpg，224×224 | 約2.32秒 | 約1.77秒 | cat，置信度0.92793 |

這些數字是本次測試主機的單次實測，不能作為手機或所有裝置的速度保證。cat.jpg 只用於開發驗證，因沒有單獨照片授權說明而沒有納入交付。

兩次執行模型結果均回報 `backend: cpu`；模型及其五個權重 shard 只透過同源 GET 載入，沒有照片 POST，也沒有外部 CDN。`disposeDetector()` 後 ready 為 false。六個模型檔案的 byte 數與 SHA256 均符合 manifest，合計18,561,843 bytes。

## 完整介面執行結果

最後完整執行：2026-10-07 22:59（Asia/Taipei），已包含最後調輕水波振幅的版本。`edge/tests/browser-smoke.cjs` 的18項實際 Chromium 測試全部通過，沒有使用假的 API 回應或假的模型結果：

| 範圍 | 結果 |
|---|---|
| 22種介面語言 | 全部可切換並設定正確 `lang`；390px寬度逐一檢查沒有橫向溢出。 |
| 真實物件辨識 | COCO-SSD 在CPU執行；coast 示例沒有檢出物件，官方 cat 開發圖片有真實 cat 輸出。 |
| 手動畫框與提示詞 | 新增水面區域；`zoom in, water ripples, snow` 同時規劃相機、水波與雪花效果。 |
| 動畫預覽 | 兩個時間點的Canvas像素雜湊不同，並非只有顯示靜態原圖。 |
| 真實影片輸出 | 產生VP8 WebM檔，854×480、141,453 bytes；Chromium載入並播放，讀得約2.096秒。 |
| 預覽／錄製取消 | 停止renderer、清除pending frame、停止captureStream軌道，取消後沒有舊影格再繪製。 |
| 偵測取消與重複按鈕 | 取消確實終止CPU Worker；同一個tick兩次點擊不產生平行模型工作。 |
| 重設與資源 | 已產生的Blob URL均撤銷，影片來源清除。 |
| 語言獨立網址 | 繁中、阿拉伯文、日文入口可從正確base路徑載入介面與renderer。 |
| 縱式原圖 | CSS顯示比例與本征比例均為0.5，手動畫框使用同一比例座標。 |
| 單檔HTML | 直接從 `file://` 開啟，真實內嵌CPU模型能辨識cat；內嵌renderer輸出854×480影片並實際播放，約2.091秒。 |
| 網路與錯誤 | 資料夾版只有同源GET／本機Blob；單檔版只有file／Blob／dataURL，沒有圖片POST、外部CDN或pageerror。 |

單檔最初使用module Blob Worker時，在Chromium的file來源無法啟動模型。最後版本改成完整內嵌的classic IIFE Worker，修正後整輪重測通過；本表記錄的是修正後版本。

桌面與390px阿拉伯文截圖已目視檢查：文字鍵沒有直接露出、阿拉伯文為RTL、版面沒有切掉操作鈕；另附繁體中文實際水波輸出畫面。**手機截圖是headless Chromium的viewport／touch-capability模擬，不是iPhone／Android實機測試，也沒有驗證所有觸控手勢。**

QA Linux環境原本缺少中文字型，繁中畫面會顯示方框；最後截圖使用僅供測試的私有fontconfig載入Google Fonts官方Noto Sans TC，中文已正常顯示。沒有更改網站程式或加入遠端字型請求；網站使用訪客裝置的系統字型。

程式已加入畫框時的pointerId與忙碌狀態防護；多指同時操作的修正經靜態審查，本次沒有實機多指手勢測試。瀏覽器媒體異常若不觸發MediaRecorder的onstop，可能需要按停止恢復；沒有對故障的媒體編碼器做注入測試。

輸出幀率與錄製時長依裝置計算及瀏覽器編碼決定，不把這次2秒示例視為所有手機都能即時錄製的保證。WebM可能沒有通用播放器預期的封裝duration欄位；Chromium能實際播放本次檔案，其他播放器與Safari格式相容性仍需驗證。

## 重現方式

1. 安裝專案測試依賴與Playwright Chromium，或用 `FRAME_BROWSER_PATH` 指定已安裝的Chromium。
2. 在套件根目錄執行 `node edge/tests/browser-smoke.cjs`。測試腳本自行建立同進程本機HTTP server，不需要公開上網。
3. 若要重現正向cat辨識，可由官方COCO-SSD repository取得開發用 `coco-ssd/demo/cat.jpg`，以 `FRAME_QA_FIXTURE=/完整路徑/cat.jpg` 指定。未提供此開發fixture時，仍執行真正coast推論，但不聲稱該圖一定有檢出物件。
4. 輸出紀錄位於 `qa-output/browser-results.json`；截圖與瀏覽器輸出的示例影片位於同資料夾。
