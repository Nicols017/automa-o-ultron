# Script de Instalação Dedicada do Agente Milvus - Pense Rede
param (
    [string]$ClientName = "Cliente Pense Rede",
    [string]$MilvusToken = "",
    [string]$MdtServer = "192.168.57.87"
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 🛠️ ULTRON - INSTALANDO AGENTE MILVUS ($ClientName)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$cleanClientName = $ClientName -replace '[^a-zA-Z0-9_]', ''
$localMsiPath = "\\$MdtServer\MilvusAgents\Milvus_$cleanClientName.msi"
$fallbackMsiPath = "\\$MdtServer\DeploymentShare$\Milvus\Milvus_$cleanClientName.msi"

if (Test-Path $localMsiPath) {
    Write-Host "Instalando MSI do repositório local: $localMsiPath..." -ForegroundColor Green
    Start-Process msiexec.exe -ArgumentList "/i `"$localMsiPath`" /qn /norestart" -Wait
    Write-Host "✅ Agente Milvus instalado com sucesso a partir de $localMsiPath!" -ForegroundColor Green
} elseif (Test-Path $fallbackMsiPath) {
    Write-Host "Instalando MSI a partir do DeploymentShare: $fallbackMsiPath..." -ForegroundColor Green
    Start-Process msiexec.exe -ArgumentList "/i `"$fallbackMsiPath`" /qn /norestart" -Wait
    Write-Host "✅ Agente Milvus instalado com sucesso!" -ForegroundColor Green
} elseif ($MilvusToken) {
    Write-Host "MSI local não encontrado. Baixando instalador via Token Milvus..." -ForegroundColor Yellow
    try {
        $milvusUrl = "https://milvus.com.br/download/agent?token=$MilvusToken"
        $installerPath = "$env:TEMP\MilvusAgentSetup.exe"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $milvusUrl -OutFile $installerPath
        Start-Process -FilePath $installerPath -ArgumentList "/verysilent /suppressmsgboxes /token=$MilvusToken" -Wait
        Write-Host "✅ Agente Milvus instalado com sucesso via Token Web!" -ForegroundColor Green
    } catch {
        Write-Host "❌ Erro ao baixar Agente Milvus via Web: $_" -ForegroundColor Red
    }
} else {
    Write-Host "⚠️ Nenhum MSI ou Token Milvus disponível para $ClientName." -ForegroundColor Yellow
}
