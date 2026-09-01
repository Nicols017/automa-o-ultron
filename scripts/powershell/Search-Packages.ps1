param (
    [string]$Query = ""
)

$ErrorActionPreference = "SilentlyContinue"

if (-not $Query) {
    Write-Host "⚠️ Informe um termo de busca." -ForegroundColor Yellow
    exit 0
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 🔍 ULTRON — BUSCA UNIVERSAL NO CATÁLOGO UNIGETUI" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# Busca no Winget
$wingetOut = winget search $Query --accept-source-agreements 2>$null
if ($wingetOut) {
    $lines = $wingetOut -split "`r?`n"
    $count = 0
    foreach ($line in $lines) {
        if ($line.Trim() -and $count -lt 15) {
            Write-Output $line
            $count++
        }
    }
} else {
    Write-Host "Nenhum resultado direto encontrado no Winget para '$Query'." -ForegroundColor Yellow
}
