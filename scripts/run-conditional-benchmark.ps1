[CmdletBinding()]
param(
    [ValidateRange(1, 10000)]
    [int]$Iterations = 50,

    [ValidateRange(1, 5000)]
    [int]$Components = 200,

    [ValidateRange(0, 1000)]
    [int]$Warmup = 5,

    [double]$P95Ms = 250,

    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.performance.yml'
$projectName = 'springbootai-conditional-benchmark'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$resultName = "conditional-assembly-$timestamp.json"
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

$resultsDir = Join-Path $repoRoot 'tests_performance\results'
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null

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
        'python', 'tests_performance/conditional_assembly.py',
        '--iterations', [string]$Iterations,
        '--components', [string]$Components,
        '--warmup', [string]$Warmup,
        '--p95-ms', [string]$P95Ms,
        '--output', $resultContainerPath
    )
    Write-Host "Conditional assembly benchmark passed. Result: $(Join-Path $resultsDir $resultName)"
}
finally {
    & docker compose -p $projectName -f $composeFile down --remove-orphans
}
