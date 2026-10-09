param([ValidateSet('ollama','gemini','glm')][string]$Provider, [string]$Model, [int]$Port=8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Provider) { $env:MODEL_PROVIDER = $Provider }
if ($Model) {
    $taskProvider = if ($Provider) { $Provider } else { 'ollama' }
    if ($taskProvider -eq 'gemini') { $env:GEMINI_MODEL = $Model }
    elseif ($taskProvider -eq 'glm') { $env:GLM_MODEL = $Model }
    else { $env:OLLAMA_MODEL = $Model }
}
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Frontend build missing. Run .\setup.ps1 first.' }
$taskPython = if (Test-Path -LiteralPath '.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
Write-Host "Inbox Desk: http://127.0.0.1:$Port (Ctrl+C to stop)"
& $taskPython -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
