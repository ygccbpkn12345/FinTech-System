param([string]$Python = "py")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
$pythonArgs = @()
if ($Python -eq "py") { $pythonArgs = @("-3.12") }
$version = & $Python @pythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $version -ne "3.12") { throw "Python 3.12 is required. Use -Python <path-to-python.exe>." }
foreach ($component in @("analyst/Analyst", "System/FinPortfolio_MVP/backend")) {
    $componentDir = Join-Path $projectRoot $component
    $venvDir = Join-Path $componentDir ".venv"
    if (-not (Test-Path -LiteralPath $venvDir)) {
        Invoke-Checked -Program $Python -Arguments ($pythonArgs + @("-m", "venv", $venvDir))
    }
    $venvPython = Join-Path $venvDir "Scripts/python.exe"
    Invoke-Checked -Program $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $componentDir "requirements.txt"))
}
foreach ($config in @(@("analyst/Analyst/.env.example", "analyst/Analyst/.env"), @("analyst/frontend/.env.development.example", "analyst/frontend/.env.development"))) {
    $target = Join-Path $projectRoot $config[1]
    if (-not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath (Join-Path $projectRoot $config[0]) -Destination $target }
}
foreach ($component in @("analyst/frontend", "System/FinPortfolio_MVP/frontend")) {
    Push-Location (Join-Path $projectRoot $component)
    try { Invoke-Checked -Program "npm.cmd" -Arguments @("ci") } finally { Pop-Location }
}
$portfolioPython = Join-Path $projectRoot "System/FinPortfolio_MVP/backend/.venv/Scripts/python.exe"
Invoke-Checked -Program $portfolioPython -Arguments @((Join-Path $PSScriptRoot "prepare_example.py"))
Write-Host "Setup complete. Start each service with scripts/start.ps1; see README.md."
