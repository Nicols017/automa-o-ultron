# Script de Instalação e Configuração Automática do Flutter
param (
    [string]$InstallPath = "C:\flutter",
    [string]$FlutterVersion = "3.24.0" # Versao padrao ou SDK stable
)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 🚀 ULTRON - INSTALANDO FLUTTER SDK" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$zipUrl = "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_$FlutterVersion-stable.zip"
$zipPath = "$env:TEMP\flutter_sdk.zip"

if (-not (Test-Path $InstallPath)) {
    Write-Host "Baixando Flutter SDK v$FlutterVersion..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
    
    Write-Host "Extraindo Flutter para $InstallPath..." -ForegroundColor Yellow
    Expand-Archive -Path $zipPath -DestinationPath "C:\" -Force
    Remove-Item -Path $zipPath -Force
} else {
    Write-Host "Flutter ja existe em $InstallPath." -ForegroundColor Green
}

# Adicionar C:\flutter\bin ao PATH do Sistema (Persistent)
$flutterBin = "$InstallPath\bin"
$oldPath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::Machine)

if ($oldPath -notlike "*$flutterBin*") {
    Write-Host "Adicionando $flutterBin ao System PATH..." -ForegroundColor Yellow
    $newPath = "$oldPath;$flutterBin"
    [Environment]::SetEnvironmentVariable("Path", $newPath, [EnvironmentVariableTarget]::Machine)
    Write-Host "✅ Flutter adicionado ao System PATH com sucesso!" -ForegroundColor Green
} else {
    Write-Host "✅ Flutter bin ja esta presente no System PATH." -ForegroundColor Green
}
