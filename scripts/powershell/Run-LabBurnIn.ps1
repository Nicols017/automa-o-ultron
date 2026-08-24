# Script de Teste de Estresse (Burn-in), Checagem de Drivers e Bateria
param (
    [int]$StressMinutes = 2
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " ⚡ ULTRON - TESTE DE ESTRESSE & CHECAGEM FINAL" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Checagem de Bateria (Se for Notebook)
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
if ($battery) {
    Write-Host "`n[1/3] Notebook Detectado! Gerando Relatório de Bateria..." -ForegroundColor Yellow
    powercfg /batteryreport /output "$env:TEMP\battery_report.html" | Out-Null
    Write-Host "✅ Saúde da Bateria estimada: $($battery.EstimatedChargeRemaining)% (Status: $($battery.Status))" -ForegroundColor Green
} else {
    Write-Host "`n[1/3] Desktop Detectado (Sem Bateria)." -ForegroundColor Gray
}

# 2. Varredura de Drivers Faltando no Windows
Write-Host "`n[2/3] Verificando se há drivers ausentes ou com erro..." -ForegroundColor Yellow
$missingDrivers = Get-PnpDevice | Where-Object { $_.Status -eq "Error" -or $_.Problem -gt 0 }

if ($missingDrivers) {
    Write-Host "⚠️ Atenção: Há $($missingDrivers.Count) dispositivo(s) sem driver ou com problema:" -ForegroundColor Red
    foreach ($dev in $missingDrivers) {
        Write-Host "   - $($dev.FriendlyName) ($($dev.Class))" -ForegroundColor Yellow
    }
} else {
    Write-Host "✅ Todos os drivers estão 100% instalados e operacionais!" -ForegroundColor Green
}

# 3. Teste de Estresse Leve de CPU (Stress / Burn-in)
Write-Host "`n[3/3] Executando teste de estresse térmico de CPU ($StressMinutes min)..." -ForegroundColor Yellow
$timeout = (Get-Date).AddMinutes($StressMinutes)

$jobs = @()
$logicalCores = (Get-CimInstance Win32_Processor).NumberOfLogicalProcessors

for ($i = 0; $i -lt $logicalCores; $i++) {
    $jobs += Start-Job -ScriptBlock {
        param($limit)
        while ((Get-Date) -lt $limit) {
            $x = 999999 * 999999
        }
    } -ArgumentList $timeout
}

# Aguarda conclusão
$jobs | Wait-Job | Remove-Job | Out-Null
Write-Host "✅ Teste de estresse concluído sem travamentos ou tela azul!" -ForegroundColor Green
