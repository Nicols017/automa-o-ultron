<#
  Verify-MacriumImage.ps1
  Read-only MRVerify check on a pre-approved Windows verifier machine.
  Requires MRVerify.exe on Windows. Does NOT use --fix or restore an image.
#>
param(
    [Parameter(Mandatory=$true)][string]$ImagePath,
    [Parameter(Mandatory=$true)][string]$AllowedRoot
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Emit-Result([bool]$Verified, [string]$Reason, [int]$Code, [string]$LogPath, [int64]$Bytes) {
    $value = @{
        verified    = $Verified
        reason      = $Reason
        exit_code   = $Code
        image_path  = $ImagePath
        log_path    = $LogPath
        size_bytes  = $Bytes
        verified_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    Write-Output ("ULTRON_MACRIUM_JSON:" + ($value | ConvertTo-Json -Compress -Depth 3))
}

$logPath = ""
$bytes = [int64]0
try {
    if ([string]::IsNullOrWhiteSpace($ImagePath) -or [string]::IsNullOrWhiteSpace($AllowedRoot)) {
        throw "Imagem ou diretorio autorizado nao informado."
    }
    if ($ImagePath -match '[\x00-\x1F"'';$|&*?<>]' -or $AllowedRoot -match '[\x00-\x1F"'';$|&*?<>]') {
        throw "Caracter proibido no caminho."
    }
    if (-not $ImagePath.EndsWith(".mrimg", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Apenas imagens .mrimg sao aceitas."
    }
    if ($ImagePath -match '(^|\\)\.\.?($|\\)' -or $AllowedRoot -match '(^|\\)\.\.?($|\\)') {
        throw "Caminhos relativos nao sao aceitos."
    }
    $fullImage = [IO.Path]::GetFullPath($ImagePath)
    $fullRoot = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\')
    if (-not $fullImage.StartsWith($fullRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Imagem fora da pasta autorizada."
    }
    if ($fullImage -ne $ImagePath) {
        throw "Caminho da imagem nao e canonico."
    }

    $macrium = Join-Path $env:ProgramFiles 'Macrium\Reflect\MRVerify.exe'
    if (-not (Test-Path -LiteralPath $macrium -PathType Leaf)) {
        throw "MRVerify.exe nao localizado na estacao Windows."
    }
    $image = Get-Item -LiteralPath $fullImage -ErrorAction Stop
    if ($image.PSIsContainer -or $image.Length -le 0) {
        throw "Imagem de backup inexistente ou vazia."
    }
    $bytes = [int64]$image.Length
    $originalTime = $image.LastWriteTimeUtc.Ticks

    $logDir = Join-Path $env:ProgramData 'Ultron\MacriumVerifyLogs'
    New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
    $logPath = Join-Path $logDir ("mrverify-" + [guid]::NewGuid().ToString("N") + ".txt")

    # MRVerify --set valida o conjunto. --fix NUNCA e usado.
    $rawLines = @(& $macrium $fullImage --set --logfile $logPath 2>&1 | Out-String)
    $code = [int]$LASTEXITCODE
    $output = [string]($rawLines -join [Environment]::NewLine)
    $logText = if (Test-Path -LiteralPath $logPath) {
        [IO.File]::ReadAllText($logPath)
    } else { "" }
    $text = ($output + [Environment]::NewLine + $logText).ToLowerInvariant()

    if ($code -ne 0 -or $text -notmatch 'verify success' -or
        $text -notmatch 'verification succeeded' -or
        $text -match 'verify failure|verification failed|no files found|unable to open|backup set is not complete') {
        Emit-Result $false "O MRVerify nao confirmou a integridade do conjunto." $code $logPath $bytes
        exit 1
    }
    if ($text -notlike ('*' + $image.Name.ToLowerInvariant() + '*')) {
        Emit-Result $false "O resultado nao identifica a imagem solicitada." $code $logPath $bytes
        exit 1
    }

    $imageAfter = Get-Item -LiteralPath $fullImage -ErrorAction Stop
    if ($imageAfter.Length -ne $bytes -or $imageAfter.LastWriteTimeUtc.Ticks -ne $originalTime) {
        Emit-Result $false "A imagem mudou durante a verificacao." 1 $logPath $bytes
        exit 1
    }
    Emit-Result $true "MRVerify concluiu com sucesso; restore nao testado." 0 $logPath $bytes
    exit 0
}
catch {
    Emit-Result $false ([string]$_.Exception.Message) 1 $logPath $bytes
    exit 1
}
