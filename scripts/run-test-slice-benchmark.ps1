[CmdletBinding()]
param(
    [ValidateRange(1, 1000)]
    [int]$Iterations = 10,

    [ValidateRange(0, 100)]
    [int]$Warmup = 1,

    [ValidateRange(1, 60000)]
    [double]$P95Ms = 1000,

    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.performance.yml'
$projectName = 'springpy-test-slice-benchmark'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$resultName = "test-slice-assembly-$timestamp.json"
$resultContainerPath = "/results/$resultName"

function Invoke-Docker {
    param([string[]]$DockerArgs)
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed with exit code $LASTEXITCODE"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found in PATH.'
}
Invoke-Docker @('info', '--format', '{{.ServerVersion}}')
New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot 'tests_performance\results') | Out-Null

try {
    if (-not $SkipBuild) {
        Invoke-Docker @(
            'compose', '-p', $projectName, '-f', $composeFile,
            'build', 'app'
        )
    }
    Invoke-Docker @(
        'compose', '-p', $projectName, '-f', $composeFile,
        'run', '--rm', '--no-deps', 'app',
        'python', '-m', 'tests_performance.test_slice_assembly',
        '--iterations', [string]$Iterations,
        '--warmup', [string]$Warmup,
        '--p95-ms', [string]$P95Ms,
        '--output', $resultContainerPath
    )
    Write-Host "Test-slice benchmark passed. Result: $(Join-Path $repoRoot "tests_performance\results\$resultName")"
}
finally {
    & docker compose -p $projectName -f $composeFile down --remove-orphans
}
