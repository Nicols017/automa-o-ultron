#requires -Version 5.1
# Read-only inventory query. Never installs, updates, repairs or retries a package.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string[]]$Packages,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{32}$')][string]$RunId
)
$ErrorActionPreference = 'Stop'
if ($Packages.Count -lt 1 -or $Packages.Count -gt 50) { throw 'Quantidade de pacotes invalida.' }
$rows = @()
$inventory = @()
$available = $false
$tempFile = Join-Path ([IO.Path]::GetTempPath()) ('ultron-package-query-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        $arguments = @('export', '--output', ('"' + $tempFile + '"'), '--include-versions', '--source', 'winget', '--accept-source-agreements', '--disable-interactivity')
        $process = Start-Process -FilePath $winget.Source -ArgumentList $arguments -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit(60000)) {
            # Only this read-only export process is stopped, never an installer.
            $process.Kill()
            $process.WaitForExit(5000) | Out-Null
        } elseif ($process.ExitCode -eq 0 -and (Test-Path -LiteralPath $tempFile)) {
            if ((Get-Item -LiteralPath $tempFile).Length -le 8MB) {
                $data = Get-Content -LiteralPath $tempFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($null -ne $data.Sources) {
                    $valid = $true
                    foreach ($source in @($data.Sources)) {
                        foreach ($package in @($source.Packages)) {
                            if ($null -eq $package -or -not ($package.PackageIdentifier -is [string])) { $valid = $false; continue }
                            $inventory += $package
                        }
                    }
                    $available = $valid
                }
            }
        }
    }
} catch {
    $available = $false
} finally {
    if (Test-Path -LiteralPath $tempFile) { Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue }
}
foreach ($requested in $Packages) {
    if ($requested -notmatch '^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$' -or $requested -notmatch '\.') {
        $rows += @{ requested=$requested; status='UNSUPPORTED_ID'; version=$null }
        continue
    }
    $matches = @($inventory | Where-Object { $_.PackageIdentifier -ieq $requested })
    $version = $null
    if ($available -and $matches.Count -eq 1 -and $matches[0].Version -is [string]) {
        $candidate = $matches[0].Version
        if ($candidate -match '^[A-Za-z0-9][A-Za-z0-9._+() -]{0,63}$' -and $candidate -notin @('Unknown','latest')) {
            $version = $candidate
        }
    }
    $rows += @{ requested=$requested; status=$(if ($version) { 'CONFIRMED_PRESENT' } else { 'UNCONFIRMED' }); version=$version }
}
Write-Output ('ULTRON_PACKAGE_VERIFICATION_JSON:' + (@{schema_version=1; run_id=$RunId; packages=@($rows)} | ConvertTo-Json -Depth 5 -Compress))
