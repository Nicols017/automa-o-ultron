# Verifier behavior with fake WinGet, temporary fake inventory and no native processes.
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility
$PSModuleAutoLoadingPreference = 'None'
$verifyScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/powershell/Verify-InstalledPackages.ps1'
function Get-Command { [CmdletBinding()] param($Name) [pscustomobject]@{Source='fixture-winget.exe'} }
function Start-Process { [CmdletBinding()] param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru)
    if ($FilePath -ne 'fixture-winget.exe' -or $ArgumentList[0] -ne 'export') { throw 'Unexpected native command' }
    $global:UltronPackageTest_calls++
    $output = $ArgumentList[2].Trim('"')
    $packages = @(
        @{PackageIdentifier='Google.Chrome';Version='123.0'},
        @{PackageIdentifier='Other.Private';Version='99.0'}
    )
    if ($global:UltronPackageTest_case -eq 'missing') { $packages = @() }
    if ($global:UltronPackageTest_case -eq 'duplicate') { $packages += @{PackageIdentifier='Google.Chrome';Version='124.0'} }
    if ($global:UltronPackageTest_case -eq 'noversion') { $packages[0].Remove('Version') }
    if ($global:UltronPackageTest_case -eq 'invalid-json') {
        [IO.File]::WriteAllText($output, 'invalid-json')
    } else {
        [IO.File]::WriteAllText($output, (@{Sources=@(@{Packages=@($packages)})} | ConvertTo-Json -Depth 8))
    }
    $p = [pscustomobject]@{ExitCode=$(if ($global:UltronPackageTest_case -eq 'query-failed') { 1 } else { 0 })}
    $p | Add-Member ScriptMethod WaitForExit { param($Timeout) return ($Timeout -ne 60000 -or $global:UltronPackageTest_case -ne 'timeout') }
    $p | Add-Member ScriptMethod Kill { $global:UltronPackageTest_kills++ }
    return $p
}
foreach ($global:UltronPackageTest_case in @('present','missing','duplicate','noversion','invalid-json','query-failed','timeout')) {
    $global:UltronPackageTest_calls = 0
    $global:UltronPackageTest_kills = 0
    $lines = @(& $verifyScript -Packages @('Google.Chrome','query name') -RunId ('a' * 32))
    $marker = 'ULTRON_PACKAGE_VERIFICATION_JSON:'
    $reportLine = @($lines | Where-Object { $_ -is [string] -and $_.StartsWith($marker) })
    if ($reportLine.Count -ne 1) { throw 'Missing or duplicated report' }
    $report = $reportLine[0].Substring($marker.Length) | ConvertFrom-Json
    $chrome = @($report.packages | Where-Object { $_.requested -eq 'Google.Chrome' })[0]
    $expected = if ($global:UltronPackageTest_case -eq 'present') { 'CONFIRMED_PRESENT' } else { 'UNCONFIRMED' }
    if ($chrome.status -ne $expected) { throw ('Incorrect presence result: ' + $global:UltronPackageTest_case) }
    if ($reportLine[0] -like '*Other.Private*') { throw 'Leaked unrequested inventory' }
    if ($report.packages[1].status -ne 'UNSUPPORTED_ID') { throw 'Free-text query was falsely verified' }
    if ($global:UltronPackageTest_calls -ne 1) { throw 'Unexpected query replay' }
    if ($global:UltronPackageTest_case -eq 'timeout' -and $global:UltronPackageTest_kills -ne 1) { throw 'Export timeout not bounded' }
    Write-Output ('PASS: ' + $global:UltronPackageTest_case + ' (fake WinGet only)')
}
