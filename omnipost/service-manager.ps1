# ==============================================================================
# VBL Law Chambers -- Social Automation Suite Service Manager
# Unified Graceful Start, Stop, Status, and Restart Controller
# ==============================================================================

param (
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status", "restart")]
    [string]$Action = "status"
)

$RootPath = $PSScriptRoot
$WebPath = Join-Path $RootPath "web"
$LegacyPidFile = Join-Path $WebPath ".web-portal.pid"

# --- Public URLs come from .env so there are no hardcoded hostnames here.
# Switching to production domains is a .env change only.
function Get-EnvValue {
    param ([string]$Key, [string]$Default)

    $envFile = Join-Path $RootPath ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            $trimmed = $line.Trim()
            if ($trimmed -and -not $trimmed.StartsWith('#') -and $trimmed.Contains('=')) {
                $idx = $trimmed.IndexOf('=')
                if ($trimmed.Substring(0, $idx).Trim() -eq $Key) {
                    $value = $trimmed.Substring($idx + 1).Trim()
                    if ($value) { return $value.TrimEnd('/') }
                }
            }
        }
    }
    return $Default
}

$WebPortalUrl  = Get-EnvValue -Key "WEB_PORTAL_PUBLIC_URL"  -Default "http://localhost:3300"
$N8nUrl        = Get-EnvValue -Key "N8N_PUBLIC_URL"         -Default "http://localhost:5678"
# Postiz and Temporal are gone: publishing runs natively from
# automation/web/publishing/. Probing them only ever reported DOWN.

function Write-BrandHeader {
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor DarkCyan
    Write-Host " [VBL LAW CHAMBERS] - ADVOCATE SOCIAL AUTOMATION SUITE" -ForegroundColor Yellow
    Write-Host "======================================================================" -ForegroundColor DarkCyan
    Write-Host ""
}

function Test-DockerDaemon {
    try {
        $out = & docker info 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Ensure-DockerRunning {
    Write-Host "[1/3] Checking Docker daemon status..." -ForegroundColor Cyan
    if (Test-DockerDaemon) {
        Write-Host "  -> Docker daemon is active and running." -ForegroundColor Green
        return $true
    }

    Write-Host "  -> Docker is not responding. Attempting to start Docker Desktop..." -ForegroundColor Yellow

    $dockerPaths = @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe",
        "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )

    $dockerExe = $null
    foreach ($p in $dockerPaths) {
        if (Test-Path $p) {
            $dockerExe = $p
            break
        }
    }

    if ($dockerExe) {
        Start-Process $dockerExe -WindowStyle Minimized
        Write-Host "  -> Launched: $dockerExe" -ForegroundColor Cyan
        Write-Host "  -> Waiting for Docker daemon to become ready (up to 90 seconds)..." -ForegroundColor Cyan
        
        $timeout = 90
        $elapsed = 0
        while ($elapsed -lt $timeout) {
            Start-Sleep -Seconds 3
            $elapsed += 3
            Write-Host -NoNewline "." -ForegroundColor Yellow
            if (Test-DockerDaemon) {
                Write-Host ""
                Write-Host "  -> Docker daemon is ready!" -ForegroundColor Green
                return $true
            }
        }
        Write-Host ""
        Write-Host "  -> Timed out waiting for Docker. Please verify Docker Desktop manually." -ForegroundColor Red
        return $false
    } else {
        Write-Host "  -> Could not locate Docker Desktop executable automatically." -ForegroundColor Red
        Write-Host "  -> Please launch Docker Desktop from your Start Menu." -ForegroundColor Yellow
        return $false
    }
}

function Clear-LegacyWebPortalProcesses {
    # The web portal now runs as the 'advocate-web-portal' container and is managed
    # by Docker Compose. This only cleans up stragglers from the old raw
    # `npm run dev` model (host processes on 3300/5173) so they can't shadow
    # the containerized portal by holding its port.
    param ([switch]$Quiet)

    if (Test-Path $LegacyPidFile) {
        $savedPid = (Get-Content $LegacyPidFile -ErrorAction SilentlyContinue)
        if ($savedPid) {
            Stop-Process -Id $savedPid.Trim() -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $LegacyPidFile -Force -ErrorAction SilentlyContinue
    }

    foreach ($p in @(3300, 5173)) {
        $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            $pidsToKill = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($procId in $pidsToKill) {
                # Docker's port proxy owns the port for containerized services -
                # only reap real node.exe leftovers from the legacy dev workflow.
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($procId -gt 0 -and $proc -and $proc.ProcessName -eq 'node') {
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                    if (-not $Quiet) {
                        Write-Host "  -> Cleared legacy host process on port $p (PID: $procId)." -ForegroundColor DarkGray
                    }
                }
            }
        }
    }
}

function Start-Services {
    Write-BrandHeader
    Write-Host "Starting all automation services gracefully..." -ForegroundColor Green
    Write-Host ""

    # 1. Docker
    $dockerOk = Ensure-DockerRunning
    if (-not $dockerOk) {
        Write-Host "  -> Cannot continue: Docker daemon is offline." -ForegroundColor Red
        return
    }

    # 2. Clear any leftovers from the old non-containerized web portal
    Write-Host ""
    Write-Host "[2/3] Clearing legacy host processes (pre-container web portal)..." -ForegroundColor Cyan
    Clear-LegacyWebPortalProcesses
    Write-Host "  -> Clear." -ForegroundColor Green

    # 3. Entire stack, web portal included, through Docker Compose
    Write-Host ""
    Write-Host "[3/3] Launching the stack (Web Portal + n8n)..." -ForegroundColor Cyan
    Push-Location $RootPath
    & docker compose up -d --build
    $composeExit = $LASTEXITCODE
    Pop-Location

    if ($composeExit -eq 0) {
        Write-Host "  -> All containers started." -ForegroundColor Green
    } else {
        Write-Host "  -> docker compose exited with code $composeExit. Check output above." -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "Waiting 8 seconds for services to initialize..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 8

    Show-Status
}

function Stop-Services {
    Write-BrandHeader
    Write-Host "Stopping all automation services gracefully..." -ForegroundColor Yellow
    Write-Host ""

    # 1. Clear leftovers from the old non-containerized web portal
    Write-Host "[1/2] Clearing legacy host processes (pre-container web portal)..." -ForegroundColor Cyan
    Clear-LegacyWebPortalProcesses
    Write-Host "  -> Clear." -ForegroundColor Green

    # 2. Stop the whole stack, web portal included
    Write-Host ""
    Write-Host "[2/2] Stopping all containers (Web Portal, n8n)..." -ForegroundColor Cyan
    if (Test-DockerDaemon) {
        Push-Location $RootPath
        & docker compose stop
        Pop-Location
        Write-Host "  -> All Docker containers stopped gracefully." -ForegroundColor Green
    } else {
        Write-Host "  -> Docker daemon is offline. No active containers to stop." -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host " All services stopped cleanly. Zero orphaned processes." -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Green
}

function Test-Endpoint {
    param (
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSec = 3
    )

    try {
        $res = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        if ($res.StatusCode -ge 200 -and $res.StatusCode -lt 400) {
            Write-Host "  [ONLINE]  " -NoNewline -ForegroundColor Green
            Write-Host "$Name " -NoNewline -ForegroundColor White
            Write-Host "($Url)" -ForegroundColor Cyan
            return $true
        }
    } catch {
        # Endpoint offline
    }
    Write-Host "  [OFFLINE] " -NoNewline -ForegroundColor Red
    Write-Host "$Name " -NoNewline -ForegroundColor White
    Write-Host "($Url)" -ForegroundColor DarkGray
    return $false
}

function Show-Status {
    Write-BrandHeader
    Write-Host "--- ACTIVE SERVICE HEALTH ---" -ForegroundColor Yellow
    Write-Host ""

    $null = Test-Endpoint -Name "Advocate Content Portal" -Url $WebPortalUrl
    $null = Test-Endpoint -Name "Content Portal API"      -Url "$WebPortalUrl/api/health"
    $null = Test-Endpoint -Name "n8n Workflow Automation" -Url $N8nUrl

    Write-Host ""
    Write-Host "--- DOCKER CONTAINER STATUS ---" -ForegroundColor Yellow
    if (Test-DockerDaemon) {
        & docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    } else {
        Write-Host "  Docker daemon is currently offline." -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor DarkCyan
    Write-Host " Quick Access Links:" -ForegroundColor Yellow
    Write-Host "  - Content Publisher: $WebPortalUrl" -ForegroundColor White
    Write-Host "  - n8n Automations:   $N8nUrl" -ForegroundColor White
    Write-Host "======================================================================" -ForegroundColor DarkCyan
    Write-Host ""
}

# --- Router ---
switch ($Action.ToLower()) {
    "start"   { Start-Services }
    "stop"    { Stop-Services }
    "restart" { Stop-Services; Start-Sleep -Seconds 2; Start-Services }
    "status"  { Show-Status }
    default   { Show-Status }
}
