param (
    [int]$Days = 7
)

$loggedUser = ""
try {
    $loggedUser = (Get-CimInstance Win32_ComputerSystem).UserName
    if (-not $loggedUser) {
        $loggedUser = (Get-Process -IncludeUserName -Name explorer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty UserName -Unique | Select-Object -First 1)
    }
} catch {}

$cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
$diagReport = @{
    computer_name = $env:COMPUTERNAME
    serial_number = (Get-CimInstance Win32_BIOS).SerialNumber
    manufacturer = if ($cs.Manufacturer) { $cs.Manufacturer } else { "Generic" }
    model = if ($cs.Model) { $cs.Model } else { "Generic Model" }
    cpu = (Get-CimInstance Win32_Processor).Name
    ram_gb = [math]::Round(((Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum / 1GB), 1)
    logged_in_user = if ($loggedUser) { $loggedUser } else { "" }
    disks = @()
    bsod_dumps = @()
    critical_events = @()
    device_errors = @()
    anydesk_id = ""
    mac_address = ""
}

# Pegar MAC Address da interface de rede ativa
try {
    $activeNet = Get-NetAdapter | Where-Object { $_.Status -eq "Up" -and $_.MacAddress } | Select-Object -First 1
    if ($activeNet) {
        $diagReport.mac_address = $activeNet.MacAddress
    }
} catch {}

# 0. Checagem do AnyDesk ID
try {
    $anydeskId = ""
    $sysConf = "C:\ProgramData\AnyDesk\system.conf"
    if (Test-Path $sysConf) {
        $match = Get-Content -Path $sysConf -ErrorAction SilentlyContinue | Select-String "ad.anynet.id=(\d+)"
        if ($match) { $anydeskId = $match.Matches.Groups[1].Value }
    }
    
    if (-not $anydeskId) {
        $anydeskExe = "${env:ProgramFiles(x86)}\AnyDesk\AnyDesk.exe"
        if (-not (Test-Path $anydeskExe)) { $anydeskExe = "$env:ProgramFiles\AnyDesk\AnyDesk.exe" }
        if (Test-Path $anydeskExe) {
            $idOut = & $anydeskExe --get-id 2>$null
            if ($idOut -match "\d+") { 
                $anydeskId = [regex]::Match($idOut, "\d+").Value 
            }
        }
    }
    
    if ($anydeskId) { $diagReport.anydesk_id = $anydeskId }
} catch {}

# 1. Checagem de Saúde de Discos Físicos (S.M.A.R.T)
try {
    $disks = Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, MediaType, OperationalStatus, HealthStatus, Size
    foreach ($d in $disks) {
        $diagReport.disks += @{
            model = $d.FriendlyName
            type = $d.MediaType
            health = $d.HealthStatus
            operational = $d.OperationalStatus
            size_gb = [math]::Round($d.Size / 1GB, 1)
        }
    }
} catch {
    Write-Host "Erro ao ler discos: $_" -ForegroundColor Red
}

# 2. Checagem de Telas Azuis (BSOD Minidumps)
if (Test-Path "C:\Windows\Minidump") {
    $dumps = Get-ChildItem "C:\Windows\Minidump\*.dmp" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 5
    foreach ($dump in $dumps) {
        $diagReport.bsod_dumps += @{
            file = $dump.Name
            date = $dump.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            size_kb = [math]::Round($dump.Length / 1KB, 1)
        }
    }
}

# 3. Dispositivos com Erro no Gerenciador de Dispositivos (Drivers faltando/corrompidos)
try {
    # Ignoramos o código 45 (dispositivos não conectados / fantasmas) para não poluir o JSON
    $problemDevices = Get-PnpDevice | Where-Object { ($_.Status -eq "Error" -or $_.Problem -gt 0) -and $_.Problem -ne 45 }
    foreach ($dev in $problemDevices) {
        $diagReport.device_errors += @{
            name = $dev.FriendlyName
            class = $dev.Class
            status = $dev.Status
            problem_code = $dev.Problem
        }
    }
} catch {}

# 4. Logs Críticos e Erros Recentes do Windows Event Log (System e Application)
try {
    $startDate = (Get-Date).AddDays(-$Days)
    $events = Get-WinEvent -FilterHashtable @{LogName='System','Application'; Level=1,2; StartTime=$startDate} -MaxEvents 20 -ErrorAction SilentlyContinue
    foreach ($evt in $events) {
        $diagReport.critical_events += @{
            time = $evt.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            provider = $evt.ProviderName
            id = $evt.Id
            message = $evt.Message -replace "`r`n", " " | Select-Object -First 1
        }
    }
} catch {}

# Exporta JSON para o Ultron processar com o LLM
$jsonOutput = $diagReport | ConvertTo-Json -Depth 4
Write-Output $jsonOutput
