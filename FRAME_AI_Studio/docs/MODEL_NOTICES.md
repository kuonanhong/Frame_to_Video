# 本機 CPU 物件偵測模型：來源、授權與限制

核對日期：2026-10-07。

本版使用 Google / TensorFlow 的 COCO-SSD SSDLite MobileNet V2。
它是**非生成式物件偵測模型**，輸出類別、信心分數、矩形邊界；不是
圖像生成器、影片生成器、分割遮罩、深度估計器或任意物件理解模型。

## 實際封裝

| 元件 | 封裝版本／來源 | 授權 |
|---|---|---|
| `@tensorflow/tfjs-core` | 4.22.0 | Apache-2.0 |
| `@tensorflow/tfjs-converter` | 4.22.0 | Apache-2.0 |
| `@tensorflow/tfjs-backend-cpu` | 4.22.0 | Apache-2.0 |
| `@tensorflow-models/coco-ssd` | 2.2.3 | Apache-2.0 |
| `seedrandom`（間接相依） | 3.0.5，David Bau | MIT |
| `long`（間接相依） | 4.0.0 | Apache-2.0 |
| SSDLite MobileNet V2 模型 | TensorFlow.js 官方 GCS 模型檔；TensorFlow 官方 Kaggle 模型頁標示 Apache 2.0 | Apache-2.0 |
| FRAME adapter／client | 本專案新增原始碼 | MIT（本專案 LICENSE） |

模型 JSON 和五個權重分片合計 **18,561,843 bytes**，沒有量化或修改權重。
逐檔實際下載大小、SHA-256 與來源網址見
`edge/model/coco-ssd-lite/manifest.json`。模型檔下載自：

<https://storage.googleapis.com/tfjs-models/savedmodel/ssdlite_mobilenet_v2/model.json>

所有模型、JavaScript runtime、權重與授權文字均隨包附上。
多檔網頁版由同一網站載入它們，不需要 CDN、模型 API、API Key、登入或付费服務。
單檔版內嵌同一模型和 runtime，利用 `tf.io.fromMemory()` 載入。
首次按下偵測才初始化模型，圖片資料留在訪客瀏覽器與本頁 Worker。

## 官方核對來源

- Google / TensorFlow COCO-SSD 說明，80 類、模型 URL、自訂 URL、邊界框 API：
  <https://github.com/tensorflow/tfjs-models/blob/master/coco-ssd/README.md>
- 官方模型與來源類別表：
  <https://github.com/tensorflow/tfjs-models/blob/master/coco-ssd/src/classes.ts>
- 官方程式將 `modelUrl` 交由 `loadGraphModel()` 載入：
  <https://github.com/tensorflow/tfjs-models/blob/master/coco-ssd/src/index.ts>
- Google / TensorFlow 官方 SSDLite MobileNet V2 TfJS 模型頁，標示 Apache 2.0，
  並標示此模型發布於 `@tensorflow-models/coco-ssd`：
  <https://www.kaggle.com/models/tensorflow/ssdlite-mobilenet-v2/tfJs/default/1?tfhub-redirect=true>
- TensorFlow.js、tfjs-models、TensorFlow Models 的完整 Apache 授權：
  <https://github.com/tensorflow/tfjs/blob/master/LICENSE>
  <https://github.com/tensorflow/tfjs-models/blob/master/LICENSE>
  <https://github.com/tensorflow/models/blob/master/LICENSE>

完整授權副本位於 `edge/model/licenses/`，打包工具另保留第三方原始授權註記於
`edge/detector-worker.js.LEGAL.txt`。更新／重新分發時請同時保留這些檔案。
COCO 訓練資料的原始照片並沒有隨包分發。本版測試曾使用上游 demo 貓照片，
該測試照片沒有加入交付包或當成可任意利用的圖庫素材。

## 80 類的實際邊界

類別如人、貓、狗、鳥、車、船、盆栽、椅子、手機等；完整表見
`edge/model/coco-classes.json`。不包含「所有物件」：天空、水、海、雲、山、
瀑布、煙、頭髮、表情、人體關節、人的身分，都不是這80個類別。
模型可能漏判、誤判，尤其是插畫、小物件、遮擋、低光和超出訓練分布的照片。
矩形框**不是精確物件輪廓**。相片中的框、類別與分數必須供使用者確認。
不得把使用者手動畫的區域偽稱為模型辨識結果。

## CPU 與跨平台

Worker 只載入 JavaScript `cpu` backend，呼叫 `tf.setBackend('cpu')`，
沒有打包 WebGL、WebGPU 或 TensorFlow 原生 GPU backend。
這表示**模型推論不需 GPU**；瀏覽器可能自行利用 GPU 繪製 Canvas 或編碼影片，
網站不能以此保證整部裝置完全不使用任何 GPU 硬體。
模型先在 CPU 偵測一次；製作動畫時不需要每幀重新執行模型。
偵測輸入最長邊限制為640像素，再由模型縮放為300×300；輸出框還原為
原 ImageData 像素座標。這可控制記憶體，但小物件可能因此更難辨識。

Web Worker 避免推論阻塞主頁；舊裝置／低階手機仍可能推論數秒或更久。
這是手機／桌機網頁設計，不是「1080p MCU 影片逐幀幾毫秒」的保證。
目前只測本機 Node CPU 與另列的 Chromium QA；Mac Safari、iPhone、Android
實機效能仍需個別驗證。詳見主驗證文件。

多人使用時，每位訪客在自己裝置上推論，沒有共同的中央推論佇列。
靜態託管仍有頻寬、檔案下載量及平台限制；本模型每個未快取訪客
需下載約18.6 MB，不代表無限流量或十萬人同时在线的保證。

## 維護／重建

先在專案根目錄依 `package.json` 安裝固定版本依賴，再執行：

```sh
node edge/model/build-detector.mjs
python3 edge/model/verify-model.py
```

`detector-worker-source.mjs` 是可編輯原始碼；`detector-worker.js` 是可直接部署的
打包成品。修改來源後需要重建，再重建單檔 HTML（若有使用它）。
不要只更新 HTML 而漏掉 `edge/model/coco-ssd-lite/` 和 Worker runtime。

Client API：

```js
import { loadDetector, detectImage, disposeDetector } from './edge/detector-client.mjs';
await loadDetector({ onProgress: ({ stage, progress }) => console.log(stage, progress) });
const predictions = await detectImage(imageData, { minScore: 0.45, maxObjects: 20 });
// [{label:'cat', classId:17, score:0.93, bbox:[x,y,width,height]}, ...]
disposeDetector();
```

載入進度是階段資訊，不是精準網路 byte 百分比。取消／逾時會停止 Worker，
釋放模型；下次需重新載入。單檔版 `embeddedModel.weightData` 會 transfer，
因此載入後該 ArrayBuffer 已移交 Worker；重試需重新解碼內嵌權重。

## 本次模型測試摘要

在此工作環境的 Node JavaScript CPU backend，使用真正的上述模型，
而不是手工假預測：

- 上游224×224貓測試照片：`cat`，信心0.9279；載入約1.53秒，推論約1.61秒。
- 套件海岸示例縮為640×360：低閾值0.15偵測到 `boat`，信心0.3038；
  默认0.45閾值則為零物件，屬實際結果。
- 推論前後262個模型 tensors，無增長；`dispose()` 後為0。
- 同一測試成功使用內嵌 `tf.io.fromMemory()` 模型載入。

時間只是這次工作環境的觀察，不是手機、MCU、Mac 或多人服務效能承諾。
