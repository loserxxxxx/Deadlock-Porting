param([string]$Python)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $pythonArgs = @()
    if (-not $Python) {
        if (Test-Path '.venv/Scripts/python.exe') { $Python = (Resolve-Path '.venv/Scripts/python.exe').Path }
        elseif (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py'; $pythonArgs = @('-3.12') }
        else { $Python = 'python' }
    }
    & $Python @pythonArgs -c "import sys; assert sys.version_info[:2] == (3, 12), 'Python 3.12 is required'"
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or pass -Python with its executable path.' }
    & $Python @pythonArgs package-runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Runtime packaging failed.' }
    cargo build --release --manifest-path src-tauri/Cargo.toml
    if ($LASTEXITCODE -ne 0) { throw 'App build failed.' }
    New-Item -ItemType Directory -Path dist -Force | Out-Null
    Copy-Item src-tauri/target/release/deadlock-porting.exe 'dist/Deadlock Porting.exe' -Force
    Write-Host 'Built dist/Deadlock Porting.exe'
} finally { Pop-Location }
