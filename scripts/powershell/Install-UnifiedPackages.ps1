param (
    [string[]]$Packages = @(),
    [string]$BundleJsonPath = "",
    [string]$RawJsonContent = "",
    [switch]$Interactive = $true
)

$ErrorActionPreference = "SilentlyContinue"

# Carrega lista de pacotes a instalar
$targetPackages = @()

if ($RawJsonContent) {
    try {
        $parsed = $RawJsonContent | ConvertFrom-Json
        if ($parsed.packages) {
            foreach ($p in $parsed.packages) {
                if ($p.Id) { $targetPackages += $p.Id }
            }
        }
    } catch {}
} elseif ($BundleJsonPath -and (Test-Path $BundleJsonPath)) {
    try {
        $content = Get-Content $BundleJsonPath -Raw -Encoding UTF8
        $parsed = $content | ConvertFrom-Json
        if ($parsed.packages) {
            foreach ($p in $parsed.packages) {
                if ($p.Id) { $targetPackages += $p.Id }
            }
        }
    } catch {}
}

if ($Packages -and $Packages.Count -gt 0) {
    foreach ($pkg in $Packages) {
        if ($pkg -and -not ($targetPackages -contains $pkg)) {
            $targetPackages += $pkg
        }
    }
}

if ($targetPackages.Count -eq 0) {
    Write-Host "⚠️ Nenhum pacote especificado para instalação." -ForegroundColor Yellow
    exit 0
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 📦 ULTRON — INSTALADOR UNIFICADO MULTI-MANAGER" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "[*] Total de programas solicitados: $($targetPackages.Count)" -ForegroundColor Yellow
Write-Host "[*] Modo de Exibição: $(if ($Interactive) { 'VISÍVEL / INTERATIVO (Termos Auto-Aceitos)' } else { 'SILENCIOSO' })" -ForegroundColor Yellow

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

$chocoAvailable = $null -ne (Get-Command choco.exe -ErrorAction SilentlyContinue)
$scoopAvailable = $null -ne (Get-Command scoop.exe -ErrorAction SilentlyContinue)

$successList = @()
$failedList = @()

foreach ($pkgQuery in $targetPackages) {
    $clean = $pkgQuery.Trim()
    if (-not $clean) { continue }

    Write-Host "`n[*] Processando e buscando: $clean..." -ForegroundColor Cyan

    # Emite aviso na tela da máquina física para o operador ver
    try {
        msg * /time:5 "🤖 [ULTRON] Instalando '$clean'... Termos e licenças aceitos automaticamente." 2>$null
    } catch {}

    $installed = $false
    $displayMode = if ($Interactive) { "--interactive" } else { "--silent" }

    # 1. Se contém ponto (ex: Valve.Steam, Google.Chrome), tenta instalação direta por ID exato no Winget
    if ($clean -match "\.") {
        Write-Host "    -> Tentando Winget por ID exato: $clean (Modo: $displayMode)" -ForegroundColor Gray
        $wArgs = @("install", "--id", $clean, "-e", $displayMode, "--accept-package-agreements", "--accept-source-agreements", "--force", "--scope", "machine")
        $p = Start-Process -FilePath $wingetExe -ArgumentList $wArgs -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue
        
        # Se falhou no modo interativo, tenta fallback no modo silencioso
        if ((-not $p -or ($p.ExitCode -ne 0 -and $p.ExitCode -ne -1978335189)) -and $Interactive) {
            $wArgsSilent = @("install", "--id", $clean, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements", "--force", "--scope", "machine")
            $p = Start-Process -FilePath $wingetExe -ArgumentList $wArgsSilent -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue
        }

        if ($p -and ($p.ExitCode -eq 0 -or $p.ExitCode -eq -1978335189)) {
            Write-Host "    [OK] Instalado com sucesso via Winget (ID)!" -ForegroundColor Green
            $successList += $clean
            $installed = $true
            continue
        }
    }

    # 2. Busca e instala por Nome ou Query livre no Winget
    if (-not $installed) {
        Write-Host "    -> Buscando correspondência universal no catálogo Winget: '$clean'..." -ForegroundColor Gray
        $wArgs = @("install", "--name", $clean, $displayMode, "--accept-package-agreements", "--accept-source-agreements", "--force", "--scope", "machine")
        $p = Start-Process -FilePath $wingetExe -ArgumentList $wArgs -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue

        if ((-not $p -or ($p.ExitCode -ne 0 -and $p.ExitCode -ne -1978335189)) -and $Interactive) {
            $wArgsSilent = @("install", "--name", $clean, "--silent", "--accept-package-agreements", "--accept-source-agreements", "--force", "--scope", "machine")
            $p = Start-Process -FilePath $wingetExe -ArgumentList $wArgsSilent -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue
        }

        if ($p -and ($p.ExitCode -eq 0 -or $p.ExitCode -eq -1978335189)) {
            Write-Host "    [OK] Instalado com sucesso via Winget (Nome)!" -ForegroundColor Green
            $successList += $clean
            $installed = $true
            continue
        }

        # 2.1 Fallback de Query livre no Winget
        $wArgsQuery = @("install", "-q", $clean, $displayMode, "--accept-package-agreements", "--accept-source-agreements", "--force", "--scope", "machine")
        $p2 = Start-Process -FilePath $wingetExe -ArgumentList $wArgsQuery -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue

        if ((-not $p2 -or ($p2.ExitCode -ne 0 -and $p2.ExitCode -ne -1978335189)) -and $Interactive) {
            $wArgsQuerySilent = @("install", "-q", $clean, "--silent", "--accept-package-agreements", "--accept-source-agreements", "--force", "--scope", "machine")
            $p2 = Start-Process -FilePath $wingetExe -ArgumentList $wArgsQuerySilent -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue
        }

        if ($p2 -and ($p2.ExitCode -eq 0 -or $p2.ExitCode -eq -1978335189)) {
            Write-Host "    [OK] Instalado com sucesso via Winget (Query)!" -ForegroundColor Green
            $successList += $clean
            $installed = $true
            continue
        }
    }

    # 3. Fallback: Chocolatey
    if (-not $installed -and $chocoAvailable) {
        Write-Host "    -> Tentando no catálogo Chocolatey: '$clean'..." -ForegroundColor Yellow
        $cArgs = @("install", $clean, "-y", "--no-progress")
        $cp = Start-Process -FilePath "choco.exe" -ArgumentList $cArgs -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue
        if ($cp -and $cp.ExitCode -eq 0) {
            Write-Host "    [OK] Instalado com sucesso via Chocolatey!" -ForegroundColor Green
            $successList += $clean
            $installed = $true
            continue
        }
    }

    # 4. Fallback: Scoop
    if (-not $installed -and $scoopAvailable) {
        Write-Host "    -> Tentando no catálogo Scoop: '$clean'..." -ForegroundColor Yellow
        $sArgs = @("install", $clean)
        $sp = Start-Process -FilePath "scoop.exe" -ArgumentList $sArgs -Wait -NoNewWindow -PassThru -ErrorAction SilentlyContinue
        if ($sp -and $sp.ExitCode -eq 0) {
            Write-Host "    [OK] Instalado com sucesso via Scoop!" -ForegroundColor Green
            $successList += $clean
            $installed = $true
            continue
        }
    }

    if (-not $installed) {
        Write-Host "    [FALHA] Programa '$clean' não foi localizado ou falhou na instalação." -ForegroundColor Red
        $failedList += $clean
    }
}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host " 📊 RESUMO DA INSTALAÇÃO UNIFICADA" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "✅ Sucesso: $($successList.Count) pacotes ($($successList -join ', '))" -ForegroundColor Green
if ($failedList.Count -gt 0) {
    Write-Host "❌ Falhas/Não encontrados: $($failedList.Count) pacotes ($($failedList -join ', '))" -ForegroundColor Red
}
