# Copyright 2025 Google LLC
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
$ErrorActionPreference = "Stop"

Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
npm install

Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
$pythonExe = $null
if (Test-Path "venv\Scripts\python.exe") {
    $pythonExe = (Resolve-Path "venv\Scripts\python.exe").Path
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
}
if (-not $pythonExe) {
    Write-Error "Python not found. Install Python 3.10+ and ensure 'python' or 'py' is in PATH."
}
$pipArgs = @("-m", "pip", "install", "-r", "requirements.txt")
if ($pythonExe -eq "py") { & py -3 $pipArgs } else { & $pythonExe $pipArgs }

Write-Host "Installation complete! You can now run .\scripts\dev.ps1 to start the app." -ForegroundColor Green
