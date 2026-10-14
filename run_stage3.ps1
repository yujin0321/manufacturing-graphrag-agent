param([string]$Python = "$PSScriptRoot\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
Push-Location $PSScriptRoot
try {
    foreach ($module in @('imaks_kg.preprocess.sensors', 'imaks_kg.preprocess.documents', 'imaks_kg.stage3.build', 'imaks_kg.stage3.extract', 'imaks_kg.stage3.audit')) {
        & $Python -m $module
        if ($LASTEXITCODE -ne 0) { throw "Failed: $module" }
    }
    & $Python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
} finally { Pop-Location }
