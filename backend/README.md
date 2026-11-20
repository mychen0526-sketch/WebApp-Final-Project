# 後端（FastAPI）

把「輸入目標 → AI 生成 → 編輯 → 本人審核 → 發布到 Threads / IG」這條流程的狀態、資料、生成與發布放在後端。規格依 Milestone 1 與 Notion 開發規格書，並加上 README 裡的設定、敏感詞檢查與排程。

| 層面 | 技術 |
| --- | --- |
| API | Python 3.12、FastAPI（RESTful） |
| 資料庫／登入／圖片 | Supabase：PostgreSQL、Auth（JWT）、Storage（公開 bucket `post-images`） |
| AI | 文字：TAIWAN AI RAP（國網中心，OpenAI 相容 API，預設 `gemma-4-31B-it`）；圖卡底圖：fal.ai 的 FLUX.1 [schnell]（約 US$0.003／張） |
| 社群 | Threads API、Instagram API with Instagram Login、LinkedIn Posts API（個人動態） |
| 新聞搜尋 | Tavily Search（正式）或 Bing News RSS（免金鑰示範）；圖片取自原始媒體的 `og:image` |
| 部署 | Dockerfile |

## 快速開始（不需要任何金鑰）

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # 預設：記憶體資料庫、模擬 AI、模擬發布、開發用登入
.venv\Scripts\uvicorn app.main:app --reload
```

- API 文件：http://127.0.0.1:8000/docs
- 沒設定 Supabase 時，用 `X-Dev-User: 任意字串` 代替登入（`DEV_AUTH=true`）。資料存在記憶體，重開就清空。
- 測試：`.venv\Scripts\python -m pytest`

## 接上真的服務

1. **Supabase**：建立專案，在 SQL Editor 依序執行 `supabase/migrations/0001_init.sql`（建 6 張表、RLS、`post-images` bucket）、`0002_templates.sql`（圖片模板）、`0003_versions.sql`、`0004_linkedin_references.sql`（LinkedIn 與新聞圖片）。把 Project URL 和 service role key 填進 `.env` 的 `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`。專案若仍用舊版 HS256 JWT secret，再填 `SUPABASE_JWT_SECRET`；新專案走 JWKS，不必填。
2. **文字（TAIWAN AI RAP）**：在 https://portal.genai.nchc.org.tw 建立 API Key，填 `RAP_API_KEY`。`RAP_BASE_URL` 預設 `https://portal.genai.nchc.org.tw/api/v1`，模型用 `RAP_TEXT_MODEL` 換（可用的 ID 查 `GET {RAP_BASE_URL}/models`）。沒填金鑰就用模擬文案。
3. **圖卡底圖（fal.ai）**：填 `FAL_API_KEY`。底圖不含文字，文字由前端疊上，所以用最便宜的 FLUX.1 [schnell] 就夠。FLUX 只懂英文，會先請 RAP 把主題寫成一句英文畫面描述（`prompts/c_scene.txt`），再套 `prompts/c_image_flux.txt`。沒填金鑰就用漸層底圖。`/health` 的 `ai`、`image` 欄位會顯示實際使用的服務。
4. **Threads／Instagram**：在 Meta 開發者後台建立 App，填 `THREADS_APP_ID/SECRET`、`INSTAGRAM_APP_ID/SECRET`，並把 `.env` 裡的 redirect URI 加進 App 設定。然後設 `MOCK_PUBLISH=false`。注意：平台要從**公開網址**抓圖，所以真的發布一定要用 Supabase Storage，記憶體模式的圖片網址平台抓不到。
5. **LinkedIn**：在 https://www.linkedin.com/developers/apps 建立 App，加入「Sign In with LinkedIn using OpenID Connect」與「Share on LinkedIn」兩個 Product，把 `LINKEDIN_REDIRECT_URI` 加到 Auth 頁的 Authorized redirect URLs，填 `LINKEDIN_CLIENT_ID/SECRET`。發到授權者的個人動態（scope：`openid profile w_member_social`）；發到公司專頁需要另外申請 Community Management API。LinkedIn 不從網址抓圖，後端會下載匯出的圖卡再上傳（Images API）。token 60 天到期，到期要重新連結。`LINKEDIN_API_VERSION` 是 `LinkedIn-Version` 標頭（YYYYMM），LinkedIn 約一年淘汰舊版，過期時改成較新的月份。
6. **新聞搜尋與真實圖片**：預設 `SEARCH_BACKEND=auto`：有 `TAVILY_API_KEY` 用 Tavily，沒有就用 Bing News RSS（免金鑰，但條款只允許顯示結果，公開使用請換 Tavily）。每則新聞都會讀原文頁的 `og:image` 與媒體名稱；所有對外抓取都經過 `services/webfetch.py`（擋內網位址、限制大小）。圖片用法：`photo` 原圖當底圖並在圖卡標註「圖片來源」；`blend` 用 fal 的 FLUX [dev] image-to-image 依品牌配色重繪（`FAL_BLEND_MODEL`、`FAL_BLEND_STRENGTH`），沒有 fal 金鑰時退回原圖。新聞照片多有著作權，審核頁會提醒確認授權。

前端登入：用 `@supabase/supabase-js` 登入後，把 `session.access_token` 放在每個請求的 `Authorization: Bearer <token>`。

## 狀態機

```text
generating ─成功→ editing ─送審→ pending_review ─核准→ approved ─發布→ publishing ─→ published
    │ 失敗              ↑  ↑ 退回 ─────────┘          │  │ 排程                     ├→ partially_published ─重試→ publishing
    ↓                   │  └──── 修改（需重審）───────┘  ↓                          └→ publish_failed ─重試→ publishing
generation_failed ─重試→┘                        scheduled ─取消→ approved            publish_failed ─reopen→ editing
                                                     └─到時間→ publishing（排程器）
```

| 動作 | API | 允許的狀態 | 之後 |
| --- | --- | --- | --- |
| 重新生成 | `POST /api/posts/{id}/generate` | editing、generation_failed | generating |
| 儲存編輯 | `PATCH /api/posts/{id}` | editing、approved | editing（approved 會被打回，必須重審） |
| 刪除 | `DELETE /api/posts/{id}` | editing、generation_failed | — |
| 送審 | `POST /api/posts/{id}/submit` | editing | pending_review |
| 退回 | `POST /api/posts/{id}/reject`（或 `/return`） | pending_review、approved | editing |
| 核准 | `POST /api/posts/{id}/approve` | pending_review | approved |
| 發布 | `POST /api/posts/{id}/publish` | approved | publishing → 結果 |
| 重試 | `POST /api/posts/{id}/retry` | partially_published、publish_failed | publishing（只發失敗的平台） |
| 排程 | `POST /api/posts/{id}/schedule` | approved | scheduled |
| 取消排程 | `POST /api/posts/{id}/cancel-schedule` | scheduled | approved |
| 重新編輯 | `POST /api/posts/{id}/reopen` | publish_failed | editing |

其他組合一律回 **409**。狀態更新用「比對後再寫入」，連按兩次發布時第二次也是 409。

後端自己守住的規則：

- **送審**：至少一個平台；平台帳號已綁定且未過期；Threads 文案 ≤ 500 字；IG 一定要有圖。
- **核准**：`readConfirmed` 和 `rightsConfirmed` 都要是 `true`。
- **發布和排程前**：用使用者的敏感詞再掃一次標題、兩版文案與圖上文字，有命中回 422 並列出詞。
- **生成**：失敗或超過 10 分鐘沒完成，一律變成 `generation_failed`，不會卡在生成中。

## API 一覽

所有 `/api` 路徑都要帶 JWT（OAuth callback 除外）。錯誤格式統一為 `{"code", "message", "detail"}`。

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/health` | 目前用的是哪種資料庫、AI、發布模式 |
| POST | `/api/candidates` | `{goal, tone?}` → 3 個提示詞候選，不存檔 |
| POST | `/api/research` | `{query, limit?}` → `{backend, results: [{title, url, source, published, summary, image_url}]}`，不存檔 |
| POST | `/api/posts` | `{goal, tone?, audience?, candidates, selected, layout?, style?, visual_style?, template_id?, reference?, image_mode?}` 建立並在背景生成，回 202 |
| GET | `/api/posts?status=` | 貼文列表，依更新時間排序 |
| GET | `/api/posts/{id}` | 單篇，含 `images` 與 `publications`（P6 輪詢用） |
| POST | `/api/posts/{id}/images` | multipart：`file`（PNG/JPEG ≤ 8MB）、`source`=`uploaded`／`exported` |
| GET | `/api/templates` | 使用者自己的圖片模板 |
| POST | `/api/templates` | multipart：`file`（PNG/JPEG ≤ 8MB，建議 1080×1080）、`name` |
| DELETE | `/api/templates/{id}` | 從清單移除；已使用它的貼文照常顯示與發布 |
| POST | `/api/posts/{id}/feedback` | `{rating: like｜neutral｜dislike}` |
| GET／PUT | `/api/settings` | 品牌名稱、預設語氣、受眾、敏感詞 |
| POST | `/api/safety/scan` | `{title, text}` → `{ok, detected, claims}` |
| GET | `/api/accounts` | 各平台是否已綁定、是否過期（不回傳 token） |
| GET | `/api/accounts/{platform}/connect` | 回傳官方授權網址 `{url}`；模擬模式直接綁定示範帳號 |
| DELETE | `/api/accounts/{platform}` | 解除綁定 |

生成與發布在背景執行，API 先回 202，前端輪詢 `GET /api/posts/{id}` 直到狀態改變。

`canvas_json` 格式（1080×1080 畫布）：

```json
{
  "layout": "top", "style": 0, "visual_style": "abstract", "colorScheme": "科技深藍",
  "image": {"url": "...", "x": 0, "y": 0, "width": 1080, "height": 1080},
  "texts": [{"type": "text", "textType": "headline", "text": "OpenAI 新公告",
             "position": {"x": 540, "y": 120}, "fontSize": 80, "fontFamily": "Noto Sans TC",
             "fontWeight": "900", "color": "#FFFFFF", "alignment": "center"}]
}
```

**新聞圖片**：建立或重新生成時帶 `reference`（`/api/research` 的一筆結果）與 `image_mode`（`photo`／`blend`／`ai`）。文案會引用它並在 LinkedIn（與放得下時的 Threads）文末附原文連結；圖片下載後裁成 1080² JPEG 存為 `post_images.source = reference`。`canvas_json` 會多 `reference`、`image_mode`、`credit`（圖卡上的出處）、`image_note`（圖片不能用時改用 AI 底圖的原因）。重新生成不帶 `reference` 沿用原本的，帶 `null` 移除。模板優先於新聞圖片。

**圖片模板**：建立或重新生成時帶 `template_id`，就不呼叫 AI 產底圖，改用該模板當背景（`post_images.source = template`，`canvas_json` 會多 `template_id`）。重新生成不帶 `template_id` 沿用原模板，帶 `null` 改回 AI 底圖。別人的模板一律 404。

發布用的圖：優先用最新的 `exported`（前端把畫布含文字匯出的 PNG），沒有才依序用上傳、模板、生成的底圖。生成的底圖不含文字，所以正式發布前，前端應先匯出並上傳 `exported`。

## 程式結構

```text
app/
  main.py            建立 FastAPI、CORS、啟動排程器
  config.py          環境變數
  auth.py            驗證 Supabase JWT
  state.py           狀態機（唯一的規則來源）
  routers/           posts、candidates、research、accounts、settings、templates
  repo/              supabase_repo（正式）、memory_repo（測試與離線開發）
  services/
    prompts/         Prompt A～D，一個 prompt 一個檔案
    ai.py            TAIWAN AI RAP 文字生成與模擬 AI
    images.py        fal.ai FLUX 底圖與 image-to-image 融合
    research.py      新聞搜尋（Tavily／Bing RSS／mock）、og:image、圖片正規化
    webfetch.py      對外抓取（擋內網、限大小、逐跳檢查轉址）
    design.py        4 種版型與 4 種配色（與前端 STYLES 對應）
    generation.py    生成流程
    publishing.py    分平台發布與結果
    scheduler.py     排程發布、清掉卡住的生成
    platforms/       threads、instagram、linkedin、mock
supabase/migrations/0001_init.sql
tests/
```

## 尚未處理

- 長效 token 約 60 天到期，目前不會自動續期；到期後要在 P2 重新連結。
- `access_token` 以明文存在 `social_accounts`（RLS 不開放讀取）；用 Supabase Vault 加密列為延伸。
- 前端還沒接上這些 API。
