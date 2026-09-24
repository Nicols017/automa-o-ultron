param(
    [Parameter(Mandatory=$true)]
    [string]$UncPath,
    
    [Parameter(Mandatory=$false)]
    [string]$SilentArgs = "/S",

    [Parameter(Mandatory=$false)]
    [string]$ShareUser = "",

    [Parameter(Mandatory=$false)]
    [string]$SharePass = ""
)

$ErrorActionPreference = "Stop"

$fileName = Split-Path $UncPath -Leaf
$tempPath = Join-Path $env:TEMP $fileName

Write-Host "Iniciando processo de cópia via rede local..."
Write-Host "Origem: $UncPath"
Write-Host "Destino: $tempPath"

try {
    # Mapeia a rede temporariamente se credenciais forem fornecidas
    if ($ShareUser -and $SharePass) {
        $shareRoot = "\\" + ($UncPath -split "\\")[2] + "\" + ($UncPath -split "\\")[3]
        Write-Host "Autenticando no compartilhamento $shareRoot..."
        net use $shareRoot /user:$ShareUser $SharePass 2>&1 | Out-Null
    }

    # Copia o arquivo para a máquina local (evita bloqueios de execução via rede no WinRM)
    Copy-Item -Path $UncPath -Destination $tempPath -Force
    
    Write-Host "Cópia concluída. Iniciando instalação silenciosa..."
    
    $process = Start-Process -FilePath $tempPath -ArgumentList $SilentArgs -Wait -PassThru
    
    if ($process.ExitCode -eq 0 -or $process.ExitCode -eq 3010) {
        Write-Host "Instalação finalizada com sucesso! (Código: $($process.ExitCode))"
    } else {
        Write-Host "Atenção: A instalação retornou o código $($process.ExitCode)."
    }
} catch {
    Write-Host "Erro durante cópia ou instalação: $($_.Exception.Message)"
} finally {
    # Limpeza
    if (Test-Path $tempPath) {
        Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
    }
    if ($ShareUser -and $SharePass) {
        $shareRoot = "\\" + ($UncPath -split "\\")[2] + "\" + ($UncPath -split "\\")[3]
        net use $shareRoot /delete /y 2>&1 | Out-Null
    }
}
