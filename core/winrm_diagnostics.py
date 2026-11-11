"""Pure classification: no network, secrets, configuration changes or retries."""


def classify_winrm_error(error):
    text = str(error).lower()
    if any(x in text for x in ("certificate", "ssl", "tls")):
        code, hint = "TLS", "Confira CA, validade e SAN; use o nome DNS do certificado."
    elif any(x in text for x in ("401", "credentials were rejected", "unauthorized")):
        code, hint = "AUTHENTICATION", "Confira conta, senha e dominio/host; evite bloquear a conta."
    elif any(x in text for x in ("access is denied", "acesso negado", "0x80070005")):
        code, hint = "AUTHORIZATION", "Confira endpoint, grupo e UAC remoto; nao desative UAC automaticamente."
    elif any(x in text for x in ("name resolution", "getaddrinfo", "nodename")):
        code, hint = "DNS", "Confira DNS/FQDN e rota VPN."
    elif any(x in text for x in ("timed out", "timeout")):
        code, hint = "TIMEOUT", "Confira rota, firewall, listener e quotas; execucao pode ter ocorrido."
    elif any(x in text for x in ("refused", "10061")):
        code, hint = "LISTENER", "Confira WinRM nativo, listener e porta 5985/5986."
    elif any(x in text for x in ("kerberos", "spn", "clock skew")):
        code, hint = "KERBEROS", "Confira DNS, SPN, dominio e relogio; prefira FQDN."
    else:
        code, hint = "TRANSPORT_UNKNOWN", "Confira logs WinRM e resultado remoto antes de repetir."
    return dict(error_code=code, stderr=hint, outcome="UNKNOWN", retry_safe=False)
