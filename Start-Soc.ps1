[CmdletBinding()]
param([ValidateRange(30,1800)][int]$TimeoutSeconds=600, [switch]$Restart, [switch]$RestartLangflow)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runtime = Join-Path $root '.venv\soc-runtime'
$python = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $runtime 'startup-logs'
$langflow = Join-Path $env:LOCALAPPDATA 'com.LangflowDesktop\.langflow-venv\Scripts\langflow.exe'
$envFile = Join-Path $runtime 'compose.env'

function Write-Stage([string]$Name,[string]$Message) {
    Write-Host ('[{0:HH:mm:ss}] [{1}] {2}' -f (Get-Date),$Name,$Message)
}
function Test-Http([string]$Url) {
    try {
        $response = $http.GetAsync($Url).GetAwaiter().GetResult()
        try { return $response.IsSuccessStatusCode } finally { $response.Dispose() }
    } catch { return $false }
}
function Test-DockerEngine {
    # Windows PowerShell wraps native stderr as a PowerShell error.
    $ErrorActionPreference='SilentlyContinue'
    & docker version --format '{{.Server.Version}}' 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function Start-Native([string]$Name,[string]$Executable,[string]$Arguments) {
    Write-Stage $Name 'Iniciando.'
    $options=@{FilePath=$Executable;ArgumentList=$Arguments;WorkingDirectory=$root;WindowStyle='Hidden';PassThru=$true;RedirectStandardOutput=(Join-Path $logs "$Name.out.log");RedirectStandardError=(Join-Path $logs "$Name.err.log")}
    $process = Start-Process @options
    Set-Content -LiteralPath (Join-Path $runtime "$Name.pid") -Value $process.Id -Encoding ascii
}

function Get-ProjectProcess([string]$Name,[string]$Pattern) {
    $pidFile=Join-Path $runtime "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { return }
    $projectPid=0
    if (-not [int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$projectPid)) { return }
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$projectPid"
    if ($process -and $process.CommandLine -like $Pattern) { return $process }
}

function Stop-ProjectService([string]$Name,[string]$Pattern) {
    $serviceProcess=Get-ProjectProcess $Name $Pattern
    if (-not $serviceProcess) { return }
    # A Windows venv launcher has a child interpreter. Stopping only the
    # launcher leaves the old service (and its old privacy code) running.
    $pending=[Collections.Generic.Queue[int]]::new()
    $serviceIds=[Collections.Generic.List[int]]::new()
    $pending.Enqueue([int]$serviceProcess.ProcessId)
    while ($pending.Count) {
        $servicePid=$pending.Dequeue()
        $serviceIds.Add($servicePid)
        foreach ($child in (Get-CimInstance Win32_Process -Filter "ParentProcessId=$servicePid")) {
            if ($child.CreationDate -ge $serviceProcess.CreationDate) { $pending.Enqueue([int]$child.ProcessId) }
        }
    }
    $ids=$serviceIds.ToArray()
    [array]::Reverse($ids)
    Stop-Process -Id $ids -ErrorAction SilentlyContinue
    Wait-Process -Id $ids -Timeout 15 -ErrorAction SilentlyContinue
}

function Start-IfNeeded([string]$Name,[string]$Executable,[string]$Arguments,[string]$Pattern,[string]$Url) {
    if (Test-Http $Url) { return }
    if (Get-ProjectProcess $Name $Pattern) { Write-Stage $Name 'Ya está iniciando. Esperando a que responda.'; return }
    Start-Native $Name $Executable $Arguments
}

Add-Type -AssemblyName System.Net.Http
$handler=[System.Net.Http.HttpClientHandler]::new()
$handler.UseProxy=$false
$http=[System.Net.Http.HttpClient]::new($handler)
$http.Timeout=[TimeSpan]::FromSeconds(3)
Push-Location -LiteralPath $root
try {
    New-Item -ItemType Directory -Force $logs | Out-Null
    Write-Stage 'Docker' 'Comprobando motor.'
    if (-not (Test-DockerEngine)) {
        Start-Process -FilePath 'C:/Program Files/Docker/Docker/Docker Desktop.exe' -WindowStyle Hidden
        $watch=[Diagnostics.Stopwatch]::StartNew()
        do {
            Start-Sleep -Seconds 3
            $dockerReady=Test-DockerEngine
            if ($dockerReady) { break }
            Write-Stage 'Docker' 'Esperando al motor.'
        } while ($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds)
        if (-not $dockerReady) { throw 'Docker no pudo iniciar. Revisa Docker Desktop.' }
    }
    if (-not (Test-Path -LiteralPath $envFile)) {
        Write-Stage 'Configuración' 'Preparando contenedores y copias de seguridad.'
        & $python scripts/prepare_containers.py
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la configuración.' }
    }
    Write-Stage 'Contenedores' 'Levantando PostgreSQL 16, Redis y n8n.'
    & docker compose --env-file $envFile up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron iniciar los contenedores.' }
    Write-Stage 'Frontend' 'Compilando React y TypeScript.'
    & npm.cmd run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Falló la compilación del frontend.' }
    Write-Stage 'Base de datos' 'Verificando esquema y usuarios iniciales.'
    & $python -m backend.manage bootstrap
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo inicializar la base de datos.' }
    $env:FONTCONFIG_FILE=(Join-Path $runtime 'fonts.conf') -replace '\\','/'
    $env:WEASYPRINT_DLL_DIRECTORIES='C:/Program Files/Tesseract-OCR'
    $env:LANGFLOW_CONFIG_DIR=Join-Path $runtime 'langflow'
    $env:LANGFLOW_DATABASE_URL='sqlite:///' + ((Join-Path $runtime 'langflow.sqlite3') -replace '\\','/')
    $env:LANGFLOW_SSRF_ALLOWED_HOSTS='127.0.0.1'
    $env:LANGFLOW_AUTO_LOGIN='true'
    $env:LANGFLOW_DO_NOT_TRACK='true'
    # Both Python services load the same local privacy filter and YAML policy.
    $env:PYTHONPATH=if ($env:PYTHONPATH) { "$root$([IO.Path]::PathSeparator)$env:PYTHONPATH" } else { $root }
    if (Test-Http 'http://127.0.0.1:7861/health') {
        $listeners=Get-NetTCPConnection -State Listen -LocalPort 7861 -ErrorAction SilentlyContinue
        foreach ($listener in $listeners) {
            $existing=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
            if ($existing.CommandLine -like '*langflow*run*--port 7861*') {
                Set-Content -LiteralPath (Join-Path $runtime 'Langflow.pid') -Value $existing.ProcessId -Encoding ascii
            }
        }
    }
    if ($RestartLangflow) {
        Stop-ProjectService 'Langflow' '*langflow*run*--port 7861*'
    }
    Start-IfNeeded 'Langflow' $langflow 'run --host 127.0.0.1 --port 7861' '*langflow*run*--port 7861*' 'http://127.0.0.1:7861/health'
    if ($Restart) {
        Stop-ProjectService 'FastAPI' '*uvicorn backend.main:app*'
    }
    Start-IfNeeded 'FastAPI' $python '-m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --no-access-log' '*uvicorn backend.main:app*' 'http://127.0.0.1:8000/health'
    $watch=[Diagnostics.Stopwatch]::StartNew()
    do {
        $apiReady=Test-Http 'http://127.0.0.1:8000/health'
        $flowReady=Test-Http 'http://127.0.0.1:7861/health'
        $routerReady=Test-Http 'http://127.0.0.1:5680/healthz/readiness'
        if ($apiReady -and $flowReady -and $routerReady) { break }
        Write-Stage 'Arranque' "FastAPI=$apiReady Langflow=$flowReady n8n=$routerReady"
        Start-Sleep -Seconds 3
    } while ($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds)
    if (-not ($apiReady -and $flowReady -and $routerReady)) {
        $pending=@()
        if (-not $apiReady) { $pending+='FastAPI' }
        if (-not $flowReady) { $pending+='Langflow' }
        if (-not $routerReady) { $pending+='n8n' }
        throw "Servicios locales pendientes tras $TimeoutSeconds segundos ($($pending -join ', ')). Revisa $logs"
    }
    Write-Stage 'SOC' 'Servicios disponibles.'
    Write-Stage 'Proveedores' 'El arranque confirma la disponibilidad local. Groq y Gemini se prueban desde Operaciones > Salud.'
    Write-Host 'Aplicación    http://127.0.0.1:8000/'
    Write-Host 'API           http://127.0.0.1:8000/docs'
    Write-Host 'Langflow      http://127.0.0.1:7861/'
    Write-Host 'n8n           http://127.0.0.1:5680/'
    Write-Host 'PostgreSQL 16 127.0.0.1:5434 / soc_reports'
    Write-Host "Credenciales  $runtime\access.json"
    Write-Host "Registros     $logs"
} finally {
    Pop-Location
    $http.Dispose()
}
