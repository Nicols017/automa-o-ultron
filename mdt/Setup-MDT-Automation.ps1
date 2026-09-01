<#
.SYNOPSIS
    Configurador Automático do MDT Deployment Share para Ultron Lab Automation
.DESCRIPTION
    Copia os arquivos de configuração (CustomSettings.ini, Bootstrap.ini) e o script
    Notify-Ultron.ps1 para dentro do Deployment Share do MDT no servidor 192.168.57.87.
#>

param (
    [string]$DeploymentSharePath = "D:\DeploymentShare$",
    [string]$UltronServerUrl = "http://192.168.57.43:7000/api/v1/mdt/completed"
)

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host " 🤖 ULTRON LAB - CONFIGURADOR DE DEPLOYMENT SHARE MDT" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

if (-not (Test-Path $DeploymentSharePath)) {
    Write-Host "⚠️ Caminho $DeploymentSharePath não encontrado. Tentando C:\DeploymentShare$..." -ForegroundColor Yellow
    if (Test-Path "C:\DeploymentShare$") {
        $DeploymentSharePath = "C:\DeploymentShare$"
    } else {
        Write-Error "Deployment Share não encontrado. Especifique o caminho correto via -DeploymentSharePath."
        return
    }
}

$controlDir = Join-Path $DeploymentSharePath "Control"
$scriptsDir = Join-Path $DeploymentSharePath "Scripts"

# 1. Copia Notify-Ultron.ps1 para a pasta Scripts do MDT
$currentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$notifyScript = Join-Path $currentDir "scripts\Notify-Ultron.ps1"

if (Test-Path $notifyScript) {
    Copy-Item -Path $notifyScript -Destination (Join-Path $scriptsDir "Notify-Ultron.ps1") -Force
    Write-Host "✅ Notify-Ultron.ps1 copiado para $scriptsDir" -ForegroundColor Green
} else {
    Write-Warning "Notify-Ultron.ps1 não encontrado na pasta local."
}

# 2. Atualiza CustomSettings.ini
$customSettingsSrc = Join-Path $currentDir "CustomSettings.ini"
if (Test-Path $customSettingsSrc) {
    Copy-Item -Path $customSettingsSrc -Destination (Join-Path $controlDir "CustomSettings.ini") -Force
    Write-Host "✅ CustomSettings.ini atualizado em $controlDir" -ForegroundColor Green
}

# 3. Atualiza Bootstrap.ini
$bootstrapSrc = Join-Path $currentDir "Bootstrap.ini"
if (Test-Path $bootstrapSrc) {
    Copy-Item -Path $bootstrapSrc -Destination (Join-Path $controlDir "Bootstrap.ini") -Force
    Write-Host "✅ Bootstrap.ini atualizado em $controlDir" -ForegroundColor Green
}

Write-Host "`n🎉 MDT configurado com sucesso para operar com o Ultron!" -ForegroundColor Cyan
Write-Host "📌 Na sua Task Sequence do MDT, adicione no grupo 'State Restore' (última etapa):" -ForegroundColor Yellow
Write-Host "   -> Add > General > Run PowerShell Script" -ForegroundColor White
Write-Host "   -> PowerShell script: %SCRIPTROOT%\Notify-Ultron.ps1" -ForegroundColor White
Write-Host "=====================================================" -ForegroundColor Cyan
