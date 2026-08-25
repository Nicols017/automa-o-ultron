<#
.SYNOPSIS
    Bootstrap Universal - Ultron Automation Client
.DESCRIPTION
    Coleta informacoes de hardware, identifica o equipamento por Service Tag / Serial Number,
    registra o host no Ultron Server e inicia a esteira de automacao/diagnostico de qualquer lugar
    (Bancada, Wi-Fi, VPN, Filiais ou Home Office), sem depender de porta fisica de switch.
.EXAMPLE
    irm http://192.168.57.43:7000/bootstrap.ps1 | iex
    ou
    .\Bootstrap-Ultron.ps1 -UltronServerUrl "http://192.168.57.43:7000" -ClientId "cliente_padrao" -AutoRun
#>

[CmdletBinding()]
param(
    [string]$UltronServerUrl = "http://192.168.57.43:7000",
    [string]$ClientId = "cliente_padrao",
    [string]$TechUserId = "nicolas",
    [switch]$AutoRun = $true
)

$ErrorActionPreference = "Continue"

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "      🤖 ULTRON ANYWHERE - INICIALIZADOR DE CLIENTE   " -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# 1. Coleta de Metadados de Identificacao (Chave primaria: Service Tag / Serial)
Write-Host "[*] Coletando informacoes de hardware e rede..." -ForegroundColor Yellow

$bios = Get-CimInstance -ClassName Win32_BIOS -ErrorAction SilentlyContinue
$serialNumber = if ($bios -and $bios.SerialNumber -and $bios.SerialNumber.Trim() -ne "") {
    $bios.SerialNumber.Trim()
} else {
    "SERIAL-" + (Get-Random -Minimum 100000 -Maximum 999999)
}

$cs = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction SilentlyContinue
$computerName = if ($cs.Name) { $cs.Name } else { $env:COMPUTERNAME }
$manufacturer = if ($cs.Manufacturer) { $cs.Manufacturer } else { "Generic" }
$model = if ($cs.Model) { $cs.Model } else { "Generic Model" }

# Coleta de IP e MAC ativo
$netAdapter = Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1
if (-not $netAdapter) {
    $netAdapter = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1
}

$macAddress = if ($netAdapter) { $netAdapter.MacAddress } else { "00:00:00:00:00:00" }

$ipAddress = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $netAdapter.InterfaceAlias -ErrorAction SilentlyContinue |
              Where-Object { $_.IPAddress -notlike "169.254*" -and $_.IPAddress -ne "127.0.0.1" } |
              Select-Object -First 1).IPAddress

if (-not $ipAddress) {
    $ipAddress = (Test-Connection -ComputerName $env:COMPUTERNAME -Count 1).IPV4Address.IPAddressToString
}

Write-Host "    -> Serial / Service Tag: $serialNumber" -ForegroundColor Green
Write-Host "    -> Modelo:               $manufacturer $model" -ForegroundColor Green
Write-Host "    -> Hostname:             $computerName" -ForegroundColor Green
Write-Host "    -> IP Atual:             $ipAddress" -ForegroundColor Green
Write-Host "    -> MAC Address:          $macAddress" -ForegroundColor Green

# 2. Habilitacao e Ajuste do WinRM (Para permitir conexao do Ultron)
Write-Host "[*] Configurando servico WinRM para conexao remota..." -ForegroundColor Yellow
try {
    Enable-PSRemoting -Force -SkipNetworkProfileCheck -ErrorAction SilentlyContinue
    Set-Service -Name WinRM -StartupType Automatic -ErrorAction SilentlyContinue
    Start-Service -Name WinRM -ErrorAction SilentlyContinue
    
    # Habilita autenticacao basica e trafego nao criptografado na LAN de laboratorio/VPN
    Set-Item -Path WSMan:\localhost\Service\Auth\Basic -Value $true -Force -ErrorAction SilentlyContinue
    Set-Item -Path WSMan:\localhost\Service\AllowUnencrypted -Value $true -Force -ErrorAction SilentlyContinue
    
    # Abre regras no Firewall do Windows
    netsh advfirewall firewall set rule group="Windows Remote Management" new enable=yes | Out-Null
    netsh advfirewall firewall add rule name="WinRM 5985" dir=in action=allow protocol=TCP localport=5985 | Out-Null
    Write-Host "    -> WinRM configurado com sucesso!" -ForegroundColor Green
} catch {
    Write-Warning "    -> Nao foi possivel ajustar todas as regras do WinRM. Continuando..."
}

# 3. Notificacao e Registro no Servidor Ultron
$payload = @{
    serial = $serialNumber
    ip = $ipAddress
    mac = $macAddress
    computer_name = $computerName
    status = "READY_FOR_PIPELINE"
    client_id = $ClientId
    auto_run = [bool]$AutoRun
} | ConvertTo-Json

Write-Host "[*] Registrando maquina no Ultron Server ($UltronServerUrl)..." -ForegroundColor Yellow

try {
    $endpoint = "$UltronServerUrl/api/v1/mdt/completed"
    $response = Invoke-RestMethod -Uri $endpoint -Method Post -Body $payload -ContentType "application/json" -TimeoutSec 15
    Write-Host "    -> Registro concluido com sucesso!" -ForegroundColor Green
    Write-Host "    -> Resposta do Servidor: $($response | ConvertTo-Json -Compress)" -ForegroundColor Cyan
} catch {
    Write-Host "⚠️ Falha ao contactar o servidor Ultron em $UltronServerUrl. Erro: $_" -ForegroundColor Red
}

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "      ✅ PROCESSO DE BOOTSTRAP FINALIZADO            " -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan
