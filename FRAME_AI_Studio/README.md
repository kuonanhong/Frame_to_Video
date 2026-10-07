# FRAME CPU：免費本機圖片轉短影片

2026-10-07 改版。預設入口改為使用者裝置運算的CPU照片工具；原版生成式AI工作室仍保留在 `dist/`，其完整說明移到 `docs/CLASSIC_README.md`。上傳的原單檔保存在 `FRAME_Classic_Uploaded.html`。

## 開啟

直接雙擊 `FRAME_CPU_Studio.html`：內嵌22語介面、COCO-SSD辨識模型、程式與Worker，不需付費API、CUDA或網路推論服務。單檔約24.5 MiB；瀏覽器不允許本機Worker／錄影時，請改用HTTP方式。

建議本機開啟完整套件：

```bash
python3 -m http.server 8080 --bind 127.0.0.1
```

瀏覽 `http://127.0.0.1:8080/` 或 `/edge/`。Windows可用 `py -m http.server 8080 --bind 127.0.0.1`。

GitHub Pages：把此資料夾**內的內容**放到儲存庫Pages的根目錄，保留 `index.html`、`edge/`、`docs/` 及 `dist/` 相對位置。不要上傳 `node_modules/`、Python虛擬環境或暫存產物。

## 使用與能力

1. 選擇JPEG、PNG、WebP，或試用示例。圖片保留比例並縮小到最大邊960px工作尺寸。
2. 按「辨識物件」：CPU神經網路辨識80類常見物件，顯示框線與分數。它會漏判或誤判，不是精確分割，也不包含所有自然景物。
3. 水面、樹木、雲朵可手動畫框。選好類型，按「畫框新增」，在原圖拖曳。物件框可停用或刪除。
4. 輸入有限動作短語，或用多語效果按鈕：推近、平移、搖擺、水波、雪。按鈕填入確定支援的標準詞；不是大型語言模型。
5. 選480p、18fps、4秒開始預覽。較弱手機可用12fps，720p依實際效能選用。
6. 匯出影片並下載。MediaRecorder依瀏覽器選擇WebM或MP4；輸出無聲。預覽或錄影時切到背景會停止。

這是**CPU物件辨識＋規則照片動畫**，不做單圖生成式影片。沒有真實人物走路、動物飛翔、新背景補畫、姿態合成或3D深度模型。照片不會因這些CPU操作上傳，沒有伺服器推論佇列；多人各自運算，但網站與模型下載仍有託管頻寬及服務限額。

CPU推論不使用WebGL／WebGPU後端；畫面合成與影片編碼仍可能由瀏覽器／作業系統使用硬體加速，不能強制整個瀏覽器完全不碰GPU。

## 完整指南

- `docs/CPU_使用與部署說明.md`：本機、手機、GitHub、22語、編碼及排查。
- `docs/CPU_演算法與限制.md`：幾何、遮罩、提示詞範圍、單圖光流與MCU限制。
- `docs/MODEL_NOTICES.md`：模型版本、官方來源、授權、校驗及CPU測試。
- `docs/CPU_VALIDATION.md`：本次真實瀏覽器測試與尚未測試的裝置。

## 維護

原始碼：`edge/app.mjs`、`edge/motion-core.mjs`、`edge/motion-worker.js`、`edge/model/detector-worker-source.mjs`。介面73個核心字串提供22語，COCO類名保留英文；翻譯尚未經母語編輯審校。

```bash
npm ci
npm run build:cpu
npm run test:cpu
python3 edge/model/verify-model.py
```

`build:cpu`以套件中的本地模型重建worker、bundle、根入口、22語入口及單檔HTML，不需要重新下載模型。瀏覽器QA可指定已安裝的Chromium：`FRAME_BROWSER_PATH=/path/to/chromium npm run test:cpu:browser`。`npm run build`仍是原版生成式AI工作室的重建流程。

原創程式MIT，第三方模型與runtime保留Apache-2.0授權及NOTICE。模型JSON與全部5個權重分片已附，不要求CDN或API key。原版LTX/Wan/SD-Turbo模型的授權與GPU條件仍以 `backend/` 及原版文件為準；它們不參與CPU工具的免費流程。
