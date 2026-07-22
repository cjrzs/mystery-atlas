$ErrorActionPreference = "Stop"

$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logs = Join-Path $project ".logs"
New-Item -ItemType Directory -Force $logs | Out-Null

# Codex can provide both Path and PATH. Start-Process treats them as duplicate keys.
$pathValue = $env:PATH
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")

function Test-LocalPort {
    param([int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $attempt = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $attempt.AsyncWaitHandle.WaitOne(400)) {
            return $false
        }
        $client.EndConnect($attempt)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

$webProcess = $null
$apiProcess = $null

if (-not (Test-LocalPort 3100)) {
    $node = (Get-Command node.exe).Source
    $nextCli = Join-Path $project "apps\web\node_modules\next\dist\bin\next"
    $webProcess = Start-Process `
        -FilePath $node `
        -ArgumentList @("`"$nextCli`"", "dev", "--hostname", "127.0.0.1", "--port", "3100") `
        -WorkingDirectory (Join-Path $project "apps\web") `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "frontend-3100.log") `
        -RedirectStandardError (Join-Path $logs "frontend-3100.err.log") `
        -PassThru
}

if (-not (Test-LocalPort 8010)) {
    $python = Join-Path $project ".venv\Scripts\python.exe"
    $apiProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "mystery_atlas_api.main:app", "--host", "127.0.0.1", "--port", "8010") `
        -WorkingDirectory $project `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "api.log") `
        -RedirectStandardError (Join-Path $logs "api.err.log") `
        -PassThru
}

@{
    apiPid = if ($apiProcess) { $apiProcess.Id } else { $null }
    webPid = if ($webProcess) { $webProcess.Id } else { $null }
} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $logs "local-dev-processes.json")

Write-Output "Mystery Atlas local services started"
Write-Output "Web: http://127.0.0.1:3100"
Write-Output "API: http://127.0.0.1:8010/docs"
