#requires -Version 5.1
<#
Instala apenas UltronService. Nao configura WinRM nem cria contas.
Token e server.url devem ser provisionados fora de banda em ProgramData/Ultron,
com ACL restrita a SYSTEM e Administradores, antes da instalacao.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$SourceExe,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $SourceExe).Path
if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $ExpectedSha256) {
    throw 'Hash do pacote diferente do hash aprovado.'
}
$targetDir = Join-Path $env:ProgramFiles 'UltronAgent'
$target = Join-Path $targetDir 'UltronAgent.exe'
$configDir = Join-Path $env:ProgramData 'Ultron'
$url = [uri](Get-Content -LiteralPath (Join-Path $configDir 'server.url') -Raw).Trim()
if ($url.Scheme -ne 'https' -or $url.UserInfo -or $url.AbsolutePath -ne '/' -or $url.Query -or $url.Fragment) {
    throw 'server.url exige origem HTTPS sem caminho, credenciais ou query.'
}
$token = (Get-Content -LiteralPath (Join-Path $configDir 'agent.token') -Raw).Trim()
if ($token.Length -lt 32) { throw 'Token individual ausente ou invalido.' }
# Reject writable/readable configuration inherited by ordinary users.
foreach ($path in @($configDir, (Join-Path $configDir 'server.url'), (Join-Path $configDir 'agent.token'))) {
    $acl = Get-Acl -LiteralPath $path
    foreach ($rule in $acl.Access) {
        $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if ($rule.AccessControlType -eq 'Allow' -and $sid -notin @('S-1-5-18','S-1-5-32-544')) {
            throw 'ACL de configuracao deve permitir somente SYSTEM e Administradores.'
        }
    }
}

# Existing executable directories must not allow unprivileged writes.
if (Test-Path -LiteralPath $targetDir) {
    foreach ($rule in (Get-Acl -LiteralPath $targetDir).Access) {
        $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        $writeMask = [System.Security.AccessControl.FileSystemRights]::Write -bor [System.Security.AccessControl.FileSystemRights]::Delete -bor [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor [System.Security.AccessControl.FileSystemRights]::TakeOwnership
        if ($rule.AccessControlType -eq 'Allow' -and ($rule.FileSystemRights -band $writeMask) -and $sid -notin @('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')) {
            throw 'Diretorio do executavel permite escrita nao administrativa.'
        }
    }
}
if ($PSCmdlet.ShouldProcess($target, 'Instalar pacote aprovado e iniciar UltronService (sem alterar WinRM)')) {
    $service = Get-Service -Name UltronService -ErrorAction SilentlyContinue
    $wasRunning = $service -and $service.Status -eq 'Running'
    $expectedPath = '"' + $target + '" --service'
    if ($service) {
        $config = Get-CimInstance -ClassName Win32_Service -Filter "Name='UltronService'"
        if ($config.PathName -ne $expectedPath -or $config.StartName -notin @('LocalSystem','NT AUTHORITY\SYSTEM')) {
            throw 'Servico existente tem caminho/conta diferentes. Exige migracao manual revisada.'
        }
    }
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    $stage = Join-Path $targetDir ('stage-' + [guid]::NewGuid().ToString('N') + '.exe')
    $backup = $null
    $created = $false
    $replaced = $false
    try {
        Copy-Item -LiteralPath $source -Destination $stage
        if ((Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash -ne $ExpectedSha256) {
            throw 'Pacote mudou durante copia; servico nao foi interrompido.'
        }
        if ($service) {
            Stop-Service -Name UltronService -ErrorAction Stop
            $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
        }
        if (Test-Path -LiteralPath $target) {
            $backup = $target + '.' + [guid]::NewGuid().ToString('N') + '.bak'
            Copy-Item -LiteralPath $target -Destination $backup
        }
        $replaced = $true  # Copy can fail after partially replacing the destination.
        Copy-Item -LiteralPath $stage -Destination $target -Force
        if (-not $service) {
            New-Service -Name UltronService -BinaryPathName $expectedPath -StartupType Automatic | Out-Null
            $created = $true
        }
        Start-Service -Name UltronService -ErrorAction Stop
        (Get-Service UltronService).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
    } catch {
        $failure = $_
        try {
            if ($replaced) {
                $current = Get-Service -Name UltronService -ErrorAction SilentlyContinue
                if ($current) {
                    Stop-Service -Name UltronService -ErrorAction Stop
                    $current.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
                }
                if ($backup) {
                    Copy-Item -LiteralPath $backup -Destination $target -Force
                } else {
                    Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
                }
            }
            if ($created) {
                $newService = Get-CimInstance -ClassName Win32_Service -Filter "Name='UltronService'"
                $deleted = Invoke-CimMethod -InputObject $newService -MethodName Delete
                if ($deleted.ReturnValue -ne 0) { throw 'Falha ao remover servico criado.' }
            }
            if ($wasRunning) { Start-Service -Name UltronService -ErrorAction Stop }
        } catch {
            Write-Warning 'Rollback incompleto. Preserve backup e revise UltronService manualmente.'
        }
        throw $failure
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Force }
    }
}
