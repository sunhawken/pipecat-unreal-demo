# Runs a Python script inside the demo project with the editor-only Python plugins switched on,
# then restores PipecatDemo.uproject exactly as it was.
#   .\Run-UEPython.ps1 -Script C:\path\script.py [-LogName name.log]
param(
    [Parameter(Mandatory)][string]$Script,
    [string]$LogName = 'ue-python.log'
)
$root = Split-Path -Parent $PSScriptRoot
$proj = if (Test-Path (Join-Path $root 'PipecatDemo.uproject')) { Join-Path $root 'PipecatDemo.uproject' } else { Join-Path $root 'pipecat-unreal-demo\PipecatDemo.uproject' }
$ue   = Join-Path ([Environment]::GetEnvironmentVariable('UE_ROOT', 'User')) 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'
$log  = Join-Path $root "logs\$LogName"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

Copy-Item $proj "$proj.bak" -Force
try {
    $j = Get-Content $proj -Raw | ConvertFrom-Json
    foreach ($n in 'PythonScriptPlugin', 'EditorScriptingUtilities') {
        if (-not ($j.Plugins | Where-Object Name -eq $n)) {
            $j.Plugins += [pscustomobject]@{ Name = $n; Enabled = $true; TargetAllowList = @('Editor') }
        }
    }
    $j | ConvertTo-Json -Depth 6 | Set-Content $proj -Encoding utf8
    $p = Start-Process $ue -ArgumentList "`"$proj`"", '-run=pythonscript', "-script=`"$Script`"", '-unattended',
        '-nosplash', '-nullrhi', '-stdout', '-FullStdOutLogOutput', "-abslog=`"$log`"" -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit(900000)) { $p.Kill(); Write-Warning 'timed out' } else { "exit=$($p.ExitCode)" }
} finally {
    Copy-Item "$proj.bak" $proj -Force
    Remove-Item "$proj.bak" -Force
}
Select-String -Path $log -Pattern 'KALINA|LogPython: Error|Traceback' | ForEach-Object { $_.Line }
