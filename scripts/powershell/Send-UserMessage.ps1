# Script para Exibir Notificação/Mensagem na Tela do Usuário Remoto
param (
    [string]$Message = "Notificação do Suporte de TI (Ultron)",
    [string]$Title = "🤖 ULTRON - SUPORTE DE TI"
)

$outputMsg = "$Title`n`n$Message"

# 1. Método Principal: msg.exe nativo do Windows (Exibe janela modal na tela de todas as sessões ativas)
try {
    $msgProc = Start-Process -FilePath "msg.exe" -ArgumentList "* /TIME:0 `"$outputMsg`"" -PassThru -NoNewWindow -Wait -ErrorAction Stop
    if ($msgProc.ExitCode -eq 0) {
        Write-Output "SUCCESS: Mensagem exibida na tela do usuário via msg.exe."
        exit 0
    }
} catch {
    # Fallback se msg.exe falhar
}

# 2. Método Alternativo: WTSRegisterSessionNotification / WTSSendMessage via C# PInvoke
$csharpSource = @"
using System;
using System.Runtime.InteropServices;

public class RemoteNotifier {
    [DllImport("wtsapi32.dll", SetLastError = true)]
    public static extern bool WTSSendMessage(
        IntPtr hServer,
        int SessionId,
        String pTitle,
        int TitleLength,
        String pMessage,
        int MessageLength,
        int Style,
        int Timeout,
        out int pResponse,
        bool bWait
    );

    public static bool ShowMessage(string title, string message) {
        int response = 0;
        // Session -1 = WTS_CURRENT_SESSION / Active Console Session
        return WTSSendMessage(IntPtr.Zero, -1, title, title.Length * 2, message, message.Length * 2, 0x00000040, 0, out response, false);
    }
}
"@

try {
    Add-Type -TypeDefinition $csharpSource -ErrorAction SilentlyContinue
    [RemoteNotifier]::ShowMessage($Title, $Message)
    Write-Output "SUCCESS: Mensagem enviada via WTSSendMessage."
} catch {
    Write-Output "PARTIAL: Tentativa de envio concluída."
}
