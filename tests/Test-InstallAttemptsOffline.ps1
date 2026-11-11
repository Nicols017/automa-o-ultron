# Installer reporting with every native command replaced. No actual package manager runs.
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility
$PSModuleAutoLoadingPreference = 'None'
$installScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/powershell/Install-UnifiedPackages.ps1'
function Get-Command { [CmdletBinding()] param($Name)
    if ($Name -eq 'winget.exe') { return [pscustomobject]@{Source='fixture-winget.exe'} }
    return $null
}
function Test-Path { [CmdletBinding()] param($Path,$LiteralPath,$PathType) return ($Path -eq 'fixture-winget.exe') }
function Get-ChildItem { [CmdletBinding()] param($Path) throw 'Unexpected native discovery' }
function msg { param([Parameter(ValueFromRemainingArguments=$true)]$Arguments) }
function Start-Process { [CmdletBinding()] param($FilePath,$ArgumentList,[switch]$Wait,[switch]$PassThru,$WindowStyle)
    if ($FilePath -ne 'fixture-winget.exe') { throw 'Unexpected executable' }
    if ($ArgumentList[0] -notin @('source','install')) { throw 'Unexpected command' }
    if (-not $PassThru) { return }
    $exitCode = if ($global:UltronAttemptsTest_case -eq 'second-fails' -and $ArgumentList -contains 'Microsoft.Office') { 5 } else { 0 }
    return [pscustomobject]@{ExitCode=$exitCode}
}
foreach ($global:UltronAttemptsTest_case in @('all-attempts-ok','second-fails')) {
    $lines = @(& $installScript -Packages @('Google.Chrome','Microsoft.Office') -RunId ('a' * 32) 6>$null)
    $marker = 'ULTRON_INSTALL_ATTEMPTS_JSON:'
    $reports = @($lines | Where-Object { $_ -is [string] -and $_.StartsWith($marker) })
    if ($reports.Count -ne 1) { throw 'Missing attempt report' }
    $report = $reports[0].Substring($marker.Length) | ConvertFrom-Json
    if ($report.run_id -ne ('a' * 32) -or $report.packages.Count -ne 2) { throw 'Wrong attempt identity' }
    $office = @($report.packages | Where-Object { $_.requested -eq 'Microsoft.Office' })[0]
    $expected = $global:UltronAttemptsTest_case -eq 'all-attempts-ok'
    if ($office.reported_success -ne $expected) { throw 'Incorrect installer outcome' }
    if ($reports[0] -like '*CONFIRMED_PRESENT*') { throw 'Installer claimed independent verification' }
    Write-Output ('PASS: ' + $global:UltronAttemptsTest_case + ' (all native commands mocked)')
}
