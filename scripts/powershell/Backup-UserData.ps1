# Script de Backup Automático de Arquivos de Usuário para o Servidor do Laboratório
param (
    [string]$TargetServer = "192.168.57.112",
    [string]$ClientName = "SUPERIOR",
    [string]$TicketNumber = "10938",
    [string]$SourceDrive = "C:"
)

$serial = (Get-CimInstance Win32_BIOS).SerialNumber -replace '[^a-zA-Z0-9_-]', ''
$folderName = if ($TicketNumber) { "$ClientName - $TicketNumber" } else { "$ClientName - $serial" }
$backupDest = "\\$TargetServer\Backups\$folderName"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 💾 ULTRON - INICIANDO BACKUP DE DADOS ($serial)" -ForegroundColor Cyan
Write-Host " Destino: $backupDest" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

if (-not (Test-Path $backupDest)) {
    New-Item -Path $backupDest -ItemType Directory -Force | Out-Null
}

$userFolders = Get-ChildItem "$SourceDrive\Users" -Directory | Where-Object { $_.Name -notin @("Public", "Default", "All Users", "Default User") }

$foldersToCopy = @("Desktop", "Documents", "Downloads", "Pictures", "Favorites", "AppData\Local\Google\Chrome\User Data\Default\Bookmarks")

foreach ($user in $userFolders) {
    Write-Host "Processando perfil: $($user.Name)..." -ForegroundColor Yellow
    $userDest = "$backupDest\$($user.Name)"
    
    foreach ($folder in $foldersToCopy) {
        $src = "$($user.FullName)\$folder"
        $dst = "$userDest\$folder"
        if (Test-Path $src) {
            Write-Host "Copiando $folder..." -ForegroundColor Gray
            robocopy "$src" "$dst" /E /R:1 /W:1 /NP /NDL /NFL /MT:8 | Out-Null
        }
    }
}

Write-Host "✅ Backup concluído com sucesso em $backupDest!" -ForegroundColor Green
