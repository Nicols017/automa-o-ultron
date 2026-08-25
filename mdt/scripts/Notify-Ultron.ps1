# Script acionado no final da Task Sequence do MDT
param (
    [string]$UltronServerUrl = "http://192.168.57.43:7000/api/v1/mdt/completed"
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 🤖 ULTRON - NOTIFICANDO FINALIZACAO DO MDT" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Habilita e Configura WinRM de Forma Irrestrita para a Bancada
try {
    Enable-PSRemoting -Force -SkipNetworkProfileCheck
    Set-Service WinRM -StartupType Automatic
    Start-Service WinRM
    
    # Permite autenticação básica e tráfego na rede interna
    Set-Item -Path "WSMan:\localhost\Service\Auth\Basic" -Value $true -Force -ErrorAction SilentlyContinue
    Set-Item -Path "WSMan:\localhost\Service\AllowUnencrypted" -Value $true -Force -ErrorAction SilentlyContinue
    Set-Item -Path "WSMan:\localhost\Client\TrustedHosts" -Value "*" -Force -ErrorAction SilentlyContinue
    
    # Libera regras no Firewall do Windows
    Enable-NetFirewallRule -DisplayGroup "Windows Remote Management" -ErrorAction SilentlyContinue
    Enable-NetFirewallRule -DisplayGroup "Remote Desktop" -ErrorAction SilentlyContinue
    Write-Host "✅ WinRM e RDP configurados e liberados com sucesso!" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Alerta na configuração do WinRM: $_" -ForegroundColor Yellow
}

# 2. Coleta Metadados da Máquina
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127*" -and $_.IPAddress -notlike "169.254*" }).IPAddress | Select-Object -First 1
$serial = (Get-CimInstance Win32_BIOS).SerialNumber
$mac = (Get-NetAdapter | Where-Object Status -eq "Up").MacAddress | Select-Object -First 1
$computerName = $env:COMPUTERNAME

$payload = @{
    serial        = $serial
    ip            = $ip
    mac           = $mac
    computer_name = $computerName
    status        = "MDT_FINISHED"
} | ConvertTo-Json

# 3. Envia Webhook ao Ultron
try {
    Write-Host "Enviando notificação para $UltronServerUrl..." -ForegroundColor Yellow
    $response = Invoke-RestMethod -Uri $UltronServerUrl -Method Post -Body $payload -ContentType "application/json" -TimeoutSec 10
    Write-Host "✅ Ultron notificado com sucesso: $($response.message)" -ForegroundColor Green
} catch {
    Write-Host "❌ Erro ao notificar Ultron: $_" -ForegroundColor Red
}
