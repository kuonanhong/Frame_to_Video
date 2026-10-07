# FRAME AI 影像工作室

完整網頁版工作台：圖片轉影片、影片再創作、文字生圖；22種語言、模型選擇與各工作流程的模型預設。介面參考 DeeVid 的創作功能，使用原創設計、原創示例與公開模型 API，沒有使用 DeeVid 的品牌、程式或付費 API。

## 開啟網頁

- 直接開啟 `FRAME_Standalone.html`：CSS、JavaScript、語系及示例圖片已全部內嵌。
- 一般網站：部署 `dist/` 整個資料夾，入口為 `dist/index.html`。各語言入口在 `dist/zh-Hant/`、`dist/en/` 等資料夾。
- 本機建議：`python -m http.server 8080 --directory dist`，瀏覽 `http://localhost:8080`。
- AI生成需要網路上的模型服務或自行執行的GPU後端。離線可開介面，但不能離線執行大型雲端模型。

## 操作

1. 選擇「圖片轉影片」「影片再創作」或「文字生圖」。
2. 上傳圖片／影片，或在圖片模式選擇原創示例。示例圖片不是生成好的影片。
3. 輸入畫面、動作或修改描述。模型通常對英文描述更穩定；網站翻譯介面，並不自動翻譯提示詞。
4. 選擇生成模型、影片秒數、比例、種子。可將模型設為這個工作流程的預設。
5. 開始生成，等待真正的模型佇列與結果。下載成果，或將生成圖片再用於圖片轉影片。

## 免費的範圍

| 執行方式 | 實際意義 |
|---|---|
| 免費公開試用 | 直接呼叫 Hugging Face 的公開 ZeroGPU Space。可能排隊、額度耗盡、要求登入或服務變更。匿名 API 不會因另開試用頁登入而自動取得該登入帳號額度。 |
| 自架模型 | 模型權重可依其授權下載，不向模型提供者支付每次生成費。仍需要自己的 GPU、電力及儲存空間。 |
| DeeVid | 作為功能參考；其免費額度是試用，不是無限免費影片生成。 |

網頁不會自動購買額度、不會使用付費API，不會把CSS動態或鏡頭平移冒充AI影片。公開模型額度不足時會顯示錯誤，並提供模型原始試用頁。連線設定可填入選填Hugging Face Token，以使用自己的免費帳號額度；Token不會寫入瀏覽器儲存或原始碼。免費服務不是本專案可保證的永久運算資源。

## 模型

| 工作流程 | 免費公開試用 | 自架預設 |
|---|---|---|
| 圖片轉影片 | Lightricks LTX Video Distilled、zerogpu-aoti Wan 2.2 Lightning | LTX Video0.9.5 2B、Wan2.2 TI2V5B |
| 影片再創作 | Lightricks LTX Video Distilled 的 video_to_video API | LTX Video0.9.5 2B，原片條件強度0.2–0.9 |
| 文字生圖 | Black Forest Labs FLUX.1 schnell | SD-Turbo，512×512、1step |

公開模型頁/API會變動，連接器集中於 `src/providers.js`。Wan公開版依來源圖片決定尺寸；SD-Turbo自架版固定512×512。這些模式的比例選單會停用。其餘實際輸出時長／尺寸以模型回傳為準。LTX公開版沒有可調來源保留程度，因此僅在自架影片再創作顯示此控制。

## 自架生成後端

參閱 `backend/README.md`。先安裝相容的PyTorch/CUDA與Python套件，再執行FastAPI。影片生成需要CUDA GPU；沒有GPU時會直接回報可理解的錯誤。輸出的影片為無聲短片；影片再創作使用原片開頭對應秒數，不保留原始音軌。模型首次使用自動從Hugging Face下載，通常需要多GB至數十GB磁碟；完整套件不包含大型權重。

網站右上「連線設定」填入後端網址及選填金鑰。後端金鑰只在這次頁面記憶體保存；網址與模型預設會保存在瀏覽器。公開網站連接HTTP本機端點可能受瀏覽器限制，建議用本機網頁或HTTPS後端。本機8080埠已在預設跨來源白名單；直接開啟單檔HTML連接自架後端時，須在FRAME_ALLOWED_ORIGINS明確加入`null`，或改用上方的本機HTTP伺服器。部署後的跨來源白名單要加入實際網站來源；不要將私密素材上傳至公開模型。

## 原始碼與重建

`dist/index.html` + `dist/assets/style.css` 是介面；`src/app.js` 管理操作；`src/providers.js` 管理API；`dist/assets/i18n.json`含22完整語系。所有第三方JavaScript已打包，執行介面不依賴CDN。

```sh
npm ci
npm run build
```

需要Chromium的介面測試：`npx playwright install chromium`，然後 `npm test`。可用 `FRAME_BROWSER_PATH` 指定現有Chromium。測試內的模擬API只用於驗證介面與通訊契約，不會出現在產品中。

支援繁中、簡中、英文、日文、韓文、阿拉伯文、馬來文、泰文、越南文、印尼文、菲律賓文、德文、波蘭文、捷克文、葡萄牙文、芬蘭文、瑞典文、俄文、法文、西班牙文、義大利文、印地文。阿拉伯文為RTL。支援Windows、macOS、Linux、iPhone、Android與平板的現代瀏覽器；GPU推論在模型端進行，不要求手機安裝模型。

## 授權與來源

原創程式碼MIT。模型權重不是MIT；請遵守各模型授權及可接受用途。SD-Turbo須保留 **Powered by Stability AI**，適用Stability AI Community License；LTX0.9.5適用Open RAIL-M；Wan5B適用Apache2.0。未將模型權重重新分發，模型授權原文在 `backend/licenses/`。公開Space使用的其他版本/LoRA則依各提供者規則。

官方來源與2026-10-07查核記錄見 `SOURCES.md`。驗證結果見 `VALIDATION.md`。
