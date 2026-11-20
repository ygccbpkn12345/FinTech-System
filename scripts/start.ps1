param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("analyst-backend", "analyst-frontend", "portfolio-backend", "portfolio-frontend")]
    [string]$Service
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$services = @{
    "analyst-backend" = @("analyst/Analyst", "python")
    "analyst-frontend" = @("analyst/frontend", "npm")
    "portfolio-backend" = @("System/FinPortfolio_MVP/backend", "python")
    "portfolio-frontend" = @("System/FinPortfolio_MVP/frontend", "npm")
}
$entry = $services[$Service]
Push-Location (Join-Path $projectRoot $entry[0])
try {
    if ($entry[1] -eq "npm") {
        & npm.cmd run dev -- --host 127.0.0.1
    } else {
        $pythonExe = Join-Path (Get-Location).Path ".venv/Scripts/python.exe"
        if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Run scripts/setup.ps1 first." }
        if ($Service -eq "analyst-backend") {
            & $pythonExe -m uvicorn api_server:app --host 127.0.0.1 --port 8000
        } else {
            & $pythonExe -m app
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Service exited with code $LASTEXITCODE" }
} finally { Pop-Location }
