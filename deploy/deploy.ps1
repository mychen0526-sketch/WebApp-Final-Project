# Deploy to AWS: backend (Lambda), backend settings (SSM), and/or frontend (S3 + CloudFront).
#
#   .\deploy\deploy.ps1                 backend + frontend (tests run first)
#   .\deploy\deploy.ps1 -Backend        backend only
#   .\deploy\deploy.ps1 -Frontend       frontend only
#   .\deploy\deploy.ps1 -Env            upload deploy\.env.production to SSM and reload the backend
#   switches combine, e.g. -Backend -Env
#
#   -SkipTests     do not run the backend tests before deploying it
#   -SkipInstall   do not run npm ci (dependencies unchanged)
#   -Yes           deploy the backend without the "Deploy this changeset?" question
#
# The very first backend deploy must be `cd deploy; sam deploy --guided` (see deploy\README.md).
param(
    [switch]$Backend,
    [switch]$Frontend,
    [switch]$Env,
    [switch]$SkipTests,
    [switch]$SkipInstall,
    [switch]$Yes,
    [string]$StackName = "social-studio",
    [string]$EnvParameterName = "/social-api/env"
)

$ErrorActionPreference = "Stop"
if (-not ($Backend -or $Frontend -or $Env)) { $Backend = $true; $Frontend = $true }

$deployDir = $PSScriptRoot
$root = Split-Path $deployDir -Parent
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$python = Join-Path $backendDir ".venv\Scripts\python.exe"

function Invoke-Step([string]$Label, [scriptblock]$Command) {
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit code $LASTEXITCODE)" }
}

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "$Name not found. $Hint" }
}

function Get-StackOutput([string]$Key) {
    $value = aws cloudformation describe-stacks --stack-name $StackName `
        --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
    if ($LASTEXITCODE -ne 0 -or -not $value -or $value -eq "None") {
        throw "Could not read output '$Key' of stack '$StackName' (is it deployed, and is the AWS CLI logged in to the right region?)"
    }
    return $value.Trim()
}

function Get-FunctionName {
    $name = aws cloudformation describe-stack-resource --stack-name $StackName --logical-resource-id Api `
        --query "StackResourceDetail.PhysicalResourceId" --output text
    if ($LASTEXITCODE -ne 0 -or -not $name) { throw "Could not find the Lambda function of stack '$StackName'" }
    return $name.Trim()
}

Assert-Command aws "Install AWS CLI v2 first."

# ---------------------------------------------------------------- backend
if ($Backend) {
    Assert-Command sam "Install the AWS SAM CLI first."
    if (-not (Test-Path $python)) { throw "backend\.venv is missing. Create it and install backend\requirements.txt first." }
    if (-not (Test-Path (Join-Path $deployDir "samconfig.toml"))) {
        throw "deploy\samconfig.toml is missing: run the first deploy by hand with `cd deploy; sam deploy --guided`."
    }

    if (-not $SkipTests) {
        Push-Location $backendDir
        try { Invoke-Step "backend tests" { & $python -m pytest -q } } finally { Pop-Location }
    }
    Invoke-Step "build Lambda package" { & $python (Join-Path $deployDir "build.py") }

    Push-Location $deployDir
    try {
        $samArgs = @("deploy", "--no-fail-on-empty-changeset")
        if ($Yes) { $samArgs += "--no-confirm-changeset" }
        Invoke-Step "sam deploy" { sam @samArgs }
    }
    finally { Pop-Location }
}

# ---------------------------------------------------------------- backend settings
if ($Env) {
    $envFile = Join-Path $deployDir ".env.production"
    if (-not (Test-Path $envFile)) { throw "deploy\.env.production is missing. Copy deploy\env.production.example and fill it in." }
    Invoke-Step "upload settings to SSM" {
        aws ssm put-parameter --name $EnvParameterName --type SecureString --overwrite `
            --value "file://$envFile" --query "Version" --output text
    }
}
if ($Env -or $Backend) {
    if ($Env) {
        # warm Lambda instances keep the settings they started with; a config change replaces them
        $function = Get-FunctionName
        Invoke-Step "reload backend settings" {
            aws lambda update-function-configuration --function-name $function `
                --description "env $(Get-Date -Format s)" --query "LastUpdateStatus" --output text
        }
        Invoke-Step "wait for update" { aws lambda wait function-updated --function-name $function }
    }
    $api = Get-StackOutput "ApiUrl"
    Write-Host "==> health check" -ForegroundColor Cyan
    try {
        $health = Invoke-RestMethod -Uri ($api.TrimEnd("/") + "/health") -TimeoutSec 60
        Write-Host ($health | ConvertTo-Json -Compress)
        if (-not $health.ok) { throw "health check did not return ok" }
    }
    catch {
        throw "Backend health check failed: $($_.Exception.Message). Logs: aws logs tail /aws/lambda/$(Get-FunctionName) --since 10m"
    }
}

# ---------------------------------------------------------------- frontend
if ($Frontend) {
    Assert-Command npm "Install Node.js first."
    if (-not (Test-Path (Join-Path $frontendDir ".env.production"))) {
        throw "frontend\.env.production is missing (VITE_API_BASE, VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY). See deploy\README.md step 4."
    }
    $bucket = Get-StackOutput "SiteBucketName"
    $distribution = Get-StackOutput "DistributionId"

    Push-Location $frontendDir
    try {
        if (-not $SkipInstall) { Invoke-Step "npm ci" { npm ci } }
        Invoke-Step "npm run build" { npm run build }
        # hashed js/css first, so the new index.html never points at files that are not uploaded yet
        Invoke-Step "upload assets" { aws s3 sync dist "s3://$bucket" --delete --exclude index.html }
        Invoke-Step "upload index.html" { aws s3 cp dist\index.html "s3://$bucket/index.html" --cache-control "no-cache" }
        Invoke-Step "invalidate CloudFront" {
            aws cloudfront create-invalidation --distribution-id $distribution --paths "/index.html" --query "Invalidation.Id" --output text
        }
    }
    finally { Pop-Location }
    Write-Host "Frontend: $(Get-StackOutput 'SiteUrl') (live within a minute or two)" -ForegroundColor Green
}

Write-Host "Done." -ForegroundColor Green
