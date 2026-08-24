# Script de Mapeamento de Pastas e Sistemas SPA / Radmin / TrueConf
param (
    [string]$ServerIP = "192.168.1.10", # IP do Servidor do Cliente
    [string]$DomainUser = "",
    [string]$DomainPass = ""
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 📁 ULTRON - CONFIGURANDO MAPEAMENTOS SPA & RADMIN" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# Mapeamentos de Unidades de Rede SPA
$spaMappings = @{
    "S:" = "\\$ServerIP\SPACRM"
    "T:" = "\\$ServerIP\SPACOM"
    "U:" = "\\$ServerIP\SPASRV"
    "V:" = "\\$ServerIP\SPAUTI"
    "W:" = "\\$ServerIP\SPADBA"
}

foreach ($drive in $spaMappings.Keys) {
    $sharePath = $spaMappings[$drive]
    Write-Host "Mapeando $drive -> $sharePath..." -ForegroundColor Yellow
    try {
        if ($DomainUser -and $DomainPass) {
            net use $drive $sharePath /user:$DomainUser $DomainPass /persistent:yes
        } else {
            net use $drive $sharePath /persistent:yes
        }
        Write-Host "✅ Mapeado $drive com sucesso!" -ForegroundColor Green
    } catch {
        Write-Host "⚠️ Erro ao mapear $drive: $_" -ForegroundColor Red
    }
}

# Instalação do Radmin VPN e TrueConf
Write-Host "`nInstalando Radmin VPN..." -ForegroundColor Yellow
try {
    winget install --id Famatech.RadminVPN --silent --accept-package-agreements --accept-source-agreements
    Write-Host "✅ Radmin VPN instalado!" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Erro ao instalar Radmin VPN via Winget." -ForegroundColor Red
}

Write-Host "`nInstalando TrueConf Client..." -ForegroundColor Yellow
try {
    winget install --id TrueConf.TrueConfClient --silent --accept-package-agreements --accept-source-agreements
    Write-Host "✅ TrueConf Client instalado!" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Erro ao instalar TrueConf Client via Winget." -ForegroundColor Red
}
