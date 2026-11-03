[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$runtime=Join-Path $PSScriptRoot '.venv/soc-runtime'
foreach ($name in @('FastAPI','Langflow')) {
    $pidFile=Join-Path $runtime "$name.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $savedPid=[int](Get-Content -LiteralPath $pidFile)
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$savedPid"
        $matchesProject=$process.CommandLine -like '*uvicorn backend.main:app*' -or $process.CommandLine -like '*langflow*run*--port 7861*'
        if ($process -and $matchesProject) {
            Stop-Process -Id $savedPid
            Write-Host "$name detenido."
        }
    }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & docker compose --env-file (Join-Path $runtime 'compose.env') stop
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron detener todos los contenedores.' }
} finally { Pop-Location }
