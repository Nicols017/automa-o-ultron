# Script Mestre de Preparacao Padrão de Bancada - Pense Rede
param (
    [string]$MilvusToken = "",
    [string]$ClientName = "Cliente Pense Rede",
    [string]$MdtServer = "192.168.57.87",
    [bool]$ActivateOfficeWin = $true
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 🤖 ULTRON LAB - INICIANDO PREPARACAO DA MAQUINA" -ForegroundColor Cyan
Write-Host " Cliente: $ClientName" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Instalação do AnyDesk via Winget / Direct
Write-Host "`n[1/5] Instalando AnyDesk..." -ForegroundColor Yellow
try {
    winget install --id AnyDeskSoftwareGmbH.AnyDesk --exact --silent --accept-package-agreements --accept-source-agreements
    Write-Host "✅ AnyDesk instalado com sucesso!" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Erro ao instalar AnyDesk via Winget: $_" -ForegroundColor Red
}

# Captura do AnyDesk ID gerado
Start-Sleep -Seconds 3
$anydeskId = ""
$systemConf = "C:\ProgramData\AnyDesk\system.conf"
if (Test-Path $systemConf) {
    $matched = Get-Content $systemConf -ErrorAction SilentlyContinue | Where-Object { $_ -match "ad\.anydesk\.id\s*=\s*(\d+)" }
    if ($matched -and $matched -match "ad\.anydesk\.id\s*=\s*(\d+)") {
        $anydeskId = $matches[1]
    }
}
if (-not $anydeskId) {
    try {
        $anydeskExe = "${env:ProgramFiles(x86)}\AnyDesk\AnyDesk.exe"
        if (-not (Test-Path $anydeskExe)) { $anydeskExe = "$env:ProgramFiles\AnyDesk\AnyDesk.exe" }
        if (Test-Path $anydeskExe) {
            $idOut = & $anydeskExe --get-id 2>$null
            if ($idOut -match "^\d+$") { $anydeskId = $idOut.Trim() }
        }
    } catch {}
}
if ($anydeskId) {
    Write-Host "ANYDESK_ID:$anydeskId" -ForegroundColor Cyan
    Write-Host "🔑 AnyDesk ID identificado: $anydeskId" -ForegroundColor Green
} else {
    Write-Host "ANYDESK_ID:NÃO_DETECTADO" -ForegroundColor Yellow
}

# 2. Instalação do Microsoft Office 365 / 2021
Write-Host "`n[2/5] Instalando Microsoft Office..." -ForegroundColor Yellow
try {
    winget install --id Microsoft.Office --silent --accept-package-agreements --accept-source-agreements
    Write-Host "✅ Office instalado com sucesso!" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Erro ao instalar Office via Winget, tentando instalador local..." -ForegroundColor Red
}

# 3. Ativação do Windows e Office via Massgrave (MAS)
if ($ActivateOfficeWin) {
    Write-Host "`n[3/5] Executando Ativação (Massgrave MAS)..." -ForegroundColor Yellow
    try {
        # Execução silenciosa do script Massgrave (HWID para Windows + Ohook para Office)
        $masScript = "irm https://get.activated.win | iex"
        Invoke-Expression $masScript
        Write-Host "✅ Processo de Ativação concluído!" -ForegroundColor Green
    } catch {
        Write-Host "⚠️ Erro na ativação automática: $_" -ForegroundColor Red
    }
}

# 4. Instalação do Agente Milvus (MSI Específico do Cliente no Compartilhamento)
Write-Host "`n[4/5] Instalando Agente Milvus para $ClientName..." -ForegroundColor Yellow

$cleanClientName = $ClientName -replace '[^a-zA-Z0-9_]', ''
$localMsiPath = "\\$MdtServer\MilvusAgents\Milvus_$cleanClientName.msi"
$fallbackMsiPath = "\\$MdtServer\DeploymentShare$\Milvus\Milvus_$cleanClientName.msi"

if (Test-Path $localMsiPath) {
    Write-Host "Instalando MSI local de $localMsiPath..." -ForegroundColor Green
    Start-Process msiexec.exe -ArgumentList "/i `"$localMsiPath`" /qn /norestart" -Wait
    Write-Host "✅ Agente Milvus instalado com sucesso a partir do servidor local!" -ForegroundColor Green
} elseif (Test-Path $fallbackMsiPath) {
    Write-Host "Instalando MSI de $fallbackMsiPath..." -ForegroundColor Green
    Start-Process msiexec.exe -ArgumentList "/i `"$fallbackMsiPath`" /qn /norestart" -Wait
    Write-Host "✅ Agente Milvus instalado com sucesso a partir do DeploymentShare!" -ForegroundColor Green
} elseif ($MilvusToken) {
    Write-Host "MSI local não encontrado. Baixando via Token online..." -ForegroundColor Yellow
    try {
        $milvusUrl = "https://milvus.com.br/download/agent?token=$MilvusToken"
        $installerPath = "$env:TEMP\MilvusAgentSetup.exe"
        Invoke-WebRequest -Uri $milvusUrl -OutFile $installerPath
        Start-Process -FilePath $installerPath -ArgumentList "/verysilent /suppressmsgboxes /token=$MilvusToken" -Wait
        Write-Host "✅ Agente Milvus instalado via Token web!" -ForegroundColor Green
    } catch {
        Write-Host "⚠️ Erro ao baixar Milvus via Web: $_" -ForegroundColor Red
    }
} else {
    Write-Host "⚠️ Nenhum instalador MSI encontrado no servidor para $ClientName." -ForegroundColor Yellow
}

# 5. Otimizações de Sistema e Ativação do RDP
Write-Host "`n[5/5] Aplicando otimizações finais de Bancada..." -ForegroundColor Yellow
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Host "✅ RDP Ativado e Firewall configurado!" -ForegroundColor Green

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host " 🎉 ULTRON - PREPARACAO CONCLUIDA COM SUCESSO!" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
