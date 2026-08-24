# Script de Entrada em Domínio com Suporte a IP Estático, DNS e Credenciais Dinâmicas - Ultron
param (
    [string]$DomainName = "",
    [string]$DomainUser = "",
    [string]$DomainPassword = "",
    [string]$DnsServer = "",
    [string]$StaticIp = "",
    [string]$SubnetMask = "255.255.255.0",
    [string]$Gateway = "",
    [string]$OUPath = "",
    [string]$VpnType = "none",
    [string]$VpnConfigFile = ""
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 🏢 ULTRON - CONFIGURACAO DE REDE & DOMINIO ($DomainName)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

if (-not $DomainName) {
    Write-Host "⚠️ Nenhum domínio especificado. Etapa ignorada." -ForegroundColor Yellow
    exit 0
}

# 1. Identifica a Placa de Rede Ativa
$activeAdapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
if (-not $activeAdapter) {
    Write-Host "❌ Nenhuma placa de rede ativa encontrada para configuração." -ForegroundColor Red
    exit 1
}

Write-Host "Placa de rede identificada: $($activeAdapter.Name) (InterfaceIndex: $($activeAdapter.InterfaceIndex))" -ForegroundColor Gray

# 2. Configura IP Estático e Gateway na Placa de Rede (se fornecido)
if ($StaticIp) {
    Write-Host "Configurando IP Estático ($StaticIp / $SubnetMask)..." -ForegroundColor Yellow
    try {
        # Converte máscara para prefix length se necessário (ex: 255.255.255.0 -> 24)
        $prefix = 24
        if ($SubnetMask -eq "255.255.0.0") { $prefix = 16 }
        elseif ($SubnetMask -eq "255.0.0.0") { $prefix = 8 }
        elseif ($SubnetMask -eq "255.255.255.128") { $prefix = 25 }
        elseif ($SubnetMask -eq "255.255.255.192") { $prefix = 26 }

        # Remove IPs anteriores e aplica novo
        Remove-NetIPAddress -InterfaceIndex $activeAdapter.InterfaceIndex -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
        
        if ($Gateway) {
            New-NetIPAddress -InterfaceIndex $activeAdapter.InterfaceIndex -IPAddress $StaticIp -PrefixLength $prefix -DefaultGateway $Gateway -ErrorAction Stop | Out-Null
            Write-Host "✅ IP Estático ($StaticIp) e Gateway ($Gateway) configurados!" -ForegroundColor Green
        } else {
            New-NetIPAddress -InterfaceIndex $activeAdapter.InterfaceIndex -IPAddress $StaticIp -PrefixLength $prefix -ErrorAction Stop | Out-Null
            Write-Host "✅ IP Estático ($StaticIp) configurado!" -ForegroundColor Green
        }
    } catch {
        Write-Host "⚠️ Alerta ao configurar IP estático: $_" -ForegroundColor Yellow
    }
}

# 3. Ajuste de Servidor DNS do Cliente / Empresa
if ($DnsServer) {
    Write-Host "Configurando Servidor DNS primário da empresa ($DnsServer)..." -ForegroundColor Yellow
    try {
        Set-DnsClientServerAddress -InterfaceIndex $activeAdapter.InterfaceIndex -ServerAddresses $DnsServer -ErrorAction Stop
        Write-Host "✅ Servidor DNS ($DnsServer) configurado na placa de rede!" -ForegroundColor Green
    } catch {
        Write-Host "⚠️ Erro ao ajustar DNS: $_" -ForegroundColor Red
    }
}

# 4. Conexão via VPN se necessário
if ($VpnType -eq "openvpn" -and (Test-Path $VpnConfigFile)) {
    Write-Host "Disponibilizando conexão VPN via OpenVPN..." -ForegroundColor Yellow
    Start-Process -FilePath "C:\Program Files\OpenVPN\bin\openvpn.exe" -ArgumentList "--config `"$VpnConfigFile`"" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# 5. Teste de Resolução e Conectividade com o Controlador de Domínio
Write-Host "Testando resolução do domínio $DomainName..." -ForegroundColor Yellow
$domainPing = Test-Connection -ComputerName $DomainName -Count 2 -Quiet

if (-not $domainPing) {
    Write-Host "⚠️ Não foi possível alcançar o controlador de domínio $DomainName." -ForegroundColor Red
    Write-Host " Verifique se o IP do DNS ($DnsServer) ou a rota/VPN com a empresa está acessível." -ForegroundColor Yellow
}

# 6. Executa Entrada no Domínio com Credenciais Fornecidas
if ($DomainUser -and $DomainPassword) {
    Write-Host "Adicionando computador ao domínio $DomainName com o usuário $DomainUser..." -ForegroundColor Yellow
    $secPass = ConvertTo-SecureString $DomainPassword -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential($DomainUser, $secPass)
    
    try {
        if ($OUPath) {
            Write-Host "Aplicando Unidade Organizacional (OU): $OUPath" -ForegroundColor Gray
            Add-Computer -DomainName $DomainName -Credential $cred -OUPath $OUPath -Force -ErrorAction Stop
        } else {
            Add-Computer -DomainName $DomainName -Credential $cred -Force -ErrorAction Stop
        }
        Write-Host "✅ Máquina inserida com sucesso no domínio $DomainName!" -ForegroundColor Green
    } catch {
        Write-Host "❌ Falha ao ingressar no domínio: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "⚠️ Credenciais de usuário/senha do AD não foram fornecidas. Etapa de ingresso não executada." -ForegroundColor Yellow
}
