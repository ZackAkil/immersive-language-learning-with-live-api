# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "")
$env:DEV_MODE = "true"

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "Warning: .env file not found. Copying from .env.example..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "Please update .env with your configuration."
    } else {
        Write-Host "Warning: .env file not found and no .env.example exists." -ForegroundColor Yellow
    }
}

if (Test-Path "venv\Scripts\python.exe") {
    $pythonExe = (Resolve-Path "venv\Scripts\python.exe").Path
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = (Get-Command py).Source
} else {
    Write-Error "Python not found. Install Python 3.10+ or run .\scripts\install.ps1 first."
}

# Resolve py to actual python for backend process (Start-Process needs executable path or command name)
$backendArgList = @("-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload")
if ($pythonExe -match "py(\.exe)?$") {
    $backendArgList = @("-3") + $backendArgList
}

Write-Host "Starting development environment..." -ForegroundColor Cyan
Write-Host "Starting Backend (Uvicorn) on port 8000..." -ForegroundColor Cyan
$backendProcess = $null
try {
    if ($pythonExe -match "py(\.exe)?$") {
        $backendProcess = Start-Process -FilePath "py" -ArgumentList $backendArgList -NoNewWindow -PassThru
    } else {
        $backendProcess = Start-Process -FilePath $pythonExe -ArgumentList $backendArgList -NoNewWindow -PassThru
    }
    Start-Sleep -Seconds 2
    Write-Host "Starting Frontend (Vite)..." -ForegroundColor Cyan
    npm run dev
} finally {
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Write-Host "Stopping backend..." -ForegroundColor Yellow
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
