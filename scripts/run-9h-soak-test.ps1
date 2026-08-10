[CmdletBinding()]
param(
    [ValidateRange(1, 100000)]
    [int]$Rate = 100,

    [ValidateRange(1, 128)]
    [int]$Workers = 4,

    [ValidateRange(10, 100000)]
    [int]$MaxVus = 1000,

    [string]$Duration = '9h',

    [ValidateRange(1, 60000)]
    [int]$P95Ms = 500,

    [ValidateRange(1, 60000)]
    [int]$P99Ms = 1000,

    [switch]$SkipPreflight
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.performance.yml'
$loadScript = Join-Path $PSScriptRoot 'run-load-test.ps1'
$sliceScript = Join-Path $PSScriptRoot 'run-test-slice-benchmark.ps1'
$projectName = 'springbootai-performance'
$appStarted = $false

try {
    if (-not $SkipPreflight) {
        Write-Host 'Running the mixed-workload preflight...'
        & $loadScript `
            -Profile smoke `
            -Workload mixed `
            -Workers $Workers `
            -Rate 5 `
            -Duration 20s `
            -MaxVus 100 `
            -P95Ms $P95Ms `
            -P99Ms $P99Ms `
            -KeepApp
        $appStarted = $true

        Write-Host 'Running the test-slice assembly gate...'
        & $sliceScript -Iterations 5 -Warmup 1 -P95Ms 1000 -SkipBuild
    }

    Write-Host "Starting $Duration mixed soak at $Rate RPS with $Workers workers..."
    $loadArgs = @{
        Profile = 'soak'
        Workload = 'mixed'
        Workers = $Workers
        Rate = $Rate
        Duration = $Duration
        MaxVus = $MaxVus
        P95Ms = $P95Ms
        P99Ms = $P99Ms
    }
    if ($appStarted) { $loadArgs.SkipBuild = $true }
    & $loadScript @loadArgs
}
finally {
    & docker compose -p $projectName -f $composeFile down --remove-orphans
}
