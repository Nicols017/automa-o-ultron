<#
.SYNOPSIS
    Script de Instalação e Configuração Automática do Servidor MDT (Zero-Touch) para o Ultron Lab.
.DESCRIPTION
    Este script deve ser executado no Servidor Windows (ex: 192.168.57.87). Ele realiza:
    1. Instalação da Role WDS (Windows Deployment Services)
    2. Download e Instalação Silenciosa do Windows ADK (Assessment and Deployment Kit)
    3. Download e Instalação Silenciosa do Windows ADK WinPE Add-on
    4. Download e Instalação Silenciosa do Microsoft Deployment Toolkit (MDT)
    5. Preparação da estrutura de pastas base.

    AVISO: Requer execução com privilégios de Administrador e internet no servidor.
#>

param(
    [string]$DownloadDir = "C:\MDT_InstallFiles",
    [string]$DeploymentSharePath = "D:\DeploymentShare`$"
)

# Verifica privilégios de administrador
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Por favor, execute este script como Administrador!"
    exit
}

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "🚀 INICIANDO INSTALAÇÃO DO AMBIENTE MDT (ULTRON LAB)" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# Cria diretório de downloads temporário
if (-not (Test-Path $DownloadDir)) {
    New-Item -ItemType Directory -Path $DownloadDir | Out-Null
}

# 1. Instalar WDS (Windows Deployment Services)
Write-Host "`n[1/4] Instalando Windows Deployment Services (WDS)..." -ForegroundColor Yellow
$wds = Get-WindowsFeature -Name WDS
if ($wds.InstallState -ne "Installed") {
    Install-WindowsFeature -Name WDS -IncludeManagementTools | Out-Null
    Write-Host "✅ WDS Instalado." -ForegroundColor Green
} else {
    Write-Host "✅ WDS já estava instalado." -ForegroundColor Green
}

# Configurações de URLs de Download (Padrão para Windows 11 ADK ou compatível)
$adkUrl = "https://go.microsoft.com/fwlink/?linkid=2243390"
$adkPeUrl = "https://go.microsoft.com/fwlink/?linkid=2243391"
$mdtUrl = "https://download.microsoft.com/download/b/3/c/b3c53689-09f8-48b4-be7c-a4593450c26c/MicrosoftDeploymentToolkit_x64.msi"

$adkExe = "$DownloadDir\adksetup.exe"
$adkPeExe = "$DownloadDir\adkwinpesetup.exe"
$mdtMsi = "$DownloadDir\mdt.msi"

# 2. Download e Instalação do ADK
Write-Host "`n[2/4] Baixando e Instalando o Windows ADK..." -ForegroundColor Yellow
if (-not (Test-Path $adkExe)) {
    Invoke-WebRequest -Uri $adkUrl -OutFile $adkExe -UseBasicParsing
}
Write-Host "Executando instalação silenciosa do ADK (isso pode demorar alguns minutos)..."
Start-Process -FilePath $adkExe -ArgumentList "/quiet /norestart /features OptionId.DeploymentTools OptionId.WindowsPreinstallationEnvironment" -Wait
Write-Host "✅ ADK Instalado." -ForegroundColor Green

# 3. Download e Instalação do ADK WinPE Add-on
Write-Host "`n[3/4] Baixando e Instalando o Windows ADK WinPE Add-on..." -ForegroundColor Yellow
if (-not (Test-Path $adkPeExe)) {
    Invoke-WebRequest -Uri $adkPeUrl -OutFile $adkPeExe -UseBasicParsing
}
Write-Host "Executando instalação silenciosa do WinPE Add-on (isso pode demorar alguns minutos)..."
Start-Process -FilePath $adkPeExe -ArgumentList "/quiet /norestart" -Wait
Write-Host "✅ WinPE Add-on Instalado." -ForegroundColor Green

# 4. Download e Instalação do MDT
Write-Host "`n[4/4] Baixando e Instalando o Microsoft Deployment Toolkit (MDT)..." -ForegroundColor Yellow
if (-not (Test-Path $mdtMsi)) {
    Invoke-WebRequest -Uri $mdtUrl -OutFile $mdtMsi -UseBasicParsing
}
Write-Host "Executando instalação silenciosa do MDT..."
Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$mdtMsi`" /quiet /norestart" -Wait
Write-Host "✅ MDT Instalado." -ForegroundColor Green

# Limpeza e Aviso Final
Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host "🎉 PRÉ-REQUISITOS INSTALADOS COM SUCESSO!" -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "O que fazer agora no Servidor Windows:"
Write-Host "1. Abra o aplicativo 'Deployment Workbench' no menu iniciar."
Write-Host "2. Crie um novo Deployment Share no caminho: $DeploymentSharePath"
Write-Host "3. Importe a ISO do seu Windows (Operating Systems)."
Write-Host "4. Crie uma Task Sequence Padrão para instalar esse Windows."
Write-Host "5. Execute o script 'Setup-MDT-Automation.ps1' do repositório para injetar a automação."
Write-Host "6. Atualize o Deployment Share e adicione a imagem WinPE no console do WDS."
Write-Host "=====================================================" -ForegroundColor Cyan
