<#
.SYNOPSIS
    Instala e configura o Servidor Ultron como um Serviço do Windows (24/7) para toda a equipe.
.DESCRIPTION
    Permite que o Ultron inicie automaticamente no boot do Windows, atendendo chamados,
    monitorando a bancada e respondendo no TrueConf para qualquer técnico da empresa,
    mesmo sem nenhum usuário logado na máquina.
#>

[CmdletBinding()]
param(
    [string]$ServiceName = "UltronAutomationServer",
    [string]$DisplayName = "Ultron Lab Automation Server (Pense Rede)",
    [int]$Port = 7000
)

# Requer privilégios de Administrador
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "[!] Execute este script como Administrador!"
    exit 1
}

$ScriptDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "$ScriptDir\main.py")) {
    $ScriptDir = $PSScriptRoot
}

$PythonExe = "$ScriptDir\venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  INSTALADOR DE SERVICO WINDOWS - ULTRON SERVER 24/7    " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "[*] Diretorio do Ultron: $ScriptDir" -ForegroundColor Yellow
Write-Host "[*] Executavel Python:   $PythonExe" -ForegroundColor Yellow
Write-Host "[*] Porta TCP:           $Port" -ForegroundColor Yellow

# 1. Liberacao de porta no Firewall do Windows para a rede interna
Write-Host "[*] Configurando regra no Windows Firewall para a porta $Port..." -ForegroundColor Yellow
netsh advfirewall firewall add rule name="Ultron Server $Port" dir=in action=allow protocol=TCP localport=$Port | Out-Null
Write-Host "    -> Regra de Firewall criada com sucesso!" -ForegroundColor Green

# 2. Criacao da Task Agendada / Servico de Inicializacao Automatica
$TaskName = "UltronServer_AutoStart"
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "main.py" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $DisplayName | Out-Null
    Write-Host "[OK] Tarefa de servico '$TaskName' registrada para inicializacao no boot!" -ForegroundColor Green
    
    # Inicia a tarefa agora
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] Ultron Server iniciado em segundo plano como Servico de Sistema!" -ForegroundColor Green
} catch {
    Write-Warning "Falha ao registrar tarefa automatica: $_"
}

Write-Host "`n🎉 Instalação concluída com sucesso!" -ForegroundColor Green
Write-Host "O Ultron Server agora roda 24/7 e atenderá toda a equipe pelo TrueConf e Web Dashboard." -ForegroundColor Cyan
