#requires -Version 5.1
# Build only: no installation, service changes or copy to web downloads.
[CmdletBinding()]
param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist'))
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'UltronAgent.cs'
$repo = Split-Path -Parent $PSScriptRoot
$commit = & git -C $repo rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[a-fA-F0-9]{40}$') { throw 'Commit Git ausente.' }
$dirty = & git -C $repo status --porcelain -- agent/UltronAgent.cs agent/build_agent.ps1
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Use fontes commitados para gerar pacote rastreavel.' }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Compilador .NET Framework ausente.' }
# Build source snapshot prevents edits during compilation from changing the manifest.
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$output = Join-Path $OutputDirectory 'UltronAgent.exe'
$manifestPath = Join-Path $OutputDirectory 'manifest.json'
if (Test-Path -LiteralPath $manifestPath) { Remove-Item -LiteralPath $manifestPath -Force }
$sourceText = [IO.File]::ReadAllText($source)
$versionMatch = [regex]::Match($sourceText, 'public\s+const\s+string\s+CurrentVersion\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"')
if (-not $versionMatch.Success) { throw 'Versao invalida.' }
$rawSourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$normalized = $sourceText.Replace(([string][char]13 + [char]10), [string][char]10)
$sha = [Security.Cryptography.SHA256]::Create()
try { $sourceHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
$temp = Join-Path $OutputDirectory ('source-' + [guid]::NewGuid().ToString('N') + '.cs')
try {
    Copy-Item -LiteralPath $source -Destination $temp
    if ((Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash.ToLowerInvariant() -ne $rawSourceHash) { throw 'Fonte mudou durante snapshot.' }
    & $compiler /nologo /target:exe /optimize+ /platform:anycpu /r:System.Management.dll /r:System.ServiceProcess.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll ("/out:" + $output) $temp
    if ($LASTEXITCODE -ne 0) { throw 'Falha na compilacao.' }
    $manifest = [ordered]@{
        schema_version = 1
        version = $versionMatch.Groups[1].Value
        commit = $commit.Trim()
        source_sha256 = $sourceHash
        binary_sha256 = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
        authenticode = 'unsigned'
    }
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    Write-Output ('Pacote gerado sem instalar: ' + $OutputDirectory)
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
}
