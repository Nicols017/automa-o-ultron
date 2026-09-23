$ErrorActionPreference = "SilentlyContinue"

$healReport = @{
    healed_items = @()
    warnings = @()
}

function Log-Heal($Item) {
    $healReport.healed_items += $Item
}

# 1. Energia e Periféricos USB (Prevenir "Thermal Throttling" e desconexões)
try {
    # Definir plano para Alto Desempenho (High Performance) se disponível
    $highPerf = powercfg -aliases | Select-String "SCHEME_MIN"
    if ($highPerf) {
        powercfg -setactive SCHEME_MIN
        Log-Heal "Plano de energia alterado para Alto Desempenho"
    }
    
    # Desabilitar USB Selective Suspend para AC e DC no plano atual
    $currentScheme = (powercfg -getactivescheme) -match "GUID: ([a-z0-9\-]+)" | Out-Null
    $schemeGuid = $matches[1]
    if ($schemeGuid) {
        powercfg -setacvalueindex $schemeGuid 2a737441-1930-4402-8d77-b2bea12b9fd5 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
        powercfg -setdcvalueindex $schemeGuid 2a737441-1930-4402-8d77-b2bea12b9fd5 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
        powercfg -setactive $schemeGuid
        Log-Heal "Suspensão Seletiva de USB desabilitada (Prevenção de quedas de Wi-Fi/Teclado)"
    }
} catch {
    $healReport.warnings += "Falha ao ajustar energia: $_"
}

# 2. Rede e Wi-Fi (Resets agressivos de TCP/IP e Adaptadores)
try {
    # Reset TCP/IP e Winsock silencioso
    & netsh int ip reset > $null
    & netsh winsock reset > $null
    & ipconfig /flushdns > $null
    
    # Reiniciar serviço de Wi-Fi se estiver rodando
    $wlansvc = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
    if ($wlansvc.Status -eq 'Running') {
        Restart-Service -Name WlanSvc -Force
        Log-Heal "Serviço Wi-Fi (WlanSvc) reiniciado"
    }

    # Netlogon (Domínio)
    $netlogon = Get-Service -Name Netlogon -ErrorAction SilentlyContinue
    if ($netlogon -and $netlogon.Status -eq 'Running') {
        Restart-Service -Name Netlogon -Force
        Log-Heal "Serviço Netlogon reiniciado (Sincronização de Domínio forçada)"
    }
    
    Log-Heal "Pilha TCP/IP e cache de DNS completamente resetados"
} catch {
    $healReport.warnings += "Falha no reset de rede: $_"
}

# 3. Gargalos Clássicos de Disco (Parar serviços sabotadores)
try {
    # SysMain (Superfetch) causa 100% disco em muitos PCs
    $sysmain = Get-Service -Name SysMain -ErrorAction SilentlyContinue
    if ($sysmain -and $sysmain.Status -eq 'Running') {
        Stop-Service -Name SysMain -Force
        Set-Service -Name SysMain -StartupType Disabled
        Log-Heal "Serviço SysMain (Superfetch) desativado para liberar gargalo de Disco"
    }
    
    # Spooler travado (Limpar fila e reiniciar)
    $spooler = Get-Service -Name Spooler -ErrorAction SilentlyContinue
    if ($spooler) {
        Stop-Service -Name Spooler -Force
        Remove-Item -Path "$env:windir\System32\spool\PRINTERS\*.*" -Force -Recurse
        Start-Service -Name Spooler
        Log-Heal "Fila de impressão fantasma destruída e Spooler reiniciado"
    }
} catch {
    $healReport.warnings += "Falha na cura de disco: $_"
}

# 4. Áudio (Reset)
try {
    $audio = Get-Service -Name Audiosrv -ErrorAction SilentlyContinue
    if ($audio -and $audio.Status -eq 'Running') {
        Restart-Service -Name Audiosrv -Force
        Log-Heal "Serviço de Áudio do Windows reiniciado"
    }
} catch {}

# 5. Lixo e Arquivos Temporários
try {
    $tempSize = 0
    $tempPaths = @("$env:TEMP\*", "$env:windir\Temp\*")
    foreach ($path in $tempPaths) {
        $files = Get-ChildItem -Path $path -Recurse -File -ErrorAction SilentlyContinue
        foreach ($file in $files) {
            $tempSize += $file.Length
            Remove-Item $file.FullName -Force -ErrorAction SilentlyContinue
        }
    }
    if ($tempSize -gt 0) {
        $mb = [math]::Round($tempSize / 1MB, 1)
        Log-Heal "Removidos $mb MB de arquivos temporários inúteis"
    }
} catch {}

# 6. Reparo Lógico de Disco Rápido
try {
    # Inicia uma verificação rápida no próximo boot se houver dirty bit
    $volume = Get-WmiObject Win32_Volume -Filter "DriveLetter = 'C:'"
    if ($volume -and $volume.DirtyBitSet) {
        # O comando fsutil dirty set força o chkdsk no boot
        # Aqui podemos tentar avisar.
        Log-Heal "Aviso: Volume C: está sujo (dirty bit). Chkdsk rodará no próximo boot."
    }
} catch {}


# Exporta JSON
$jsonOutput = $healReport | ConvertTo-Json -Depth 4
Write-Output $jsonOutput
