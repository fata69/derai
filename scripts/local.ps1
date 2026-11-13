[CmdletBinding()]
param(
    [ValidateSet('Setup', 'Preview', 'Demo', 'Snapshot', 'TestPostgres', 'Run', 'Stop')]
    [string]$Mode = 'Preview',
    [string]$At = '2026-11-13T11:37:20+07:00',
    [string]$VenvPath = '.venv'
)

$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$previousPath = Get-Location
$previousDatabaseUrl = $env:DATABASE_URL
$previousPassword = $env:PGPASSWORD
$previousTestDatabaseUrl = $env:TEST_DATABASE_URL

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Program (exit $LASTEXITCODE)"
    }
}

try {
    Set-Location -LiteralPath $projectPath
    $venvAbsolutePath = [IO.Path]::GetFullPath((Join-Path $projectPath $VenvPath))
    $pythonPath = Join-Path $venvAbsolutePath 'Scripts\python.exe'

    if ($Mode -eq 'Stop') {
        Invoke-Checked -Program docker -Arguments @('compose', '--profile', 'dev', 'stop', 'scheduler-dev', 'db')
        return
    }

    if ($Mode -eq 'Snapshot') {
        # Database target is this project's dev container; no connection from .env.
        Get-Content -Raw -LiteralPath 'scripts/export-jobs.sql' |
            docker compose --profile dev exec -T db psql -X -qAt -v ON_ERROR_STOP=1 `
                -v "tick_at=$At" -U derai_worker -d derai_scheduler_local -f -
        if ($LASTEXITCODE -ne 0) {
            throw "Local snapshot failed (exit $LASTEXITCODE)"
        }
        return
    }

    if ($Mode -eq 'Setup') {
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            Invoke-Checked -Program py -Arguments @('-3', '-m', 'venv', $venvAbsolutePath)
        }
        Invoke-Checked -Program $pythonPath -Arguments @('-m', 'pip', 'install', '-c', 'constraints.txt', '-e', '.[dev]')
        Write-Output 'Setup selesai. Jalankan .\scripts\local.ps1 Preview atau Demo.'
        return
    }

    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw 'Virtual environment belum tersedia. Jalankan .\scripts\local.ps1 Setup dahulu.'
    }

    if ($Mode -eq 'Preview') {
        Invoke-Checked -Program $pythonPath -Arguments @('-m', 'derai_scheduler', 'preview', '--topics', 'fixtures/topics.json', '--at', $At)
        return
    }

    if ($Mode -eq 'Demo') {
        Invoke-Checked -Program docker -Arguments @('compose', '--profile', 'dev', 'up', '-d', '--wait', 'db')
        $env:DATABASE_URL = 'postgresql+psycopg://derai_worker@127.0.0.1:55432/derai_scheduler_local'
        $env:PGPASSWORD = 'derai_local_worker'
        Write-Output 'Tick pertama; pada database baru menghasilkan processed=4.'
        Invoke-Checked -Program $pythonPath -Arguments @('-m', 'derai_scheduler', 'tick', '--at', $At)
        Write-Output 'Tick kedua pada jam sama; menghasilkan processed=0.'
        Invoke-Checked -Program $pythonPath -Arguments @('-m', 'derai_scheduler', 'tick', '--at', $At)
        Invoke-Checked -Program docker -Arguments @('compose', 'exec', '-T', 'db', 'psql', '-U', 'derai_local_admin', '-d', 'derai_scheduler_local', '-c', "SELECT name, status, data::json->>'query' AS query, data::json->>'scheduled_for' AS scheduled_for FROM records WHERE kind = 'job' ORDER BY name, query;")
        return
    }

    if ($Mode -eq 'TestPostgres') {
        Invoke-Checked -Program docker -Arguments @('compose', '--profile', 'dev', 'up', '-d', '--wait', 'db')
        Invoke-Checked -Program docker -Arguments @('compose', 'exec', '-T', 'db', 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'derai_local_admin', '-d', 'postgres', '-f', '/docker-entrypoint-initdb.d/003-tests.sql')
        $env:TEST_DATABASE_URL = 'postgresql+psycopg://derai_local_admin:derai_local_admin@127.0.0.1:55432/derai_scheduler_test'
        Invoke-Checked -Program $pythonPath -Arguments @('-m', 'pytest', '-m', 'postgres')
        return
    }

    if (-not $env:DATABASE_URL) {
        $env:DATABASE_URL = 'postgresql+psycopg://derai_worker@127.0.0.1:55432/derai_scheduler_local'
        $env:PGPASSWORD = 'derai_local_worker'
    }
    Invoke-Checked -Program $pythonPath -Arguments @('-m', 'derai_scheduler', 'run')
}
finally {
    $env:DATABASE_URL = $previousDatabaseUrl
    $env:PGPASSWORD = $previousPassword
    $env:TEST_DATABASE_URL = $previousTestDatabaseUrl
    Set-Location -LiteralPath $previousPath
}
