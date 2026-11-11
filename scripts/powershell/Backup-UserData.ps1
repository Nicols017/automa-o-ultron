# Backup de PASTAS de usuario (NAO imagem Macrium, NAO liberacao de formato).
# Executado por WinRM na estacao Windows de origem.
# Nunca usa /MIR, /PURGE, remove arquivos ou inicia MDT.
param(
    [Parameter(Mandatory=$true)][string]$TargetShare,
    [Parameter(Mandatory=$true)][string]$ClientName,
    [Parameter(Mandatory=$true)][string]$TicketNumber,
    [string]$SourceDrive = "C:"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$runId = [guid]::NewGuid().ToString("N")
$destination = ""
$copiedDirectories = 0
$sourceProfiles = 0
$filesPresent = [int64]0
$totalBytes = [int64]0
$errors = New-Object System.Collections.Generic.List[string]
$robocopyCodes = New-Object System.Collections.Generic.List[int]

function Result-Json([string]$State, [string]$Reason) {
    $obj = @{
        status = $State
        reason = $Reason
        type = "selected_user_files"
        image_backup = $false
        mdt_authorized = $false
        destination = $destination
        client = $ClientName
        ticket = $TicketNumber
        run_id = $runId
        profiles_found = $sourceProfiles
        folders_copied = $copiedDirectories
        files_at_destination = $filesPresent
        bytes_at_destination = $totalBytes
        robocopy_exit_codes = @($robocopyCodes.ToArray())
        completed_at = [DateTime]::UtcNow.ToString("o")
    }
    Write-Output ("ULTRON_FILES_BACKUP_JSON:" + ($obj | ConvertTo-Json -Compress -Depth 4))
}

try {
    if ($ClientName -notmatch '^[\p{L}\p{N} _-]{2,60}$' -or $TicketNumber -notmatch '^[0-9]{2,12}$') {
        throw "Cliente ou chamado invalido."
    }
    if ($SourceDrive -notmatch '^[A-Za-z]:$') {
        throw "Unidade de origem invalida."
    }
    if ($TargetShare -notmatch '^\\\\[A-Za-z0-9.-]+\\[A-Za-z0-9$._-]+$') {
        throw "Compartilhamento de destino invalido."
    }
    $usersPath = "$SourceDrive\Users"
    if (-not (Test-Path -LiteralPath $usersPath -PathType Container)) {
        throw "Pasta de perfis nao encontrada: $usersPath"
    }
    if (-not (Test-Path -LiteralPath $TargetShare -PathType Container)) {
        throw "Storage indisponivel ou sem acesso de leitura: $TargetShare"
    }

    $folderName = "$TicketNumber - $ClientName"
    $destination = Join-Path (Join-Path $TargetShare $folderName) ("ultron-files-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + $runId.Substring(0,8))
    New-Item -ItemType Directory -Path $destination -ErrorAction Stop | Out-Null

    $profiles = @(Get-ChildItem -LiteralPath $usersPath -Directory -Force |
        Where-Object {
            $_.Name -notin @(
                "Public", "Default", "Default User", "All Users",
                "defaultuser0", "WDAGUtilityAccount"
            ) -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        })
    $sourceProfiles = $profiles.Count
    if ($sourceProfiles -eq 0) {
        throw "Nenhum perfil de usuario localizado."
    }

    # Conjunto delimitado. Nao inclui automaticamente aplicativos, outros volumes,
    # PSTs fora dessas pastas, dados online-only do OneDrive ou sistema operacional.
    $folders = @(
        "Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos",
        "Favorites", "AppData\Local\Google\Chrome\User Data\Default\Bookmarks"
    )

    foreach ($profile in $profiles) {
        foreach ($relative in $folders) {
            $src = Join-Path $profile.FullName $relative
            if (-not (Test-Path -LiteralPath $src)) { continue }
            $dst = Join-Path (Join-Path $destination $profile.Name) $relative
            $item = Get-Item -LiteralPath $src -Force -ErrorAction Stop
            if ($item.PSIsContainer) {
                New-Item -ItemType Directory -Path $dst -Force -ErrorAction Stop | Out-Null
                & robocopy.exe $src $dst /E /Z /COPY:DAT /DCOPY:DAT /XJ /R:2 /W:2 /NP /NDL /NFL /MT:8 | Out-Null
                $code = [int]$LASTEXITCODE
                $robocopyCodes.Add($code)
                $copiedDirectories++
                if ($code -ge 4) {
                    $errors.Add("Falha ou divergencia na copia de $($profile.Name)\$relative (Robocopy: $code)")
                }
            } else {
                $parent = Split-Path -Path $dst -Parent
                New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop | Out-Null
                & robocopy.exe (Split-Path -Path $src -Parent) $parent (Split-Path -Path $src -Leaf) /Z /COPY:DAT /R:2 /W:2 /NP /NDL /NFL | Out-Null
                $code = [int]$LASTEXITCODE
                $robocopyCodes.Add($code)
                $copiedDirectories++
                if ($code -ge 4) {
                    $errors.Add("Falha na copia de $($profile.Name)\$relative (Robocopy: $code)")
                }
            }
        }
    }

    if ($copiedDirectories -eq 0) {
        throw "Nenhuma pasta da lista de backup encontrada."
    }
    # Enumerar apenas os arquivos no novo diretorio, nunca arquivos antigos do chamado.
    $backedUp = Get-ChildItem -LiteralPath $destination -Recurse -File -Force -ErrorAction Stop
    foreach ($file in $backedUp) {
        $filesPresent++
        $totalBytes += [int64]$file.Length
    }
    if ($filesPresent -eq 0) {
        throw "Pasta de destino sem arquivos; nenhuma copia comprovada."
    }
    if ($errors.Count -gt 0) {
        throw ($errors -join "; ")
    }
    Result-Json "SUCCESS" "Copia das pastas selecionadas concluida; nao inclui imagem do sistema nem prova de restauracao."
    exit 0
}
catch {
    Result-Json "ERROR" ([string]$_.Exception.Message)
    exit 1
}
