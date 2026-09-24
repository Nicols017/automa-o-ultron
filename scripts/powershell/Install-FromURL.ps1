param(
    [Parameter(Mandatory=$true)]
    [string]$Url,
    
    [Parameter(Mandatory=$false)]
    [string]$SilentArgs = "/S",

    [Parameter(Mandatory=$false)]
    [string]$FileName = "Instalador_Download.exe"
)

$ErrorActionPreference = "Stop"

$tempPath = Join-Path $env:TEMP $FileName
Write-Host "Baixando $Url para $tempPath..."

try {
    # Ignora erros de certificado SSL se for HTTPS interno
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    
    Invoke-WebRequest -Uri $Url -OutFile $tempPath -UseBasicParsing
    
    Write-Host "Download concluído. Iniciando instalação silenciosa..."
    
    $process = Start-Process -FilePath $tempPath -ArgumentList $SilentArgs -Wait -PassThru
    
    if ($process.ExitCode -eq 0 -or $process.ExitCode -eq 3010) {
        Write-Host "Instalação finalizada com sucesso! (Código: $($process.ExitCode))"
    } else {
        Write-Host "Atenção: A instalação retornou o código $($process.ExitCode)."
    }
} catch {
    Write-Host "Erro durante download ou instalação: $($_.Exception.Message)"
} finally {
    if (Test-Path $tempPath) {
        Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
    }
}
