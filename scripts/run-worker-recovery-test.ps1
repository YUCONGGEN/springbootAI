[CmdletBinding()]
param(
    [int]$Workers = 2,
    [int]$RecoverySeconds = 15,
    [int]$MaxFailures = 2,
    [switch]$KeepApp
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.performance.yml'
$projectName = 'springbootai-performance-recovery'
$targetUrl = 'http://127.0.0.1:8088/benchmark/async'
$env:APP_WORKERS = [string][Math]::Max(2, $Workers)

function Invoke-Docker {
    param([string[]]$DockerArgs)
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed with exit code $LASTEXITCODE"
    }
}

try {
    Invoke-Docker @(
        'compose', '-p', $projectName, '-f', $composeFile,
        'up', '-d', '--build', '--wait', 'app'
    )

    $killCode = @'
import json, os, signal, psutil
workers = []
for process in psutil.process_iter(['pid', 'cmdline']):
    command = ' '.join(process.info['cmdline'] or [])
    if 'multiprocessing.spawn' in command and 'spawn_main' in command:
        workers.append(process.info['pid'])
if len(workers) < 2:
    raise SystemExit('expected at least two Uvicorn workers, found: %r' % workers)
workers.sort()
victim = workers[0]
print(json.dumps({'before': workers, 'killed': victim}), flush=True)
os.kill(victim, signal.SIGTERM)
'@
    $rawKill = & docker compose -p $projectName -f $composeFile exec -T app python -c $killCode
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to terminate a Uvicorn worker.'
    }
    $workerState = $rawKill | Select-Object -Last 1 | ConvertFrom-Json

    $deadline = (Get-Date).AddSeconds($RecoverySeconds)
    $failures = 0
    $requests = 0
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    $newWorker = $null

    while ((Get-Date) -lt $deadline -and -not $newWorker) {
        try {
            $response = Invoke-WebRequest `
                -UseBasicParsing `
                -Uri $targetUrl `
                -DisableKeepAlive `
                -TimeoutSec 2
            $requests += 1
            $pidValue = [string]$response.Headers['X-Worker-Pid']
            if ($pidValue) {
                [void]$seen.Add($pidValue)
                if ($workerState.before -notcontains [int]$pidValue) {
                    $newWorker = $pidValue
                }
            }
        }
        catch {
            $failures += 1
        }
        Start-Sleep -Milliseconds 50
    }

    $report = [ordered]@{
        generated_at = (Get-Date).ToString('o')
        workers_before = $workerState.before
        killed_worker = $workerState.killed
        replacement_worker = $newWorker
        requests = $requests
        failures = $failures
        observed_workers = @($seen)
        recovery_limit_seconds = $RecoverySeconds
    }
    $reportPath = Join-Path $repoRoot "tests_performance\results\worker-recovery-$(Get-Date -Format 'yyyyMMdd-HHmmss').json"
    $report | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $reportPath

    if (-not $newWorker) {
        throw "No replacement worker was observed within $RecoverySeconds seconds."
    }
    if ($failures -gt $MaxFailures) {
        throw "Worker recovery produced $failures failed requests; allowed: $MaxFailures."
    }
    Write-Host "Worker recovery passed. Replacement PID: $newWorker. Failures: $failures. Result: $reportPath"
}
finally {
    Remove-Item Env:APP_WORKERS -ErrorAction SilentlyContinue
    if (-not $KeepApp) {
        & docker compose -p $projectName -f $composeFile down --remove-orphans
    }
}
