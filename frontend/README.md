# Orbit Studio（前端）

React + Vite。已接上 `backend/` 的 FastAPI：登入用 Supabase Auth，所有貼文、設定、平台帳號、圖片模板都走後端 API。

## 啟動

```powershell
cd frontend
npm install          # 第一次才需要
npm run dev          # http://127.0.0.1:5173
```

設定在 `.env.local`（範本見 `.env.example`）：

| 變數 | 用途 |
| --- | --- |
| `VITE_API_BASE` | 後端網址，預設 `http://127.0.0.1:8000` |
| `VITE_SUPABASE_URL` | Supabase 專案網址；留空 = 開發模式（不用登入，後端要 `DEV_AUTH=true` 且不設 `SUPABASE_URL`） |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Supabase 的 publishable key（可公開） |

## 哪些是真的、哪些是示範

| 功能 | 狀態 |
| --- | --- |
| 登入、AI 三個方向、生成文案與圖卡、重寫、系列 | 後端（AI RAP 文字、fal 圖片） |
| 編輯、存草稿、送審、核准、退回、發布、排程、重試 | 後端 |
| 發布用的圖 | 送審時把編輯器畫面匯出成 1080×1080 PNG 上傳（`exported`） |
| Threads / Instagram 連結 | 後端 OAuth（需要 ngrok） |
| 敏感詞、語氣、受眾、品牌名稱、圖片模板、回饋 | 後端 |
| X、Telegram | 只有預覽，未串接 |
| 趨勢情報中心（新聞來源） | 示範資料 |

## 程式結構

```text
src/lib/auth.js        Supabase 登入（純 fetch），token 自動續期
src/lib/api.js         後端 API client
src/lib/posts.js       後端貼文 ↔ 畫面資料的轉換、狀態中文
src/lib/exportCard.js  把圖卡畫成 PNG
src/App.jsx            所有動作（呼叫 API、輪詢生成與發布）
src/pages/             各頁面
```
