# FRAME 本機生成後端

這個 Python 3.11 / FastAPI 後端將前端的文字生圖、圖片生影片與影片改寫請求送到本機 Diffusers 模型，並以非同步工作提供結果。影片推論需要 NVIDIA CUDA GPU；只有 SD-Turbo 文字生圖支援較慢的 CPU 執行。正式推論流程不會使用示意圖片或拼接假影片代替模型結果。

程式採用固定模型版本，首次執行相應工作才下載權重。下載可能達數十 GB，請預留磁碟空間、主記憶體與網路時間。GPU 推論依賴已固定版本，目前驗證範圍只有使用替代推論函式的 API 測試，尚未完成真實 GPU 推論或 Docker 建置實測；不保證特定 GPU 的記憶體用量、速度或生成品質。

## 模型與用途

| 工作 | API 模型值 | Hugging Face 模型 | 固定 revision |
| --- | --- | --- | --- |
| 文字生圖 | `sd-turbo` | `stabilityai/sd-turbo` | `b261bac6fd2cf515557d5d0707481eafa0485ec2` |
| 圖片生影片、影片改寫 | `ltx-2b` | `Lightricks/LTX-Video-0.9.5` | `e58e28c39631af4d1468ee57a853764e11c1d37e` |
| 圖片生影片 | `wan-5b` | `Wan-AI/Wan2.2-TI2V-5B-Diffusers` | `b8fff7315c768468a5333511427288870b2e9635` |

LTX 0.9.5 是 2B 模型。影片改寫使用 `LTXConditionPipeline` 的來源影片條件；`strength` 控制來源保留程度，值越高越接近來源。它不是傳統影像編輯的雜訊強度，生成結果也不保證逐幀保留所有內容。Wan 使用明確的 `WanImageToVideoPipeline`，而不是模型儲存庫預設的文字生影片管線。

本後端採以下固定輸出尺寸：

| 模型 | `16:9` | `9:16` | `1:1` |
| --- | --- | --- | --- |
| SD-Turbo | 512×512 | 512×512 | 512×512 |
| LTX 2B | 512×288 | 288×512 | 512×512 |
| Wan 5B | 1280×704 | 704×1280 | 896×896 |

`aspect` 只影響影片工作，SD-Turbo 一律輸出 512×512。Wan 的寬 / 高尺寸採官方原生設定，因此 `16:9` / `9:16` 是接近該比例的預設，並非精確比例。來源圖片與影片畫面會縮放、置中裁切至目標尺寸。

Wan 官方的 1280×704、24fps、CPU offload 推論指令以至少 24GB VRAM 為參考；本後端使用相同原生尺寸，但未驗證本套 Diffusers 設定的實際 VRAM 用量。LTX 2B 使用較低解析度的草稿尺寸，仍未以 GPU 實測。影片解析度、長度、文字編碼器與 CPU offload 都會影響 VRAM / RAM 需求。CPU offload 會降低 GPU 常駐記憶體用量並增加主記憶體需求與等待時間。

影片改寫取來源影片開頭，依要求時長及模型幀數對齊，重新取樣為 24fps；來源不足時，重複最後一幀補足長度。輸出 MP4 不包含來源音訊。

## 安裝與啟動

先準備 Python 3.11，以及與 CUDA 12.8 PyTorch wheel 相容的 NVIDIA 驅動。在本目錄執行：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements.txt
python -m pip check
uvicorn app:app --host 0.0.0.0 --port 7860
```

第二次安裝會沿用已安裝的 `torch==2.8.0+cu128`。若只測 CPU 生圖，將 PyTorch 安裝命令的索引改為 `https://download.pytorch.org/whl/cpu`，並設定 `FRAME_DEVICE=cpu`。Windows 可使用 `.venv\Scripts\Activate.ps1` 啟用環境。來源影片解碼與 MP4 輸出透過 imageio 的 FFmpeg 功能；`imageio-ffmpeg` wheel 包含 FFmpeg 執行檔，另外安裝系統 FFmpeg 是選配，也可設定 `IMAGEIO_FFMPEG_EXE` 指定執行檔。

前端填入後端位址 `http://localhost:7860`。使用 API Key 時，前端也須填入同一把 Key。健康檢查為 `GET http://localhost:7860/api/health`。啟動成功只代表 HTTP 服務可用；首次實際生成仍可能在下載、載入模型或推論階段失敗。

只執行一個 Uvicorn worker。工作狀態與生成佇列由單一程序管理，重新啟動後不會恢復任何工作狀態或原本的結果 URL。磁碟上的檔案可能仍然存在；啟動與背景清理會按檔案時間移除超過保留期限的無關聯檔案。

## 環境變數

| 名稱 | 預設值 | 用途 |
| --- | --- | --- |
| `FRAME_DEVICE` | `auto` | `auto`、`cuda` 或 `cpu`；CPU 僅提供文字生圖。 |
| `FRAME_API_KEY` | 未設定 | 設定後，受保護的 API 以 `Authorization: Bearer <key>` 驗證。 |
| `FRAME_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080` | 以逗號分隔的完整前端 origin；部署前端時加入其 HTTPS origin。 |
| `FRAME_DATA_DIR` | `./data` | 來源上傳、工作中間檔與輸出檔的存放位置。 |
| `FRAME_MODEL_CACHE` | 未設定 | 指定 Hugging Face 模型快取目錄；未設定時使用其標準快取。 |
| `FRAME_LOW_MEMORY` | `1` | 在 CUDA 使用模型 CPU offload；設為 `0` 可使用較多 VRAM。 |
| `FRAME_KEEP_HOURS` | `24` | 已完成工作與暫存輸出的保留時間。 |
| `FRAME_MAX_JOBS` | `100` | 保留的工作數量上限。 |
| `FRAME_KEEP_INPUTS` | `0` | 預設在推論結束或取消後刪除來源上傳；設為 `1` 可保留來源至工作清除。 |
| `IMAGEIO_FFMPEG_EXE` | 未設定 | 選填，覆寫 imageio 使用的 FFmpeg 執行檔路徑。 |

瀏覽器 CORS 設定不等同存取驗證。若將服務開放到網際網路，應設定 API Key，並透過 HTTPS 反向代理提供服務。上傳來源與結果暫存於本機資料目錄；不會自動上傳到模型推論供應商。

## API

| 路徑 | 方法 | 用途 |
| --- | --- | --- |
| `/api/health` | `GET` | 檢查服務與執行環境。 |
| `/api/jobs` | `POST` | 以 multipart form 建立工作。 |
| `/api/jobs/{id}` | `GET` | 查詢工作進度、結果或錯誤。 |
| `/api/jobs/{id}` | `DELETE` | 要求取消工作；排隊工作立即取消，進行中的工作先標記 `cancel_requested=true`。已成功、失敗或取消的工作維持原狀，不會刪除完成的輸出。 |
| `/api/files/{id}` | `GET` | 取得成功工作的圖片或 MP4。 |

取消採合作式中斷：模型步驟、來源解碼或輸出編碼會檢查取消旗標；模型載入與網路下載不會立即中斷。完成的輸出依 `FRAME_KEEP_HOURS` 清除，`DELETE` 不提供立即刪除完成結果的功能。

`POST /api/jobs` 的 multipart 欄位：

| 欄位 | 規則 |
| --- | --- |
| `workflow` | 必填：`text-image`、`image-video` 或 `video-video`。 |
| `model` | 選填；文字生圖預設 `sd-turbo`，影片工作預設 `ltx-2b`。`wan-5b` 僅支援圖片生影片。 |
| `prompt` | 必填，1–1800 字元。 |
| `negative_prompt` | 選填，最多 1800 字元；SD-Turbo 不使用負面提示詞。 |
| `file` | 圖片生影片與影片改寫必填；文字生圖不接受上傳。PNG / JPEG / WebP 圖片最多 20MB，MP4 / WebM / MOV 影片最多 80MB。影片的容器標頭在上傳時檢查，實際解碼在推論階段由 imageio / FFmpeg 執行。 |
| `duration` | 1–5 秒，預設 3 秒；輸出為 24fps，幀數依模型需要對齊，因此時長可能有少量差異。 |
| `aspect` | `16:9`、`9:16` 或 `1:1`，預設 `16:9`；僅影響影片。Wan 使用接近比例的原生尺寸。 |
| `seed` | 0–4294967295 整數，預設 0；固定種子仍可能因裝置、版本或運算方式而出現差異。 |
| `strength` | 0.05–0.95，預設 0.65；影片改寫的來源保留程度。 |

例如，以 LTX 建立圖片生影片工作：

```bash
curl http://localhost:7860/api/jobs \
  -F workflow=image-video \
  -F model=ltx-2b \
  -F 'prompt=The camera slowly moves forward; soft waves move naturally.' \
  -F duration=3 \
  -F aspect=16:9 \
  -F seed=42 \
  -F file=@input.png
```

若有設定 `FRAME_API_KEY`，在每個受保護請求加入 `-H "Authorization: Bearer $FRAME_API_KEY"`。建立工作後，以回應中的 `id` 輪詢 `/api/jobs/{id}`；查詢回應含 `status`、`progress`、`message`、`error`、`created_at`。成功後，`output_url` 指向 `/api/files/{id}`，`output_type` 為 `image` 或 `video`。生成錯誤會由工作查詢回應提供，不應被當成成功的示意輸出。

## Docker / NVIDIA GPU

主機需要 NVIDIA GPU、相容驅動與 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)，Docker 才能使用 `--gpus all`。映像採 Python 3.11，先從官方 `cu128` 索引安裝 PyTorch 2.8.0，再安裝其餘固定依賴；模型權重不包含在映像中。

```bash
docker build -t frame-backend .
docker volume create frame-data
docker volume create frame-model-cache
docker run --rm --gpus all \
  -p 127.0.0.1:7860:7860 \
  -v frame-data:/app/data \
  -v frame-model-cache:/app/model-cache \
  -e FRAME_DEVICE=cuda \
  frame-backend
```

需要遠端前端時，以 `-e FRAME_ALLOWED_ORIGINS=https://your-frontend.example` 設定實際前端 origin，並按部署環境提供 API Key。兩個命名 volume 分別保留輸出與模型快取；`--rm` 只移除容器。映像以 UID 1000 執行，若改成主機目錄掛載，該目錄必須允許此使用者寫入。

## 不需 GPU 的 API 測試

若只驗證 HTTP 服務與佇列，可只安裝 `requirements-api.txt`；不需要安裝 Torch 或 Diffusers。完整生成則必須使用前述安裝步驟。

```bash
python -m pip install -r requirements-api.txt
python -m unittest discover -s tests -v
```

`tests/test_api.py` 以替代推論函式驗證 API 邏輯，不下載模型、不使用 GPU，也不證明實際模型可執行。正式程式的模型載入在 `infer.py` 中延後進行。部署前仍需在目標硬體分別完成三種工作流程的實際推論檢查。

## 授權與來源

模型權重的授權與本後端程式的授權分開。使用、再散布或商用前，請閱讀以下模型授權及其限制：

- Wan：Apache 2.0，遵守授權與 NOTICE 要求。
- SD-Turbo：Stability AI Community License；商用須向 Stability AI 註冊，免費商用門檻為年營收低於 100 萬美元（US $1m）。超過授權門檻需取得其他商業授權；門檻計算包含關係企業，請以完整條款為準。提供模型或使用它的產品 / 服務時，須附授權與 Notice，並提供 **Powered by Stability AI** 標示。
- LTX 0.9.5：Open RAIL-M，包含使用限制。較新 LTX 版本採其他條款，本套件固定 0.9.5，不能將其授權推廣到其他版本。

**Powered by Stability AI**

本套件附有 [NOTICE](NOTICE) 與模型授權副本：`licenses/SD-Turbo-LICENSE.md`、`licenses/LTX-Video-0.9.5-LICENSE.txt`、`licenses/Wan-Apache-2.0-LICENSE.txt`。發佈此後端及整合前端時，保留相應授權與標示；模型權重不包含於套件內。

原始文件與固定版 API：

- [PyTorch 2.8.0 官方安裝命令](https://pytorch.org/get-started/previous-versions/)
- [Diffusers 0.35.1 安裝](https://huggingface.co/docs/diffusers/v0.35.1/installation)
- [SD-Turbo 模型與使用方式](https://huggingface.co/stabilityai/sd-turbo)
- [SD-Turbo LICENSE](https://huggingface.co/stabilityai/sd-turbo/blob/main/LICENSE.md)
- [Wan 5B 模型、硬體說明與 Apache 2.0 授權](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers)
- [Wan 0.35.1 API](https://huggingface.co/docs/diffusers/v0.35.1/api/pipelines/wan)
- [Wan I2V 0.35.1 原始碼](https://github.com/huggingface/diffusers/blob/v0.35.1/src/diffusers/pipelines/wan/pipeline_wan_i2v.py)
- [LTX 0.9.5 模型](https://huggingface.co/Lightricks/LTX-Video-0.9.5)
- [LTX 0.9.5 模型授權](https://huggingface.co/Lightricks/LTX-Video/blob/main/ltx-video-2b-v0.9.5.license.txt)
- [LTX 0.35.1 API](https://huggingface.co/docs/diffusers/v0.35.1/api/pipelines/ltx_video)
- [LTX 條件管線 0.35.1 原始碼](https://github.com/huggingface/diffusers/blob/v0.35.1/src/diffusers/pipelines/ltx/pipeline_ltx_condition.py)

本後端供有足夠硬體的本機或自管 GPU 主機使用。免費雲端 GPU 的供應、配額與工作時間限制會變動，不提供永遠免費、持續運作的雲端推論承諾。
