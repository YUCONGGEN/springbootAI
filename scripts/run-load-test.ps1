[CmdletBinding()]
param(
    [ValidateSet('smoke', 'baseline', 'stress', 'soak')]
    [string]$Profile = 'smoke',

    [ValidateSet(
        'mixed', 'async', 'sync', 'gateway', 'echo', 'cpu',
        'validation', 'cache', 'csv', 'jpa', 'conditional',
        'data', 'datasource', 'txevent', 'config', 'i18n', 'actuator',
        'swagger', 'websocket', 'messaging', 'custom', 'seata'
    )]
    [string]$Workload = 'mixed',

    [string]$TargetUrl = '',
    [int]$Workers = 2,
    [int]$Rate = 0,
    [string]$Duration = '',
    [int]$TargetRps = 0,
    [int]$MaxVus = 0,
    [int]$P95Ms = 500,
    [int]$P99Ms = 1000,
    [double]$FailRate = 0.01,
    [ValidateRange(1, 2000)]
    [int]$CsvRows = 50,
    [ValidateRange(1, 10000)]
    [int]$ConditionalEvaluations = 100,
    [ValidateRange(20, 2000)]
    [int]$DataRows = 100,
    [ValidateRange(1, 1000)]
    [int]$BindingIterations = 25,
    [ValidateRange(1, 10000)]
    [int]$I18nMessages = 100,
    [ValidateRange(100, 30000)]
    [int]$WebSocketTimeoutMs = 3000,
    [string]$SwaggerPath = '/openapi.json',
    [string]$SwaggerDocsPath = '/docs',
    [string]$SwaggerRedocPath = '/redoc',
    [string]$CustomPath = '/',
    [string]$CustomMethod = 'GET',
    [string]$CustomBody = '',
    [string]$AuthToken = '',
    [string]$SeataBridgeToken = '',
    [string]$SeataApplicationId = 'springpy-k6',
    [string]$SeataTransactionGroup = 'springpy_tx_group',
    [int]$SeataTimeoutMs = 60000,
    [string]$ExpectedStatus = '200',
    [switch]$SkipBuild,
    [switch]$KeepApp
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.performance.yml'
$projectName = 'springbootai-performance'
$startedBenchmark = [string]::IsNullOrWhiteSpace($TargetUrl) -and $Workload -ne 'seata'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$resultContainerPath = "/results/$Profile-$Workload-$timestamp.json"

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
    if ($startedBenchmark) {
        $env:APP_WORKERS = [string][Math]::Max(1, $Workers)
        $upArgs = @(
            'compose', '-p', $projectName, '-f', $composeFile,
            'up', '-d'
        )
        if (-not $SkipBuild) { $upArgs += '--build' }
        $upArgs += @('--wait', 'app')
        Invoke-Docker $upArgs
        $effectiveTarget = 'http://app:8080'
    }
    else {
        if ([string]::IsNullOrWhiteSpace($TargetUrl)) {
            $TargetUrl = 'http://127.0.0.1:18091'
        }
        $effectiveTarget = $TargetUrl.TrimEnd('/')
        $effectiveTarget = $effectiveTarget.Replace('://localhost', '://host.docker.internal')
        $effectiveTarget = $effectiveTarget.Replace('://127.0.0.1', '://host.docker.internal')
    }

    $runArgs = @(
        'compose', '-p', $projectName, '-f', $composeFile,
        'run', '--rm', '--no-deps',
        '-e', "SPRINGPY_BASE_URL=$effectiveTarget",
        '-e', "SPRINGPY_PROFILE=$Profile",
        '-e', "SPRINGPY_WORKLOAD=$Workload",
        '-e', "SPRINGPY_RESULTS_FILE=$resultContainerPath",
        '-e', "SPRINGPY_P95_MS=$P95Ms",
        '-e', "SPRINGPY_P99_MS=$P99Ms",
        '-e', "SPRINGPY_FAIL_RATE=$FailRate",
        '-e', "SPRINGPY_CSV_ROWS=$CsvRows",
        '-e', "SPRINGPY_CONDITIONAL_EVALUATIONS=$ConditionalEvaluations",
        '-e', "SPRINGPY_DATA_ROWS=$DataRows",
        '-e', "SPRINGPY_BINDING_ITERATIONS=$BindingIterations",
        '-e', "SPRINGPY_I18N_MESSAGES=$I18nMessages",
        '-e', "SPRINGPY_WEBSOCKET_TIMEOUT_MS=$WebSocketTimeoutMs",
        '-e', "SPRINGPY_SWAGGER_PATH=$SwaggerPath",
        '-e', "SPRINGPY_SWAGGER_DOCS_PATH=$SwaggerDocsPath",
        '-e', "SPRINGPY_SWAGGER_REDOC_PATH=$SwaggerRedocPath",
        '-e', "SPRINGPY_CUSTOM_PATH=$CustomPath",
        '-e', "SPRINGPY_CUSTOM_METHOD=$CustomMethod",
        '-e', "SPRINGPY_CUSTOM_BODY=$CustomBody",
        '-e', "SPRINGPY_AUTH_TOKEN=$AuthToken",
        '-e', "SPRINGPY_SEATA_BRIDGE_TOKEN=$SeataBridgeToken",
        '-e', "SPRINGPY_SEATA_APPLICATION_ID=$SeataApplicationId",
        '-e', "SPRINGPY_SEATA_TRANSACTION_GROUP=$SeataTransactionGroup",
        '-e', "SPRINGPY_SEATA_TIMEOUT_MS=$SeataTimeoutMs",
        '-e', "SPRINGPY_EXPECTED_STATUS=$ExpectedStatus"
    )
    if ($Rate -gt 0) { $runArgs += @('-e', "SPRINGPY_RATE=$Rate") }
    if ($Duration) { $runArgs += @('-e', "SPRINGPY_DURATION=$Duration") }
    if ($TargetRps -gt 0) { $runArgs += @('-e', "SPRINGPY_TARGET_RPS=$TargetRps") }
    if ($MaxVus -gt 0) { $runArgs += @('-e', "SPRINGPY_MAX_VUS=$MaxVus") }
    $runArgs += @('k6')

    Invoke-Docker $runArgs
    Write-Host "Load test passed. Result: $(Join-Path $resultsDir "$Profile-$Workload-$timestamp.json")"
}
finally {
    Remove-Item Env:APP_WORKERS -ErrorAction SilentlyContinue
    if ($startedBenchmark -and -not $KeepApp) {
        & docker compose -p $projectName -f $composeFile down --remove-orphans
    }
}
