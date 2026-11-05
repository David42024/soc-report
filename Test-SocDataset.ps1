[CmdletBinding(DefaultParameterSetName='Preview')]
param(
    [Parameter(ParameterSetName='Preview')][switch]$DryRun,
    [Parameter(Mandatory,ParameterSetName='Run')][switch]$Run,
    [Parameter(Mandatory,ParameterSetName='Run')][ValidatePattern('^[a-z0-9][a-z0-9-]{2,39}$')][string]$RunId,
    [Parameter(Mandatory,ParameterSetName='Run')][string]$ReviewedCases,
    [Parameter(ParameterSetName='Run')][switch]$Local,
    [Parameter(ParameterSetName='Run')][switch]$Native,
    [Parameter(ParameterSetName='Run')][switch]$VerifyRecovery,
    [Parameter(Mandatory)][string]$Archive
)

$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$archivePath=(Resolve-Path -LiteralPath $Archive).Path
$arguments=@('-X','utf8','-m','scripts.soc_dataset','--archive',$archivePath)
if ($Run) {
    $arguments+=@('--run-id',$RunId,'--reviewed',(Resolve-Path -LiteralPath $ReviewedCases).Path)
    if ($Local) { $arguments+='--local' }
    if ($Native) { $arguments+='--native' }
    if ($VerifyRecovery) { $arguments+='--verify-recovery' }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $python @arguments
    $result=$LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
