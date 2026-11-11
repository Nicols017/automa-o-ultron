# All commands that read/change machine state are replaced in this child scope.
# Never dot-source this harness in an interactive administrative session.
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility, Microsoft.PowerShell.Security, CimCmdlets
$PSModuleAutoLoadingPreference = 'None'
$installer = Join-Path (Split-Path -Parent $PSScriptRoot) 'agent/Install-Agent.ps1'
$global:UltronInstallerTest_target = Join-Path (Join-Path $env:ProgramFiles 'UltronAgent') 'UltronAgent.exe'
$global:UltronInstallerTest_hash = 'A' * 64

function Resolve-Path { [CmdletBinding()] param($LiteralPath) [pscustomobject]@{Path='fixture.exe'} }
function Get-Content { [CmdletBinding()] param($LiteralPath,[switch]$Raw)
    if ($LiteralPath -like '*server.url') { return 'https://example.invalid' }
    return ('t' * 40)
}
function Get-FileHash { [CmdletBinding()] param($LiteralPath,$Algorithm)
    $value = $global:UltronInstallerTest_hash
    if ($global:UltronInstallerTest_case -eq 'tampered-stage' -and $LiteralPath -like '*stage-*') { $value = 'B' * 64 }
    [pscustomobject]@{Hash=$value}
}
function Get-Acl { [CmdletBinding()] param($LiteralPath) [pscustomobject]@{Access=@()} }
function Test-Path { [CmdletBinding()] param($LiteralPath,$PathType)
    if ($LiteralPath -eq $global:UltronInstallerTest_target -and $global:UltronInstallerTest_case -like 'new-*') { return $false }
    return $true
}
function New-Item { [CmdletBinding()] param($ItemType,$Path,[switch]$Force) $global:UltronInstallerTest_events.Add('mkdir') }
function Copy-Item { [CmdletBinding()] param($LiteralPath,$Destination,[switch]$Force)
    if ($LiteralPath -like '*.bak') { $global:UltronInstallerTest_events.Add('restore'); return }
    if ($Destination -eq $global:UltronInstallerTest_target) {
        $global:UltronInstallerTest_events.Add('replace')
        if ($global:UltronInstallerTest_case -eq 'partial-copy') { throw 'Injected partial copy failure' }
    } elseif ($Destination -like '*.bak') { $global:UltronInstallerTest_events.Add('backup') }
    else { $global:UltronInstallerTest_events.Add('stage') }
}
function Remove-Item { [CmdletBinding()] param($LiteralPath,[switch]$Force) $global:UltronInstallerTest_events.Add('remove') }
function Get-Service { [CmdletBinding()] param($Name)
    if (-not $global:UltronInstallerTest_exists) { return $null }
    $service = [pscustomobject]@{Status='Running'}
    $service | Add-Member -MemberType ScriptMethod -Name WaitForStatus -Value { param($Status,$Timeout) }
    return $service
}
function Get-CimInstance { [CmdletBinding()] param($ClassName,$Filter)
    [pscustomobject]@{PathName=('"'+$global:UltronInstallerTest_target+'" --service');StartName='LocalSystem'}
}
function Stop-Service { [CmdletBinding()] param($Name) $global:UltronInstallerTest_events.Add('stop') }
function Start-Service { [CmdletBinding()] param($Name)
    $global:UltronInstallerTest_events.Add('start')
    $global:UltronInstallerTest_starts++
    if ($global:UltronInstallerTest_case -in @('start-fails','new-start-fails') -and $global:UltronInstallerTest_starts -eq 1) { throw 'Injected start failure' }
}
function New-Service { [CmdletBinding()] param($Name,$BinaryPathName,$StartupType)
    $global:UltronInstallerTest_events.Add('create')
    $global:UltronInstallerTest_exists = $true
}
function Invoke-CimMethod { [CmdletBinding()] param($InputObject,$MethodName)
    $global:UltronInstallerTest_events.Add('delete-service')
    $global:UltronInstallerTest_exists = $false
    [pscustomobject]@{ReturnValue=0}
}
function Assert($condition,$message) { if (-not $condition) { throw $message } }

foreach ($global:UltronInstallerTest_case in @('whatif','success','tampered-stage','partial-copy','start-fails','new-success','new-start-fails')) {
    $global:UltronInstallerTest_events = New-Object 'System.Collections.Generic.List[string]'
    $global:UltronInstallerTest_starts = 0
    $global:UltronInstallerTest_exists = $global:UltronInstallerTest_case -notlike 'new-*'
    $failed = $false
    try {
        & $installer -SourceExe fixture.exe -ExpectedSha256 $global:UltronInstallerTest_hash -WhatIf:($global:UltronInstallerTest_case -eq 'whatif') -Confirm:$false
    } catch { $failed = $true; Write-Output ("Expected/actual failure: " + $_.Exception.Message) }
    switch ($global:UltronInstallerTest_case) {
        'whatif' { Assert (-not $failed -and $global:UltronInstallerTest_events.Count -eq 0) 'WhatIf changed machine state' }
        'success' {
            Assert (-not $failed) 'Successful update failed'
            Assert (($global:UltronInstallerTest_events -join ',') -eq 'mkdir,stage,stop,backup,replace,start,remove') 'Wrong update ordering'
        }
        'tampered-stage' {
            Assert $failed 'Changed package accepted'
            Assert (-not $global:UltronInstallerTest_events.Contains('stop')) 'Stopped service before staging hash validation'
        }
        'partial-copy' {
            Assert $failed 'Partial copy reported success'
            Assert ($global:UltronInstallerTest_events.Contains('restore') -and $global:UltronInstallerTest_events.Contains('start')) 'Partial copy did not roll back'
        }
        'new-success' {
            Assert (-not $failed) 'Fresh install failed'
            Assert ($global:UltronInstallerTest_events.Contains('create')) 'Fresh install did not create service'
        }
        'new-start-fails' {
            Assert $failed 'Fresh install startup failure reported success'
            Assert ($global:UltronInstallerTest_events.Contains('delete-service')) 'Failed fresh install left service behind'
            Assert (-not $global:UltronInstallerTest_events.Contains('restore')) 'Fresh install restored nonexistent backup'
        }
        'start-fails' {
            Assert $failed 'Startup failure reported success'
            Assert ($global:UltronInstallerTest_events.Contains('restore') -and $global:UltronInstallerTest_starts -eq 2) 'Startup failure did not restore/restart original'
        }
    }
    Write-Output ('PASS: ' + $global:UltronInstallerTest_case + ' (mocked machine commands)')
}
