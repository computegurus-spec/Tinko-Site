<# ------------- Tinko one-shot runner -------------
This script:
- Starts uvicorn in a new console window
- Waits for /api/health
- (Optional) Inserts a test failed payment for a merchant
- (Optional) Enqueues retries for the newest failed payment
- Opens the dashboard page in your browser

Edit the variables in the CONFIG section below if needed.
--------------------------------------------------- #>

param(
  [string]$ApiKey = "",             # <- paste a merchant API key to target (or pass with -ApiKey)
  [switch]$InsertTestEvent,         # add -InsertTestEvent to create a fresh failed event
  [switch]$EnqueueRetry             # add -EnqueueRetry to enqueue retry for newest failed event
)

# -------- CONFIG --------
$BackendDir   = "C:\Users\sadis\OneDrive\Desktop\Tinko-Site\backend"
$PublicURL    = "https://tinko.in/dashboard.html"     # your deployed dashboard
$LocalAPI     = "http://127.0.0.1:8000"
$PSQLPath     = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
$DbUser       = "postgres"
$DbHost       = "localhost"
$DbName       = "tinko"
$PythonExe    = "python"                               # or full path to python if needed
$UvicornArgs  = "app:app --host 127.0.0.1 --port 8000 --reload"
# ------------------------

function Start-Backend {
  Write-Host ">> Starting backend (uvicorn)..." -ForegroundColor Cyan
  Push-Location $BackendDir
  # start a new PowerShell window so server keeps running
  Start-Process -WindowStyle Normal powershell -ArgumentList "-NoExit", "-Command", "cd `"$BackendDir`"; uvicorn $UvicornArgs"
  Pop-Location
}

function Wait-Health {
  Write-Host ">> Waiting for health endpoint $LocalAPI/api/health ..." -ForegroundColor Cyan
  $ok = $false
  for ($i=0; $i -lt 30; $i++) {
    try {
      $resp = Invoke-RestMethod -Uri "$LocalAPI/api/health" -TimeoutSec 2
      if ($resp.ok -eq $true) { $ok = $true; break }
    } catch { Start-Sleep -Seconds 1 }
    Start-Sleep -Milliseconds 800
  }
  if (-not $ok) {
    Write-Host "!! Backend didn’t come up in time. You can still continue if you know it’s running." -ForegroundColor Yellow
  } else {
    Write-Host ">> Health OK" -ForegroundColor Green
  }
}

function Insert-Test-Event {
  param([string]$ApiKey)
  if (-not $ApiKey) { Write-Host "!! No -ApiKey provided; skipping insert." -ForegroundColor Yellow; return }
  Write-Host ">> Inserting test failed payment for API key: $ApiKey" -ForegroundColor Cyan

  $sql = @"
DO $$
DECLARE
  mid uuid;
  pid text := 'pay_test_' || floor(extract(epoch from now()))::text;
BEGIN
  SELECT id INTO mid FROM merchants WHERE api_key = '$ApiKey' LIMIT 1;
  IF mid IS NULL THEN
    RAISE NOTICE 'Merchant not found for API key.';
  ELSE
    INSERT INTO payment_events
      (merchant_id, razorpay_payment_id, customer_email, customer_phone, amount, currency, status, failure_reason, gateway)
    VALUES
      (mid, pid, 'buyer@example.com', '9876543210', 7500, 'INR', 'failed', 'Card declined', 'razorpay');
    RAISE NOTICE 'Inserted payment id: %', pid;
  END IF;
END $$;
"@

  & "$PSQLPath" -U $DbUser -h $DbHost -d $DbName -v "ON_ERROR_STOP=1" -c $sql
}

function Enqueue-Retry-For-Latest {
  param([string]$ApiKey)
  if (-not $ApiKey) { Write-Host "!! No -ApiKey provided; skipping enqueue." -ForegroundColor Yellow; return }

  Write-Host ">> Enqueueing retry via Python helper..." -ForegroundColor Cyan
  $py = @"
from app import scheduler
from retry_engine import enqueue_retry
from db import get_merchant_by_api_key, execute_query

api_key = '$ApiKey'
m = get_merchant_by_api_key(api_key)
if not m:
    print('Merchant not found for given API key')
    raise SystemExit(1)

p = execute_query(\"\"\"
  SELECT razorpay_payment_id, customer_email, customer_phone, amount, currency, failure_reason
  FROM payment_events
  WHERE merchant_id=%s AND status='failed'
  ORDER BY created_at DESC LIMIT 1
\"\"\", (m['id'],), fetch="one")

if not p:
    print('No failed events found to enqueue')
    raise SystemExit(0)

pd = dict(p)
pd['razorpay_payment_id'] = p['razorpay_payment_id']
print('Picked row:', pd)
enqueue_retry(scheduler, pd, m)
print('Enqueued')
"@

  $tmpPy = Join-Path $BackendDir "scripts\enqueue_once.py"
  if (!(Test-Path (Split-Path $tmpPy))) { New-Item -ItemType Directory -Force -Path (Split-Path $tmpPy) | Out-Null }
  $py | Out-File -FilePath $tmpPy -Encoding utf8

  Push-Location $BackendDir
  & $PythonExe $tmpPy
  Pop-Location
}

function Show-Stats {
  param([string]$ApiKey)
  if (-not $ApiKey) { return }
  Write-Host ">> Current stats for merchant (API key: $ApiKey)" -ForegroundColor Cyan
  try {
    $r = Invoke-RestMethod -Uri "$LocalAPI/api/stats" -Headers @{ "X-API-Key" = $ApiKey }
    $r | ConvertTo-Json -Depth 4
  } catch { Write-Host "!! Could not fetch stats yet." -ForegroundColor Yellow }
}

# ------------------ RUN ------------------
Write-Host "===== Tinko Runner =====" -ForegroundColor Magenta
Write-Host "Backend: $BackendDir" -ForegroundColor DarkGray
Write-Host "API    : $LocalAPI" -ForegroundColor DarkGray
Write-Host ""

Start-Backend
Wait-Health

if ($ApiKey) { Show-Stats -ApiKey $ApiKey }

if ($InsertTestEvent) {
  Insert-Test-Event -ApiKey $ApiKey
  Start-Sleep -Seconds 1
  Show-Stats -ApiKey $ApiKey
}

if ($EnqueueRetry) {
  Enqueue-Retry-For-Latest -ApiKey $ApiKey
}

Write-Host ">> Opening dashboard: $PublicURL" -ForegroundColor Cyan
Start-Process $PublicURL

Write-Host "`nAll set. Keep the server window open. Use Ctrl+C there to stop uvicorn." -ForegroundColor Green
