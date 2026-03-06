param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GameArgs
)

Set-Location $PSScriptRoot

Write-Host ""
Write-Host "===================================" -ForegroundColor Cyan
Write-Host " Thronglets Game Launcher" -ForegroundColor Green
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = "{0}_{1}" -f (Get-Date -Format "yyyyMMdd_HHmmss_fff"), $PID
$logFile = Join-Path $logDir "batch_$timestamp.log"

$pythonCmd = $null
$pythonArgs = @()

if (Test-Path ".venv\\Scripts\\python.exe") {
    $pythonCmd = (Resolve-Path ".venv\\Scripts\\python.exe").Path
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
    $pythonArgs = @("-3")
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
}

if (-not $pythonCmd) {
    Write-Host "Python not found. Install Python or create the project's .venv." -ForegroundColor Red
    exit 1
}

$commandArgs = @()
$commandArgs += $pythonArgs
$commandArgs += "thronglets_game.py"
$commandArgs += $GameArgs

Write-Host "Using interpreter: $pythonCmd" -ForegroundColor Green
Write-Host "Logging output to: $logFile" -ForegroundColor Yellow
Write-Host ""

& $pythonCmd @commandArgs 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $logFile
$exitCode = if ($LASTEXITCODE -ne $null) { $LASTEXITCODE } else { 0 }

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Game session complete" -ForegroundColor Green
}
else {
    Write-Host "Game exited with code $exitCode" -ForegroundColor Red
}
Write-Host "Log file: $logFile"
exit $exitCode
