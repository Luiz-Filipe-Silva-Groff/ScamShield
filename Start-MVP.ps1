param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localPython = Join-Path $PSScriptRoot '.tools\test-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $localPython)) {
    $localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $localPython)) {
        py -3.11 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Instale Python 3.11 ou use docker compose up --build.' }
    }
    & $localPython -m pip install --disable-pip-version-check -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar as dependências.' }
}
& $localPython run.py --port $Port
