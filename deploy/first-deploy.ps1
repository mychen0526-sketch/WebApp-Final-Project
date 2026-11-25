# First AWS deploy, steps 1-4 of deploy\README.md, without the interactive `sam deploy --guided`.
#   powershell -ExecutionPolicy Bypass -File deploy\first-deploy.ps1 [-Region ap-northeast-1]
# Safe to re-run: existing samconfig.toml / .env.production files are kept as they are.
# Secrets are copied from backend\.env on this machine and never printed.
param(
    [string]$Region,
    [string]$StackName = "social-studio",
    [string]$FunctionName = "social-api",
    [string]$EnvParameterName = "/social-api/env"
)
$ErrorActionPreference = "Stop"
$deployDir = $PSScriptRoot
$root = Split-Path $deployDir -Parent
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
$utf8 = New-Object System.Text.UTF8Encoding $false

function Step([string]$Label, [scriptblock]$Command) {
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit code $LASTEXITCODE)" }
}
function Out([string]$Key) {
    $v = aws cloudformation describe-stacks --stack-name $StackName `
        --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
    if ($LASTEXITCODE -ne 0 -or -not $v -or $v -eq "None") { throw "Stack output $Key not found" }
    return $v.Trim()
}

foreach ($c in "aws", "sam", "npm") {
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { throw "$c not found - install it first (see deploy\README.md step 0)." }
}
if (-not (Test-Path $python)) { throw "backend\.venv is missing." }
Step "AWS login check" { aws sts get-caller-identity --query Arn --output text }

if (-not $Region) { $Region = aws configure get region; if ($Region) { $Region = $Region.Trim() } }
if (-not $Region) { throw "No AWS region set. Re-run with -Region <region of / nearest to your Supabase project>, e.g. -Region ap-northeast-1" }
$env:AWS_DEFAULT_REGION = $Region
$env:AWS_REGION = $Region
Write-Host "Region: $Region" -ForegroundColor Yellow

# ---- 1. build backend package
Step "build Lambda package" { & $python (Join-Path $deployDir "build.py") }

# ---- 2. deploy the stack (answers of README step 2, saved to samconfig.toml)
$samcfg = Join-Path $deployDir "samconfig.toml"
if (-not (Test-Path $samcfg)) {
    $cfg = @"
version = 0.1
[default.deploy.parameters]
stack_name = "$StackName"
resolve_s3 = true
s3_prefix = "$StackName"
region = "$Region"
confirm_changeset = true
disable_rollback = false
capabilities = "CAPABILITY_IAM"
parameter_overrides = "FunctionName=\"$FunctionName\" EnvParameterName=\"$EnvParameterName\""
"@
    [IO.File]::WriteAllText($samcfg, $cfg, $utf8)
}
Push-Location $deployDir
try { Step "sam deploy (answer y to deploy the changeset)" { sam deploy --no-fail-on-empty-changeset } }
finally { Pop-Location }

$api = (Out "ApiUrl").TrimEnd("/")
$site = (Out "SiteUrl").TrimEnd("/")
Write-Host "ApiUrl : $api" -ForegroundColor Green
Write-Host "SiteUrl: $site" -ForegroundColor Green

# ---- 3. backend settings -> SSM
$envProd = Join-Path $deployDir ".env.production"
if (-not (Test-Path $envProd)) {
    Write-Host "==> writing deploy\.env.production from backend\.env" -ForegroundColor Cyan
    $dev = [ordered]@{}
    foreach ($l in Get-Content (Join-Path $root "backend\.env")) {
        if ($l -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { $dev[$matches[1]] = $matches[2].Trim() }
    }
    # keep the dev APP_SECRET when it is strong: tokens already saved in Supabase are encrypted with it
    $secret = $dev["APP_SECRET"]
    $plain = if ($secret) { $secret.Trim('"').Trim("'") } else { "" }
    if ($plain.Length -lt 32 -or $plain -match "change-me") {
        $secret = (& $python -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
        Write-Host "   APP_SECRET in backend\.env is weak: generated a new one (reconnect social accounts after deploy)" -ForegroundColor Yellow
    }
    $override = @{
        MOCK_AI = "false"; MOCK_PUBLISH = "false"; DEV_AUTH = "false"; APP_SECRET = $secret
        FRONTEND_URL = $site; PUBLIC_BASE_URL = $api; CORS_ORIGINS = "[`"$site`"]"
        THREADS_REDIRECT_URI = "$api/api/accounts/threads/callback"
        INSTAGRAM_REDIRECT_URI = "$api/api/accounts/instagram/callback"
        LINKEDIN_REDIRECT_URI = "$api/api/accounts/linkedin/callback"
    }
    $skip = @("SCHEDULER_ENABLED", "SCHEDULER_INTERVAL_SECONDS")
    $seen = @{}
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($l in Get-Content (Join-Path $deployDir "env.production.example")) {
        if ($l -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $k = $matches[1]; $v = $matches[2]; $seen[$k] = $true
            if ($override.ContainsKey($k)) { $v = $override[$k] }
            elseif ($dev.Contains($k) -and $dev[$k] -ne "") { $v = $dev[$k] }
            $out.Add("$k=" + $v.Replace("<API>", $api).Replace("<SITE>", $site))
        } else { $out.Add($l) }
    }
    $extra = $dev.Keys | Where-Object { -not $seen.ContainsKey($_) -and $skip -notcontains $_ }
    if ($extra) { $out.Add(""); $out.Add("# from backend\.env"); foreach ($k in $extra) { $out.Add("$k=" + $dev[$k]) } }
    [IO.File]::WriteAllLines($envProd, $out, $utf8)
}
Step "upload settings to SSM" {
    aws ssm put-parameter --name $EnvParameterName --type SecureString --overwrite --value "file://$envProd" --query Version --output text
}
Step "reload backend settings" {
    aws lambda update-function-configuration --function-name $FunctionName --description "env $(Get-Date -Format s)" --query LastUpdateStatus --output text
}
Step "wait for update" { aws lambda wait function-updated --function-name $FunctionName }
Write-Host "==> health check" -ForegroundColor Cyan
$health = $null
for ($i = 0; $i -lt 3 -and -not $health; $i++) {
    try { $health = Invoke-RestMethod -Uri "$api/health" -TimeoutSec 60 } catch { Start-Sleep 5 }
}
if (-not $health) { throw "Health check failed. Logs: aws logs tail /aws/lambda/$FunctionName --since 10m" }
Write-Host ($health | ConvertTo-Json -Compress) -ForegroundColor Green

# ---- 4. frontend
$feEnv = Join-Path $root "frontend\.env.production"
if (-not (Test-Path $feEnv)) {
    $fe = foreach ($l in Get-Content (Join-Path $root "frontend\.env.local")) {
        if ($l -match '^VITE_API_BASE=') { "VITE_API_BASE=$api" } else { $l }
    }
    if (-not ($fe -match '^VITE_API_BASE=')) { $fe = @("VITE_API_BASE=$api") + $fe }
    [IO.File]::WriteAllLines($feEnv, [string[]]$fe, $utf8)
}
& (Join-Path $deployDir "deploy.ps1") -Frontend -StackName $StackName

Write-Host ""
Write-Host "Remaining manual step (README step 5):" -ForegroundColor Yellow
Write-Host "  Supabase > Authentication > URL Configuration: Site URL = $site ; Redirect URLs += $site/**"
Write-Host "  Meta / LinkedIn developer consoles, add redirect URIs:"
Write-Host "    $api/api/accounts/threads/callback"
Write-Host "    $api/api/accounts/instagram/callback"
Write-Host "    $api/api/accounts/linkedin/callback"
