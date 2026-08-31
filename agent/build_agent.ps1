# Script de compilacao do UltronAgent.exe
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
$baseDir = Split-Path -Parent $scriptDir

$sourceFile = Join-Path $scriptDir "UltronAgent.cs"
$outputExe = Join-Path $scriptDir "UltronAgent.exe"
$staticDownloads = Join-Path $baseDir "static\downloads"
$staticExe = Join-Path $staticDownloads "UltronAgent.exe"

if (-not (Test-Path $staticDownloads)) {
    New-Item -ItemType Directory -Path $staticDownloads -Force | Out-Null
}

$cscPaths = @(
    "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)

$csc = $cscPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $csc) {
    Write-Error "Compilador csc.exe do .NET Framework nao foi encontrado."
    exit 1
}

Write-Host "[*] Compilando UltronAgent.cs..." -ForegroundColor Yellow

$icoPath = Join-Path $scriptDir "app.ico"

$compileArgs = @(
    "/target:exe",
    "/optimize+",
    "/platform:anycpu",
    "/r:System.Management.dll",
    "/r:System.dll",
    "/r:System.Core.dll",
    "/out:$outputExe"
)

if (Test-Path $icoPath) {
    $compileArgs += "/win32icon:$icoPath"
}

$compileArgs += "$sourceFile"

$process = Start-Process -FilePath $csc -ArgumentList $compileArgs -NoNewWindow -Wait -PassThru

if ($process.ExitCode -eq 0 -and (Test-Path $outputExe)) {
    Copy-Item -Path $outputExe -Destination $staticExe -Force
    $sizeKb = [math]::Round(((Get-Item $outputExe).Length / 1KB), 1)
    Write-Host "[OK] UltronAgent.exe compilado com sucesso! ($sizeKb KB)" -ForegroundColor Green
    Write-Host "     -> Local: $outputExe" -ForegroundColor Cyan
    Write-Host "     -> Web:   $staticExe" -ForegroundColor Cyan
} else {
    Write-Error "Falha na compilacao do UltronAgent.exe (ExitCode: $($process.ExitCode))"
    exit 1
}
