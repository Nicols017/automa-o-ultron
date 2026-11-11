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
if ($PSCmdlet.ShouldProcess($target, 'Instalar pacote aprovado e iniciar UltronService (sem alterar WinRM)')) {
    $service = Get-Service -Name UltronService -ErrorAction SilentlyContinue
    if ($service) {
        Stop-Service -Name UltronService -ErrorAction Stop
        $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    }
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    # Keep a local rollback copy; never overwrite an existing backup silently.
    if (Test-Path -LiteralPath $target) {
        Copy-Item -LiteralPath $target -Destination ($target + '.' + [guid]::NewGuid().ToString('N') + '.bak')
    }
    Copy-Item -LiteralPath $source -Destination $target -Force
    if (-not $service) {
        New-Service -Name UltronService -BinaryPathName ('"' + $target + '" --service') -StartupType Automatic | Out-Null
    } else {
        & sc.exe config UltronService binPath= ('"' + $target + '" --service') start= auto
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao configurar UltronService; restaure o backup antes de iniciar.' }
    }
    Start-Service -Name UltronService -ErrorAction Stop
    (Get-Service UltronService).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
}
