param (
    [string]$OutputPath = ""
)

$ErrorActionPreference = "SilentlyContinue"

# 1. Coleta lista de pacotes reconhecidos pelo Winget
$wingetPackages = @()
try {
    $wingetOut = winget list --accept-source-agreements 2>$null
    if ($wingetOut) {
        $lines = $wingetOut -split "`r?`n"
        $headerIndex = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match "^Name\s+Id\s+Version") {
                $headerIndex = $i
                break
            }
        }
        if ($headerIndex -ge 0 -and ($headerIndex + 1) -lt $lines.Count) {
            for ($i = $headerIndex + 2; $i -lt $lines.Count; $i++) {
                $line = $lines[$i].Trim()
                if (-not $line) { continue }
                # Regex para extrair Name, Id, Version, Source
                $tokens = $line -split "\s{2,}"
                if ($tokens.Count -ge 2) {
                    $pkgName = $tokens[0].Trim()
                    $pkgId = $tokens[1].Trim()
                    $pkgVer = if ($tokens.Count -ge 3) { $tokens[2].Trim() } else { "latest" }
                    $pkgSource = if ($tokens.Count -ge 4) { $tokens[3].Trim() } else { "winget" }

                    if ($pkgId -match "^[A-Za-z0-9\._\-]+$" -and $pkgId -notmatch "^<.*>$") {
                        $wingetPackages += @{
                            Id = $pkgId
                            Name = $pkgName
                            Version = $pkgVer
                            Source = if ($pkgSource) { $pkgSource } else { "winget" }
                            ManagerName = "Winget"
                        }
                    }
                }
            }
        }
    }
} catch {}

# 2. Se Winget não retornou pacotes, lê Registro do Windows (HKLM/HKCU Uninstall)
if ($wingetPackages.Count -eq 0) {
    $regPaths = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $installedApps = Get-ItemProperty $regPaths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -and $_.SystemComponent -ne 1 -and $_.ParentKeyName -eq $null }
    foreach ($app in $installedApps) {
        $name = $app.DisplayName.Trim()
        $ver = if ($app.DisplayVersion) { $app.DisplayVersion.Trim() } else { "1.0" }
        $pub = if ($app.Publisher) { $app.Publisher.Trim() } else { "Unknown" }
        
        $wingetPackages += @{
            Id = ($name -replace "[^a-zA-Z0-9\.]", "")
            Name = $name
            Version = $ver
            Source = "Registry"
            ManagerName = "WindowsInstaller"
            Publisher = $pub
        }
    }
}

# 3. Monta estrutura padrão de Bundle compatível com UniGetUI v2 / WingetUI
$bundle = @{
    export_version = 2
    created_by = "Ultron Lab Automation (Pense Rede)"
    created_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    hostname = $env:COMPUTERNAME
    packages = $wingetPackages
}

$json = $bundle | ConvertTo-Json -Depth 5

if ($OutputPath) {
    [System.IO.File]::WriteAllText($OutputPath, $json, [System.Text.Encoding]::UTF8)
}

Write-Output $json
