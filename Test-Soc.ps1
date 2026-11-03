[CmdletBinding()]
param([switch]$Live)

$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$env:FONTCONFIG_FILE=(Join-Path $PSScriptRoot '.venv/soc-runtime/fonts.conf') -replace '\\','/'
$env:WEASYPRINT_DLL_DIRECTORIES='C:/Program Files/Tesseract-OCR'
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$resultDirectory=Join-Path $PSScriptRoot '.venv/soc-runtime/test-results'
New-Item -ItemType Directory -Force $resultDirectory | Out-Null
$resultLog=Join-Path $resultDirectory ('soc-tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$failedChecks=[Collections.Generic.List[string]]::new()

function Invoke-SocCheck {
    param([string]$Name,[string]$Executable,[string[]]$Arguments)
    "[$Name]" | Tee-Object -FilePath $resultLog -Append
    $previousPreference=$ErrorActionPreference
    try {
        $ErrorActionPreference='Continue'
        & $Executable @Arguments 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $resultLog -Append
        $checkExit=$LASTEXITCODE
    } finally {
        $ErrorActionPreference=$previousPreference
    }
    "EXIT_CODE $Name $checkExit" | Tee-Object -FilePath $resultLog -Append
    if ($checkExit -ne 0) { $failedChecks.Add($Name) }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    Invoke-SocCheck 'Python SQLite y simulaciones' $python @('-m','unittest','discover','-s','tests','-v')
    Invoke-SocCheck 'Reglas n8n' 'node.exe' @('--test','tests/ui-and-workflow.test.cjs')
    Invoke-SocCheck 'Compilacion TypeScript' 'npm.cmd' @('run','build','--prefix','frontend')
    Invoke-SocCheck 'React' 'npm.cmd' @('test','--prefix','frontend')
    if ($Live) {
        foreach ($pattern in @('live_soc.py','live_platform.py','live_chat.py','live_recovery.py','live_backup.py','live_totp.py','live_impact.py')) {
            Invoke-SocCheck $pattern $python @('-m','unittest','discover','-s','tests','-p',$pattern,'-v')
        }
    }
    if ($failedChecks.Count) {
        "GRUPOS_FALLIDOS $($failedChecks -join ', ')" | Tee-Object -FilePath $resultLog -Append
    } else {
        'TODOS_LOS_GRUPOS_APROBADOS' | Tee-Object -FilePath $resultLog -Append
    }
} finally {
    Pop-Location
    Write-Host "Resultado completo en $resultLog"
}
if ($failedChecks.Count) { exit 1 }
exit 0
