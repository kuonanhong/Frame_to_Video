# 選用：本機 CPU 神經網路圖片編輯

這是三個真實 Diffusers 推論介面的完整 Python 原始碼。安裝 Python 套件並自行下載模型後，會在**自己電腦的 CPU** 上執行神經網路，輸出一張修改後的 PNG；再把它加入 FRAME 的影片分鏡。它不會產生人物「讀書後大笑」的連續動作，也不會把圖片重繪假稱為文字生成影片。

GitHub Pages 只提供 HTML、JavaScript、圖片等靜態檔案，不能替網站訪客執行這個 Python 服務。手機與平板可以使用網站的剪輯／照片動畫功能；這個額外的 CPU 模型服務需在能安裝 Python／PyTorch 的桌機或筆電啟動。它只允許同一部電腦連線，沒有對外開放伺服器模式。

**本交付沒有附帶這三個模型的 GB 級權重。** v5 已在獨立 Linux x86_64／Python 3.11.17／Torch 2.6.0 CPU 環境，真正下載並執行三種模型，使用 float32、8 個 CPU 執行緒，沒有 GPU。時間包含模型載入；RAM 為程序核心峰值，不是所有電腦的需求保證。

| 真實測試 | 尺寸／設定 | 實測時間 | 程序峰值 RAM | 目視及像素檢查 |
|---|---|---|---|---|
| SD-Turbo | 512×288；4 步、strength 0.75 | 14.46 秒 | 6.75 GiB | 出現較暗雲層，但構圖改變、原帆船未保留 |
| InstructPix2Pix | 256×144；15 步 | 27.17 秒 | 6.01 GiB | 山景出現積雪，大致保留海岸與帆船 |
| SD Inpainting | 384×216；20 步 | 41.28 秒 | 7.05 GiB | 遮罩區改變；78,541 個黑遮罩像素全部原樣保留，但沒有畫出要求的橘色熱氣球 |

PNG、完整測量 JSON、模型 revision／檔案 SHA-256 與原始碼雜湊位於 `qa/`。這三次是實際模型煙霧測試，**不是品質評比，也不是動作影片生成**。Intel Mac、Apple Silicon、Windows 尚未實機驗證，不能將 Linux 秒數當作您電腦的速度。v4 的舊 SD-Turbo 報告保留供追溯；v5 新結果與相同輸入／seed 的 v4 PNG 雜湊相同。

另外已通過 16 個輸入、HTTP、工作佇列、取消、模型缺失、三個 adapter 呼叫參數、遮罩保留及平台套件選擇測試；這些測試的神經推論邊界採 mock，與上述真實模型測試分開記錄。Linux 的一個指令安裝／啟動流程也已連到真實本機 HTTP 服務並確認三個模型狀態。`installed: true` 代表檔案清單與大小符合安裝記錄，不代表您這次安裝已通過模型品質測試。

## 可選模型

| API 識別 | 來源 | 作用 | 建議提示詞 |
|---|---|---|---|
| `sd-turbo` | `stabilityai/sd-turbo` | 圖生圖，1–4 個採樣步數，通常較快；可能改變人物或構圖 | `A cozy living room with warm sunset light, realistic photograph` |
| `instruct-pix2pix` | `timbrooks/instruct-pix2pix` | 文字指令修改圖片，15 步起；較容易理解「把…改成…」但不保證每次成功 | `Change the jacket to a blue denim jacket` |
| `sd-inpaint` | `stable-diffusion-v1-5/stable-diffusion-inpainting` | 塗白區域重繪，黑色區域保留；適合局部家具／服裝／髮型概念圖 | `A small oak bedside table beside the bed, realistic photograph` |

最後一個來源是已停用 Runway 舊 repository 的**社群鏡像**，與 RunwayML 沒有隸屬關係。下載程式只接受表內固定 ID，不會執行任意模型程式碼。所有模型使用 Safetensors；磁碟下載 fp16 版本，載入時轉為 CPU float32 計算，沒有 CUDA／MPS／GPU 分支。保留模型附帶的 safety checker。

這些模型主要使用英文提示詞。介面翻譯不會自動讓模型具備所有語言的提示理解能力。可先手寫英文提示；例如「沉浸讀書後大笑」是時間動作描述，這三個**靜態圖片**專家無法輸出該動作影片。改成 `A portrait of the same person laughing while holding a book`，也只是嘗試產生一張笑容圖片，身分及手部仍可能失真。

每個模型會下載數 GB，載入 float32 後另占數 GB 記憶體；步數、尺寸、CPU、RAM 會大幅影響速度。建議桌機至少 16 GB RAM、有 15–20 GB 可用磁碟，較完整測試建議 32 GB 以上；這不是保證可用的最低規格。您的 Intel i9／64 GB RAM 可從 SD-Turbo 單張測試開始，仍需測量实际時間。最多長邊 512，單次一張，一次只執行一個任務，不會用「有幾個 CPU 核心」推算或宣稱即時。

## 一個指令安裝並啟動（v5）

先安裝 Python 3.11，終端機切到 FRAME 專案根目錄。第一次指令會建立獨立 `.venv-native` 環境、安裝固定版本套件，並主動下載 SD-Turbo（約 2.58 GB 的模型檔案，另需安裝空間）。請先閱讀模型授權。

macOS／Linux：

```bash
python3.11 native_cpu/setup_native.py --model sd-turbo --launch
```

Windows：

```powershell
py -3.11 native_cpu/setup_native.py --model sd-turbo --launch
```

macOS 亦可執行 `native_cpu/start_native.command`（若解壓縮遺失執行權限，改用上方指令）；Windows 可雙擊 `native_cpu/start_native.bat`。兩者都會下載 SD-Turbo 並啟動服務。第二次啟動會重用完整的本機模型，不重新下載。Python 套件仍會做版本、CPU 計算及 NumPy 相容檢查；檢查通過並不代表圖片品質通過評比。

要多安裝一個專家，可將 `--model instruct-pix2pix` 或 `--model sd-inpaint` 加到指令；`--model` 可以重複。只安裝套件時省略 `--model`。套件損壞時加 `--repair`；不會删除使用者模型。模型另放大磁碟可用 `--model-dir "/你的模型目錄"`，往後啟動要保留同一選項。

安裝器依平台選擇 Intel Mac 的 Torch 2.2.2、Linux／Windows x86_64 的 Torch 2.6.0 CPU，以及 Apple Silicon 的 Torch 2.6.0（仍用 CPU）。只有 Linux x86_64 的實際安裝／執行完成測試；Mac 與 Windows 為原始碼及官方 wheel 選擇核對，沒有實機測試。其他架構會停止並顯示原因。

下方保留手動安裝步驟，方便診斷或使用既有獨立環境。

## 1. 建立 Python 3.11 環境

請先安裝 **Python 3.11**。不要在現有重要專案環境直接升降套件版本。

macOS／Linux，在終端機切到解壓縮後含有 `index.html` 的 FRAME 專案根目錄：

```bash
cd "/你的路徑/FRAME_AI_Studio"
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell：

```powershell
cd "C:\你的路徑\FRAME_AI_Studio"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

Windows 下文所有 `python`，請改用 `.\.venv\Scripts\python.exe`，不需要調整 PowerShell execution policy。

## 2. 安裝 CPU 套件

### Intel Mac（您目前的機器）

PyTorch 官方表示 2.2.x 是最後支援 macOS x86／x64 的版本；不能照抄 Apple Silicon 最新版安裝方式。此處固定 2.2.2 配 Python 3.11：

```bash
python -m pip install torch==2.2.2
python -m pip install -r native_cpu/requirements.txt
```

NumPy 固定為 1.26.4 以配合舊 PyTorch；不要在此環境擅自升級到 NumPy 2。若安裝器說沒有對應 wheel，先確認 `python --version` 是 3.11，並執行 `python -c "import platform; print(platform.machine())"`，Intel Mac 預期 `x86_64`。

### Windows／Linux x86_64

```bash
python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r native_cpu/requirements.txt
```

### Apple Silicon Mac

```bash
python -m pip install torch==2.6.0
python -m pip install -r native_cpu/requirements.txt
```

程式仍明確使用 CPU，不會切換 MPS。其他 CPU 架構若沒有對應 PyTorch wheel，需先依 PyTorch 官方支援情況處理，不能保證同一安裝指令涵蓋全部硬體。

檢查依賴：

```bash
python -c "import torch,diffusers,transformers; print(torch.__version__,diffusers.__version__,transformers.__version__)"
```

固定的 Diffusers 0.30.3／Transformers 4.44.2 是本程式 API 相容基線，並非宣稱最新版本。此本機服務不應放到公網。升級依賴後請重新執行測試與真實 smoke test。

## 3. 主動下載需要的模型（第一次需網路）

先閱讀各模型頁面的授權。免費取得權重不等於所有用途均無限制；尤其 SD-Turbo 請查看 Stability AI 當前授權，另兩者也需遵守模型卡與其底層模型條款。程式下載公開模型不需 GitHub PAT，也不會讀取或顯示私人雲端 Token。

先下載一種即可：

```bash
python native_cpu/fetch_models.py --model sd-turbo
```

需要其他用途時再依序下載：

```bash
python native_cpu/fetch_models.py --model instruct-pix2pix
python native_cpu/fetch_models.py --model sd-inpaint
```

預設儲存在 `native_cpu/models/模型識別/`，它已加入 `.gitignore`，**不要上傳到 GitHub Pages**。下載會先把當時的 `main` 解析為不可變 commit SHA，再只下載該 commit 的必要檔案。中斷可重新執行同一指令續傳；`FRAME_INSTALL.json` 記錄來源 SHA、所有檔案大小與 SHA-256。若要重現已下載版本，可取記錄中的 40 字元 SHA：

```bash
python native_cpu/fetch_models.py --model sd-turbo --revision 你的40字元commitSHA
```

最後一行為範例；請替換成真實 SHA，不能原樣輸入。亦可用環境變數 `FRAME_NATIVE_MODEL_DIR` 指定自己的大型磁碟目錄；下載與伺服器需使用同一設定。

離線校驗：

```bash
python native_cpu/fetch_models.py --model sd-turbo --verify
```

推論時強制 `local_files_only=True`、`HF_HUB_OFFLINE=1`；缺權重會顯示缺少，不會暗中大量下載、不會改呼叫付費服務。

## 4. 開啟有本機 CPU API 的網站

```bash
python native_cpu/server.py --port 8787
```

在同一台電腦開啟 **http://127.0.0.1:8787/**。這個指令已同時提供整個網站及本機 CPU API，不必再開另一個 `http.server`。網站的本機 AI 區塊會查詢 `/api/status`；只有此來源才可提交生成任務。

普通的 `python -m http.server 8080` 與 GitHub Pages 能執行前端剪輯，**不會執行這個 Python 模型 API**。來自 GitHub Pages 的網頁也不能直接連到本機 CPU 服務，避免跨來源讀取本機資料。若要使用本機模型，請用上面的本機入口。

模型第一次載入、VAE 解碼、單一步 CPU 計算可能很久。取消是合作式，會在模型載入完成或下一個去噪步驟邊界生效；不能承諾立即停止。每次任務結束釋放 pipeline，後續任務會重新載入，以降低多模型同時占 RAM 的風險。

結果僅在伺服器記憶體保留最近 8 筆，關閉伺服器後清除；上傳照片、提示詞及遮罩不寫入磁碟。請在需要時自行儲存產出或加入分鏡。`models/` 內只儲存權重及安裝記錄。

## 5. 本機真實生成測試

這個步驟才會真的執行已下載模型：

```bash
python native_cpu/smoke_real.py --model sd-turbo --image "/你的路徑/room.jpg" --prompt "A cozy living room with warm sunset light" --output native_cpu/outputs/turbo-test.png
```

產出 `turbo-test.png` 與 `turbo-test.report.json`；後者記錄真實耗時、平台／套件版本、來源 revision、CPU dtype、程序 RAM 峰值、原始碼及圖檔 SHA-256、逐步進度與像素檢查。Linux／macOS 的記憶體使用核心 RUSAGE_SELF；Windows 使用每 25ms 採樣，可能漏掉短暫峰值。可用 `--max-side 256` 先做小圖測試。若目標檔案已存在，程式拒絕覆蓋，請改檔名。

局部重繪例：先準備和照片**完全相同尺寸**的灰階 PNG 遮罩；要修改的區域塗白，其餘塗黑。

```bash
python native_cpu/smoke_real.py --model sd-inpaint --image "/你的路徑/room.jpg" --mask "/你的路徑/room-mask.png" --prompt "A small wooden chair beside the window, realistic photo" --output native_cpu/outputs/chair-test.png
```

照片與遮罩會一起等比例縮放／補邊。v5 明確傳入 inpaint 的寬／高，修正非正方形圖片被 Diffusers 預設尺寸改成正方形、造成遮罩合成失敗的問題。完成後黑色區域會以準備後的原图像素覆蓋回去，避免未選區被模型順便改變；白色區域的內容、透視與物理尺寸仍需人工檢查，並不構成 CAD 或可量測的 3D 設計。

## HTTP API（前端開發者）

所有路徑相對於同一個 `http://127.0.0.1:8787`。沒有 CORS 開放、外部圖片 URL、shell 執行參數、任意模型 ID 或任意檔案路徑 API。

| 方法／路徑 | 行為 |
|---|---|
| `GET /api/status` | 回報真實依賴版本、模型安裝狀態、`busy`、`max_side` |
| `POST /api/jobs` | multipart 建立工作，回傳 202；忙碌／缺模型 409，缺依賴 503 |
| `GET /api/jobs/{id}` | `queued/running/completed/failed/cancelled`，`progress`，`phase`，錯誤或結果 URL |
| `POST /api/jobs/{id}/cancel` | 請求取消；在計算步驟邊界檢查 |
| `GET /api/jobs/{id}/result.png` | 完成結果，`image/png`；未完成或已清除 404 |

`POST /api/jobs` 欄位：

- `expert`: `sd-turbo`、`instruct-pix2pix`、`sd-inpaint`。
- `prompt`: 1–1000 字元。
- `image`: 必填 PNG/JPEG/WEBP/BMP，最多 12 MiB、24 MP；禁止 URL。
- `mask`: inpaint 必填，其餘忽略；與來源照片相同尺寸。
- `steps`: Turbo 1–4（預設 4），其餘 1–30（預設 15／20）。
- `strength`: Turbo 圖片變化強度 0.1–1（預設 0.75），且 `steps × strength ≥ 1`。
- `guidance`: Pix2Pix／Inpaint 1–15（預設 7.5）；Turbo 固定 0。
- `image_guidance`: Pix2Pix 1–3（預設 1.5）。
- `seed`: 0–4294967295（預設 42）。相同 seed 不保證不同 CPU／函式庫版本逐位元一致。
- `max_side`: 256–512（預設 512），輸出邊長會取 8 的倍數。

前端請用 `FormData`，不要自己設定 `Content-Type` 邊界；每 1–2 秒查詢狀態。Service Worker 不應快取 `/api/`。圖片結果是單張 PNG，需由使用者確認後加入分鏡，再用前端剪輯匯出影片。

## 已執行的程式測試

```bash
python -m unittest discover -s native_cpu/tests -v
```

16 項測試包含真實 loopback HTTP server、來源／Host 防護、隱藏目錄／權重路徑拒絕、multipart 解析、單任務併發拒絕、取消、以 mock pipeline 驗證 3 個 adapter 參數／遮罩合成、拒絕錯誤输出尺寸，以及各平台 Torch 選擇。另有三個真實權重 CPU 推論 PNG／JSON 與 Linux 安裝啟動檢查於 `qa/`。`VALIDATION.json` 分開記錄測試範圍，`qa/repair-log-v5.json` 保留發現的錯誤、修正與限制。

## 核對來源

- SD-Turbo 模型卡與 img2img 條件：https://huggingface.co/stabilityai/sd-turbo
- InstructPix2Pix 作者模型：https://huggingface.co/timbrooks/instruct-pix2pix
- SD Inpainting 鏡像與授權：https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-inpainting
- Diffusers inpainting：https://huggingface.co/docs/diffusers/using-diffusers/inpaint
- Diffusers callbacks：https://huggingface.co/docs/diffusers/using-diffusers/callback
- PyTorch 2.2 官方公告（Intel macOS 最後版本）：https://pytorch.org/blog/pytorch2-2/
- PyTorch 官方舊版本安裝：https://pytorch.org/get-started/previous-versions/
