# Script de Instalação e Pré-Configuração do TrueConf Client
param (
    [string]$ServerDomain = "serra.extinbras.com.br"
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 📹 ULTRON - CONFIGURANDO TRUECONF CLIENT ($ServerDomain)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Download do instalador diretamente do servidor do cliente se necessário
$installerPath = "$env:TEMP\TrueConfClientSetup.exe"
$downloadUrl = "https://$ServerDomain/guest/download/windows"

Write-Host "Baixando TrueConf Client de https://$ServerDomain..." -ForegroundColor Yellow
try {
    # Tenta baixar do servidor proprio do cliente (ja vem pre-configurado)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -ErrorAction Stop
    Write-Host "✅ Download concluido a partir do servidor do cliente!" -ForegroundColor Green
    
    # Instalação silenciosa
    Start-Process -FilePath $installerPath -ArgumentList "/verysilent /suppressmsgboxes" -Wait
} catch {
    Write-Host "⚠️ Não foi possivel baixar do DNS especifico. Instalando via Winget..." -ForegroundColor Red
    winget install --id TrueConf.TrueConfClient --silent --accept-package-agreements --accept-source-agreements
}

# 2. Pré-Configuração Automática do Servidor no Registro do Windows (evita digitação manual pelo usuário)
Write-Host "`nPré-configurando servidor no Registro do Windows ($ServerDomain)..." -ForegroundColor Yellow

$regPaths = @(
    "HKCU:\Software\TrueConf\Client",
    "HKLM:\SOFTWARE\TrueConf\Client",
    "HKLM:\SOFTWARE\WOW6432Node\TrueConf\Client"
)

foreach ($regPath in $regPaths) {
    if (-not (Test-Path $regPath)) {
        New-Item -Path $regPath -Force | Out-Null
    }
    Set-ItemProperty -Path $regPath -Name "Server" -Value $ServerDomain -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $regPath -Name "ServerAddress" -Value $ServerDomain -ErrorAction SilentlyContinue
}

Write-Host "✅ TrueConf Client instalado e apontado automaticamente para $ServerDomain!" -ForegroundColor Green
Write-Host " O usuário só precisará digitar Login/Senha do AD ao abrir o app." -ForegroundColor Green
