# 部署到 AWS（最低成本 Serverless）

```
瀏覽器 ──► CloudFront ──► S3（前端 dist）
   │
   └────► Lambda Function URL（串流模式）──► FastAPI（Lambda Web Adapter，arm64）
                     ▲                              │
EventBridge Scheduler（每分鐘 tick、每小時續期 token）  ├─► Supabase（資料庫、登入、圖片）
生成／發布：Lambda 非同步呼叫自己（已簽章）              └─► RAP、fal、Threads／IG／LinkedIn
```

不用 API Gateway、NAT、RDS、ECR、Secrets Manager，這些都是固定月費或比較貴的服務。所有秘密都放在一個 SSM SecureString 參數裡（標準參數免費）。

## 0. 事前準備（一次）

1. 開一個 AWS 帳號，建立 IAM 使用者或 IAM Identity Center 使用者（不要用 root），在本機執行 `aws configure`（或 `aws configure sso`）。
2. 安裝 [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) 和 [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)，**不需要 Docker**。
3. **區域選跟 Supabase 專案一樣或最近的**（例如 Supabase 在東京就用 `ap-northeast-1`）。每一次請求都會打到 Supabase，距離比 AWS 區域本身的價差更重要。
4. **先設預算警示**：Billing → Budgets → Create budget → 選 *Zero spend budget* 或月預算 5 USD，填自己的 email。
5. 在 Supabase SQL Editor 依序執行 `backend/supabase/migrations/0001` 到 `0005`。

以下指令都在專案根目錄，用 PowerShell 執行。

## 1. 打包後端

```powershell
backend\.venv\Scripts\python deploy\build.py
```

產出 `deploy\.build\lambda.zip`，大約 17 MB。打包時用 pip 直接下載 Linux arm64 套件，版本鎖定成 `backend\.venv` 裡已經通過測試的版本。

## 2. 第一次部署

```powershell
cd deploy
sam deploy --guided
```

問答照這樣填：

| 問題 | 填 |
| --- | --- |
| Stack Name | `social-studio` |
| AWS Region | 步驟 0.3 選的區域 |
| Parameter FunctionName／EnvParameterName | 直接 Enter（`social-api`、`/social-api/env`） |
| Confirm changes before deploy | `y` |
| Allow SAM CLI IAM role creation | `y` |
| Disable rollback | `n` |
| **Api Function Url has no authentication. Is this okay?** | `y`（驗證由 FastAPI 用 Supabase JWT 處理） |
| Save arguments to configuration file | `y`（存成 `samconfig.toml`，已被 git 忽略） |

完成後畫面會印出 Outputs。之後也可以用下面的指令再查一次：

```powershell
aws cloudformation describe-stacks --stack-name social-studio --query "Stacks[0].Outputs" --output table
```

記下 `ApiUrl`（例如 `https://abc.lambda-url.ap-northeast-1.on.aws/`）和 `SiteUrl`（例如 `https://d123.cloudfront.net`）。

> 這時候排程每分鐘會呼叫一次 Lambda，但 SSM 參數還不存在，所以 CloudWatch 會出現啟動失敗的紀錄。做完步驟 3 就會恢復正常。

## 3. 設定後端環境變數（SSM）

```powershell
copy env.production.example .env.production
```

把裡面的 `<API>` 換成 ApiUrl（**去掉結尾的 `/`**），`<SITE>` 換成 SiteUrl，再填入各個金鑰。`APP_SECRET` 和 `TOKEN_ENCRYPTION_KEY` 用檔案裡附的指令產生。`MOCK_PUBLISH=false` 時如果 `APP_SECRET` 太弱，後端會拒絕啟動。

```powershell
aws ssm put-parameter --name /social-api/env --type SecureString --overwrite --value file://.env.production
aws lambda update-function-configuration --function-name social-api --description "env $(Get-Date -Format s)"
```

第二行會讓還在執行中的 Lambda 實例重新讀取設定。以後每次修改 `.env.production`，這兩行都要再跑一次。

驗證：

```powershell
curl.exe <ApiUrl>health
```

應該回傳 `"database":"supabase"`、`"publish":"live"`。

## 4. 部署前端

建立 `frontend\.env.production`：

```
VITE_API_BASE=<API>
VITE_SUPABASE_URL=https://xxxx.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<Supabase publishable / anon key>
```

```powershell
cd ..\frontend
npm ci
npm run build
$bucket = aws cloudformation describe-stacks --stack-name social-studio --query "Stacks[0].Outputs[?OutputKey=='SiteBucketName'].OutputValue" --output text
$dist   = aws cloudformation describe-stacks --stack-name social-studio --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text
aws s3 sync dist "s3://$bucket" --delete --exclude index.html
aws s3 cp dist\index.html "s3://$bucket/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id $dist --paths "/index.html"
```

Vite 產出的 js 和 css 檔名帶有 hash，可以長期快取。只有 `index.html` 設成不快取，所以每次只需要讓它失效（每月前 1,000 個路徑免費）。

## 5. 外部服務設定

- **Supabase** → Authentication → URL Configuration：Site URL 填 `<SITE>`，Redirect URLs 加上 `<SITE>/**`。
- **Meta（Threads、Instagram）、LinkedIn 開發者後台**：Redirect URI 加上 `<API>/api/accounts/{threads|instagram|linkedin}/callback`，要和 `.env.production` 裡的值一模一樣。

## 之後更新

第一次部署（步驟 1–5）做完之後，都用 `deploy\deploy.ps1`：

| 改了什麼 | 做什麼 |
| --- | --- |
| 前後端都改 | `.\deploy\deploy.ps1`（先跑後端測試，再部署後端、前端） |
| 只改後端程式 | `.\deploy\deploy.ps1 -Backend` |
| 只改前端 | `.\deploy\deploy.ps1 -Frontend` |
| 後端設定（`deploy\.env.production`） | `.\deploy\deploy.ps1 -Env` |
| 看 log | `aws logs tail /aws/lambda/social-api --follow`（保留 7 天） |

選項可以組合（例如 `-Backend -Env`）。`-SkipTests` 跳過後端測試，`-SkipInstall` 跳過 `npm ci`，`-Yes` 部署後端時不詢問確認。後端部署完會自動做 `/health` 檢查。

## 在 Lambda 上的行為差異

- **背景工作**：生成和發布不會在同一個請求的背景執行，因為回應送出後 Lambda 就凍結了。改成用 `InvocationType=Event` 呼叫自己，事件用 `APP_SECRET` 簽章，見 `backend/app/jobs.py`。非同步重試設為 0，避免同一則貼文被發兩次。
- **排程**：`SCHEDULER_ENABLED=false`。改由 EventBridge 每分鐘送 `tick`（到點發布、清理卡住的生成和發布），每小時送 `refresh_tokens`。到點發布最多延遲約 1 分鐘。
- **生成串流**：生成在另一個 Lambda 實例執行，SSE 讀不到它記憶體裡的進度，所以**文案不會逐字出現**。串流每 2 秒查一次資料庫，完成後直接顯示結果。「停止」仍然有效：狀態會立刻改變，背景那次生成的結果會被丟棄。

## 每月成本估算（小流量）

| 項目 | 免費額度 | 預估 |
| --- | --- | --- |
| Lambda（arm64、512 MB） | 每月 100 萬次請求、40 萬 GB-秒，永久免費 | 每分鐘 tick 約 4.3 萬次＋使用量，0 元 |
| EventBridge Scheduler | 每月 1,400 萬次 | 0 元 |
| CloudFront | 每月 1 TB、1,000 萬次請求，永久免費 | 0 元 |
| S3（前端，幾 MB）、SAM 部署用的 bucket | | 低於 0.1 美元 |
| SSM 標準參數、CloudWatch Logs（保留 7 天） | 5 GB log | 0 元 |
| Supabase Free | | 0 元（tick 每分鐘查詢一次，專案不會因閒置被暫停） |

實際的花費主要來自 **fal 和 RAP 的 API 呼叫**，不是 AWS。
