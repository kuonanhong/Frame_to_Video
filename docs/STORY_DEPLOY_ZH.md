> 歷史資料：此文件記錄 Story 3.0。Story 4 的功能與本輪測試請以根目錄「使用與部署說明.html」及「VALIDATION_V4.html」為準。

# FRAME Story Studio：操作與 GitHub Pages 部署

版本日期：2026-10-09。本文件適用於新增的 `story/` 分鏡工作台。上傳套件原有的 CPU 物件辨識／規則動畫工具仍保留於 `edge/`；原版雲端 AI 介面與 Python 後端保留作為原始參考，並不因部署到 Pages 而取得雲端推論能力。

## 1. 先在本機開啟

解壓縮後，進入同時包含 `index.html`、`story/`、`edge/`、`docs/` 的 `FRAME_AI_Studio` 資料夾。請用 HTTP 開啟，避免直接雙擊 HTML 所造成的模組、WASM、Worker 與離線快取限制。

macOS／Linux：

```bash
cd "/你的解壓縮路徑/FRAME_AI_Studio"
python3 -m http.server 8080 --bind 127.0.0.1
```

Windows PowerShell（已安裝 Python）：

```powershell
cd "C:\你的解壓縮路徑\FRAME_AI_Studio"
py -m http.server 8080 --bind 127.0.0.1
```

開啟 `http://127.0.0.1:8080/`（`/story/` 亦為入口）。停止本機網站：回到終端機按 `Ctrl+C`。手機使用正式 GitHub Pages 的 HTTPS 網址較合適；一般區域網路 HTTP 可能無法使用麥克風、定位或離線安裝功能。

## 2. 圖片／影片變成有聲故事

1. 先按「載入示範」確認介面、分鏡與預覽正常，再加入自己的 JPG、PNG、WebP 圖片或瀏覽器可解碼的影片。可逐批加入，最多 20 個分鏡。
2. 選取分鏡，修改名稱、秒數、運鏡及轉場；影片分鏡可指定起始／結束秒數。重要人物與文字放在畫面中央，因為輸出比例不同時會裁切部分邊緣。
3. 在「敘事／旁白文字」輸入故事。可先辨識常見物件，再選 CPU AI 敘事；模型依物件標籤和你寫的描述產生文字，不具備通用視覺問答能力。檢查內容是否符合照片；細小模型可能重複或編造內容，文字仍可直接編輯。
4. 需要可合成到影片的聲音，選「生成可匯出配音」、上傳旁白錄音，或用麥克風自行錄音。系統語音試聽僅用來聽文字，不能可靠地擷取為影片音軌。語速、預設音色可以選擇；音色沒有可靠的年齡、人格或情緒保證。
5. 調整亮度、對比、飽和度與暖色光；這些是濾鏡及畫面後製，不是真實三維場景重新打光。
6. 可輸入字幕、加入自己的配樂或使用內建原創輕柔音樂。檢查配樂音量，避免遮住旁白。
7. 先預覽，確認順序、聲音與轉場，再匯出。手機從 360p、12 fps 開始；較快的電腦可試 720p、24 fps。錄製時保持分頁在前景，不要鎖定螢幕。
8. 下載影片、SRT 字幕及需要的 WAV 旁白。用「儲存專案」保留分鏡設定和素材，以後再開啟；這不是雲端帳號同步服務。

影片格式會依 `MediaRecorder.isTypeSupported()` 選擇瀏覽器支援的 MP4 或 WebM。不能藉改副檔名完成轉檔。若裝置不能錄影，請保留專案，在支援錄製的現代瀏覽器中重新開啟。大型原始影片解碼、長敘事推論與高解析度錄製可能超過手機記憶體。

本機有 FFmpeg、需要常見 H.264 MP4 時，可另行轉檔（FFmpeg 並非網頁必需依賴）：

```bash
ffmpeg -i input.webm -c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart output.mp4
```

## 3. 多語、地圖與聲音的實際範圍

工作台核心介面有 22 種語言：繁體中文、簡體中文、英語、日語、韓語、法語、德語、西班牙語、葡萄牙語、義大利語、俄語、波蘭語、捷克語、芬蘭語、瑞典語、阿拉伯語、泰語、越南語、馬來語、印尼語、菲律賓語、印地語。阿拉伯語採由右至左版面。這不是全部亞洲、歐洲或全世界語言；翻譯尚未經各語母語編輯全面審校。

預設依瀏覽器的語言偏好選擇介面，手動選擇會保存在此瀏覽器。語言偏好不是實際國籍或目前所在地；例如人在日本也可能使用繁體中文瀏覽器。模型可生成的語言和介面可顯示的語言是不同能力，請看 `STORY_CAPABILITIES.md` 和模型說明。

不需要 Google Maps 判斷語系。只有你按定位按鈕後，瀏覽器才會要求定位授權；地圖用一般 Google Maps 連結開啟，不需要在網頁埋 API key。定位失敗或不同意時，仍可照常製作影片。開啟 Google Maps 需要連線，且會依你的選擇將該地點送往 Google 地圖；它不是離線製片必需功能。

上傳某人的聲音檔會直接作為旁白素材使用，並不訓練或克隆該人的音色。若要使用別人的錄音，請取得其使用同意。瀏覽器系統語音清單取決於作業系統；部分聲音可能依賴遠端服務，不能一概稱為離線聲庫。

## 4. 準備離線使用

第一次須從本機網站或 HTTPS 網站載入介面、推論程式與模型。先按「準備離線使用」，等待介面報告完成，再測試重新整理和實際推論。不曾載入／未快取的模型，無法在斷線後憑空取得。

快取屬於瀏覽器儲存空間，並非永久保證；無痕視窗、清除網站資料、系統儲存不足或瀏覽器回收空間，可能刪除模型。不同瀏覽器及不同網站位址各有自己的快取。不要把工作台安裝到一個網址後，期待另一個網址自動共用模型。

離線製片可以使用已載入的素材與模型；Google Maps、需要網路的系統語音或原版雲端模型服務仍需要網路。專案與匯出影片請另外下載保存。

## 5. 上傳既有 GitHub 儲存庫

上傳是 **`git push`**；`git pull` 是取得遠端更新。以下範例使用你的 `Frame_to_Video` 儲存庫。先確認解壓縮路徑，並把第一行換成你真正的本機路徑。這些指令不會刪除遠端歷史。

```bash
FRAME_PACKAGE_DIR="/你的解壓縮路徑/FRAME_AI_Studio"
git clone https://github.com/kuonanhong/Frame_to_Video.git
cd Frame_to_Video
git switch main
git pull --ff-only origin main
rsync -av --exclude='.git' --exclude='node_modules' --exclude='*.zip' "$FRAME_PACKAGE_DIR/" ./
touch .nojekyll
git status --short
git diff --stat
git add .
git commit -m "Add local CPU storyboard, narration, audio and video editor"
git push origin main
```

若儲存庫已經在本機，不要再 `git clone` 到原資料夾裡；改成 `cd` 進入既有儲存庫，從 `git switch main` 開始。若目前分支不是 `main`，請先以 `git branch --show-current` 確認，再對應調整。遇到 `git pull --ff-only` 拒絕更新時，先保存本機修改並處理差異，不要直接使用 `--force`。

macOS 通常已有 `rsync`；Windows 可用 Git Bash 搭配檔案總管，把解壓縮的專案內容複製進儲存庫，再執行 `git status`、`git add`、`git commit`、`git push`。不要把下載的 ZIP 當作網站唯一檔案上傳；網站需要 ZIP 裡的實際資料夾。

GitHub 不能使用帳號密碼做 Git HTTPS 推送認證。可使用 GitHub Desktop 的登入或你自己保管的 Personal Access Token；不要把 token 寫入 HTML、JavaScript、公開儲存庫或模型 URL。

## 6. 設定 Pages

1. 打開 GitHub 儲存庫 → **Settings → Pages**。
2. 使用 **Deploy from a branch**，選 **main**、**/(root)**；已有 Actions 工作流程時，請以該工作流程實際發布的資料夾為準。
3. 等待部署完成，開啟 `https://kuonanhong.github.io/Frame_to_Video/story/`。主頁若使用套件提供的根入口，也能連入新工作台。
4. 用無痕視窗確認新檔案已發布，再測試示例、生成敘事、可匯出配音、預覽與影片下載。
5. 手機再測一次；更新後若仍看到舊介面，先清除工作台離線快取，再重新整理並準備模型。

不要只上傳 `story/index.html`。必須保留 `story/` 的程式、Worker、WASM、模型、語系及其相對路徑，也須保留程式實際引用的 `edge/` 物件辨識檔案。以完整附件包為準，不要重新命名已由程式引用的權重分片。`node_modules/`、Python 虛擬環境、個人的圖片／錄音與匯出影片不必發布。

GitHub Pages 提供靜態 HTML、CSS、JavaScript、WASM 與模型檔案；**不能在伺服器上執行 Python、CUDA、FFmpeg 指令或原版 `backend/`**。本工作台把相應工作放在訪客瀏覽器執行，部署網站不等於免費取得雲端 GPU。

## 7. 大檔與多人使用

截至 2026-10-09 查核的 GitHub 官方文件：

| 項目 | 官方限制／建議 | 本套件的操作 |
|---|---|---|
| 一般 Git 單一檔案 | 超過 50 MiB 有警告；超過 100 MiB 拒收 | 使用實際模型分片；所有一般 Git 單檔須低於上限。 |
| GitHub 網頁上傳 | 每檔不超過 25 MiB | 模型用 Git CLI／GitHub Desktop 推送，不必靠網頁拖放。 |
| 已發布 Pages 網站 | 不超過 1 GB | 不上傳不必要的原始素材、生成影片、虛擬環境與大型後端模型。 |
| Pages 來源儲存庫 | 建議不超過 1 GB | 控制模型與歷史版本；不要反覆累積大型權重。 |
| Pages 流量 | 每月 100 GB 軟性頻寬限額 | 初次模型下載仍消耗網站流量；離線快取降低重複下載。 |
| Git LFS | 官方明列不能用於 Pages 網站 | 不將 Pages 必需權重改成 LFS 指標檔。 |

在提交前找出超過 100 MiB 的檔案：

```bash
python3 - <<'PY'
from pathlib import Path
for p in Path('.').rglob('*'):
    if p.is_file() and '.git' not in p.parts and 'node_modules' not in p.parts:
        if p.stat().st_size > 100 * 1024 * 1024:
            print(f'{p.stat().st_size / 1024 / 1024:.1f} MiB  {p}')
PY
```

超過上限時不要用 `git lfs track '*.onnx'` 將問題隱藏：Pages 可能只發布 LFS 指標，模型解析就會失敗。大型模型必須使用推論引擎真正支援的分片、縮小／量化版本，或另外提供合法的模型下載來源及離線導入流程；不能任意把一個 ONNX 二進位切成數份就期待 ONNX Runtime 自動理解。

訪客各自在自己的裝置推論，彼此不共用一個 CPU 佇列；但仍共同下載網站與模型。若每位新訪客下載 300 MB，1,000 位首次訪客就約 300 GB，已高於上述軟性月額度。不能保證十萬人同時使用、永不當機、永遠零延遲或無限免費流量。

## 8. 問題排查

| 現象 | 先做什麼 |
|---|---|
| 載入模型失敗 | 確認使用 HTTP／HTTPS，所有 WASM、Worker、模型檔及大小寫完整；檢查是否上傳到正確相對路徑。 |
| 雲端失敗、本機正常 | 開瀏覽器開發工具的 Network，找 404、LFS 指標或被當 HTML 回傳的模型；確認 Pages 發布根目錄。 |
| 手機卡住／記憶體不足 | 先不載入敘事模型，以手動文字、上傳錄音、較少素材、360p、12 fps 製片。 |
| 敘事答非所問 | 小模型並非看圖推理模型；改清楚的英文短描述、刪除不實內容或直接編輯旁白。 |
| 系統聲音能聽見但匯出無聲 | 系統語音只是試聽；改用可匯出配音、錄音檔或麥克風錄音。 |
| 配音長於分鏡 | 檢查自動延長後的總時長，或縮短文字／調整語速。 |
| 定位被拒絕 | 不影響影片功能；使用一般地圖連結，或在 HTTPS 網站重新授權。 |
| WebM 不能在特定播放器播放 | 改支援該格式的播放器、裝置支援的 MP4，或本機 FFmpeg 轉檔。 |
| 更新後仍是舊程式 | 清除工作台快取、重新整理；再在無痕視窗確認部署版本。 |

## 官方參考

- [GitHub Pages 的用途與限制](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [GitHub 單檔上限](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
- [Git LFS 與 Pages 限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)
- [瀏覽器語言偏好](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/languages)
- [定位授權及 HTTPS](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition)
- [瀏覽器提供的語音清單](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis/getVoices)
- [系統語音是否為本機服務](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisVoice/localService)
- [MediaRecorder 格式支援](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/isTypeSupported_static)


## 字型與裝置工作副本

另附 jf open 粉圓 OFL 1.1 字型（約4 MB），讓沒有中文系統字型的裝置也能顯示常用繁體中文字及字幕；其他語言仍依裝置字型fallback。照片工作副本最大邊手機1280、桌面2048像素，手機總照片像素約12MP、桌面40MP；這是保守資源限制，不是精確硬體測量。
