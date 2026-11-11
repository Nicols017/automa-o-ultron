#requires -Version 5.1
<#
Entrada antiga mantida para impedir provisionamento inseguro.
UltronAgent e WinRM nativo sao componentes separados.
Consulte docs/WINDOWS_AGENT_REVIEW.md e agent/Install-Agent.ps1.
#>
[CmdletBinding()]
param(
    [string]$UltronServerUrl,
    [string]$ClientId,
    [string]$TechUserId,
    [switch]$AutoRun
)
throw 'Bootstrap legado desativado: nao cria contas, altera WinRM ou inicia pipelines. Use o instalador revisado.'
