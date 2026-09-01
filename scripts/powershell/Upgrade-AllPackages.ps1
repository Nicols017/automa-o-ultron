param (
    [switch]$IncludeUnknown = $true
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 🚀 ULTRON — ATUALIZAÇÃO EM MASSA DE SOFTWARES" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

function Get-RealWingetPath {
    $cmd = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path $cmd.Source)) { return $cmd.Source }
    $appx = Get-ChildItem "C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_*_x64__8wekyb3d8bbwe\winget.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -First 1
    if ($appx -and (Test-Path $appx)) { return $appx }
    $userApp = Get-ChildItem "C:\Users\*\AppData\Local\Microsoft\WindowsApps\winget.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -First 1
    if ($userApp -and (Test-Path $userApp)) { return $userApp }
    return "winget.exe"
}
$wingetExe = Get-RealWingetPath

# 1. Garante que as fontes do Winget estão atualizadas
Write-Host "[*] Sincronizando fontes e catálogos do Winget..." -ForegroundColor Yellow
& $wingetExe source update 2>$null | Out-Null

# 2. Executa a atualização de todos os programas
Write-Host "[*] Executando 'winget upgrade --all' silencioso..." -ForegroundColor Yellow

$upgradeArgs = @("upgrade", "--all", "--silent", "--accept-package-agreements", "--accept-source-agreements", "--force", "--scope", "machine")
if ($IncludeUnknown) {
    $upgradeArgs += "--include-unknown"
}

$proc = Start-Process -FilePath $wingetExe -ArgumentList $upgradeArgs -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue
$exitCode = if ($proc) { $proc.ExitCode } else { 0 }

# 3. Relatório final de status
if ($exitCode -eq 0) {
    Write-Host "[OK] Todos os softwares foram atualizados com sucesso!" -ForegroundColor Green
} elseif ($exitCode -eq -1978335189 -or $exitCode -eq 2316632107) {
    Write-Host "[OK] Nenhum software pendente de atualização. Tudo na versão mais recente!" -ForegroundColor Green
} else {
    Write-Host "[*] Processo de atualização concluído (Código: $exitCode)." -ForegroundColor Yellow
}

# Retorna lista de softwares pós-atualização
winget list --accept-source-agreements 2>$null | Select-Object -First 30
