"""Install once, then assess a separate read-only package inventory report."""
import json
import re
import uuid

INSTALL_MARKER = "ULTRON_INSTALL_ATTEMPTS_JSON:"
VERIFY_MARKER = "ULTRON_PACKAGE_VERIFICATION_JSON:"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+ -]{0,127}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+() -]{0,63}")
STATES = {"CONFIRMED_PRESENT", "UNCONFIRMED", "UNSUPPORTED_ID"}


# Only these diagnostic categories may reach chat or the installation API.
TRANSPORT_HINTS = {
    "TLS": "Confira a validade, o nome e a cadeia do certificado do equipamento.",
    "DNS": "Confira a resolução do nome do equipamento e a conexão com a rede.",
    "LISTENER": "Confira o serviço de gerenciamento e a porta configurada no equipamento.",
    "AUTHORIZATION": "Confira as permissões da conta no equipamento.",
    "AUTHENTICATION": "Confira a conta e a credencial Windows configuradas.",
    "KERBEROS": "Confira domínio, nome do equipamento e sincronização de horário.",
    "TIMEOUT": "O equipamento demorou a responder. Confira o estado da tarefa antes de repetir.",
    "TRANSPORT_UNKNOWN": "Confira o estado do equipamento antes de repetir o pedido.",
}


def transport_diagnostic(response):
    code = response.get("error_code")
    return code if isinstance(code, str) and code in TRANSPORT_HINTS else None


def package_list(packages):
    if not isinstance(packages, (list, tuple)) or not 1 <= len(packages) <= 50:
        raise ValueError("Informe de 1 a 50 pacotes.")
    result = []
    for value in packages:
        if not isinstance(value, str) or not ID.fullmatch(value.strip()):
            raise ValueError("Identificador de pacote invalido.")
        value = value.strip()
        if value.casefold() not in {x.casefold() for x in result}:
            result.append(value)
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Campo duplicado")
        result[key] = value
    return result


def _report(response, marker, requested, run_id, verification=False):
    text = response.get("stdout", "")
    if not isinstance(text, str) or len(text) > 1024 * 1024:
        raise ValueError("Saida invalida")
    lines = [line[len(marker):] for line in text.splitlines() if line.startswith(marker)]
    if len(lines) != 1:
        raise ValueError("Relatorio ausente ou duplicado")
    obj = json.loads(lines[0], object_pairs_hook=_object)
    if set(obj) != {"schema_version", "run_id", "packages"} or type(obj["schema_version"]) is not int or obj["schema_version"] != 1 or obj["run_id"] != run_id:
        raise ValueError("Relatorio divergente")
    rows = obj["packages"]
    if not isinstance(rows, list) or len(rows) != len(requested):
        raise ValueError("Pacotes divergentes")
    result = {}
    for row in rows:
        fields = {"requested", "status", "version"} if verification else {"requested", "manager", "exit_code", "reported_success"}
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Linha invalida")
        key = row["requested"]
        if not isinstance(key, str) or key.casefold() in result or key.casefold() not in {x.casefold() for x in requested}:
            raise ValueError("Pacote inesperado")
        if verification:
            if row["status"] not in STATES:
                raise ValueError("Estado invalido")
            version = row["version"]
            if version is not None and (not isinstance(version, str) or not VERSION.fullmatch(version) or version.casefold() in {"unknown", "latest"}):
                raise ValueError("Versao invalida")
            if row["status"] == "CONFIRMED_PRESENT" and not version:
                raise ValueError("Versao nao confirmada")
        else:
            if row["manager"] not in {"winget", "chocolatey", "scoop", "unknown"} or type(row["reported_success"]) is not bool:
                raise ValueError("Gerenciador invalido")
            code = row["exit_code"]
            if code is not None and (type(code) is not int or not -(2**31) <= code < 2**32):
                raise ValueError("Codigo invalido")
            if row["reported_success"] and (code not in (0, -1978335189)):
                raise ValueError("Sucesso inconsistente")
        result[key.casefold()] = row
    return result


def assess_installation(install, verification, requested, run_id):
    requested = package_list(requested)
    install = install if isinstance(install, dict) else {}
    verification = verification if isinstance(verification, dict) else {}
    uncertain = install.get("outcome") == "UNKNOWN" or install.get("status_code") == -1
    try:
        attempts = _report(install, INSTALL_MARKER, requested, run_id)
        attempt_valid = not uncertain and type(install.get("status_code")) is int
    except (ValueError, TypeError, KeyError):
        attempts, attempt_valid = {}, False
    try:
        if verification.get("outcome") == "UNKNOWN" or type(verification.get("status_code")) is not int or verification.get("status_code") != 0:
            raise ValueError()
        found = _report(verification, VERIFY_MARKER, requested, run_id, verification=True)
    except (ValueError, TypeError, KeyError):
        found = {}
    rows = []
    for package in requested:
        attempt, presence = attempts.get(package.casefold(), {}), found.get(package.casefold(), {})
        confirmed = presence.get("status") == "CONFIRMED_PRESENT"
        state = "CONFIRMED_PRESENT" if confirmed else "UNCONFIRMED"
        if confirmed and (not attempt_valid or attempt.get("reported_success") is not True):
            state = "PRESENT_WITH_UNCONFIRMED_INSTALL"
        rows.append(dict(requested=package, manager=attempt.get("manager", "unknown"),
                         installer_exit_code=attempt.get("exit_code"),
                         installer_reported_success=attempt.get("reported_success"),
                         status=state, version=presence.get("version") if confirmed else None))
    good = sum(row["status"] == "CONFIRMED_PRESENT" for row in rows)
    present = sum(row["version"] is not None for row in rows)
    if attempt_valid and good == len(rows) and install.get("status_code") == 0 and install.get("success") is True:
        status = "SUCCESS"
    elif present and attempt_valid:
        status = "PARTIAL"
    elif attempt_valid and all(row.get("reported_success") is False and row.get("exit_code") is not None for row in attempts.values()):
        status = "ERROR"
    else:
        status = "UNKNOWN"
    return dict(assessment_version=1, success=status == "SUCCESS", status=status,
                outcome="UNKNOWN" if status == "UNKNOWN" else "REPORTED",
                verification_method="winget_export", package_results=rows,
                evidence="SOFTWARE_PRESENCE_VERIFIED" if status == "SUCCESS" else "NONE",
                installation_diagnostic=transport_diagnostic(install),
                verification_diagnostic=transport_diagnostic(verification),
                credentials_missing=install.get("error_code") == "CREDENTIALS_MISSING",
                auth_failed=bool(install.get("auth_failed")),
                status_code=install.get("status_code", -1), stdout="", stderr="",
                install_report_valid=attempt_valid)


def install_and_verify(executor, ip, packages, interactive=False):
    packages = package_list(packages)
    run_id = uuid.uuid4().hex
    try:
        installed = executor.run_script_file(ip, "Install-UnifiedPackages.ps1",
            params={"Packages": packages, "Interactive": bool(interactive), "RunId": run_id})
    except Exception:
        installed = {"outcome": "UNKNOWN", "status_code": -1}
    if not isinstance(installed, dict):
        installed = {"outcome": "UNKNOWN", "status_code": -1}
    if installed.get("outcome") == "UNKNOWN" or installed.get("status_code") == -1 or installed.get("auth_failed"):
        return assess_installation(installed, {}, packages, run_id)
    try:
        verified = executor.run_script_file(ip, "Verify-InstalledPackages.ps1",
            params={"Packages": packages, "RunId": run_id})
    except Exception:
        verified = {}
    return assess_installation(installed, verified, packages, run_id)


def format_installation(result):
    status = result.get("status", "UNKNOWN")
    lines = ["INSTALACAO: " + status]
    if result.get("credentials_missing"):
        lines.append("A instalação não começou. Configure a credencial Windows autorizada para o equipamento e envie o pedido novamente.")
    for field, stage in (("installation_diagnostic", "Instalação"), ("verification_diagnostic", "Consulta de versão")):
        code = result.get(field)
        if code in TRANSPORT_HINTS:
            lines.append(f"{stage} ({code}). {TRANSPORT_HINTS[code]}")
    if result.get("auth_failed") and result.get("installation_diagnostic") != "AUTHENTICATION":
        lines.append("Autenticacao do executor recusada; instalacao nao confirmada.")
    for row in result.get("package_results", []):
        if row["version"]:
            description = "encontrado, versao " + row["version"]
            if row["status"] != "CONFIRMED_PRESENT":
                description += "; tentativa do instalador nao confirmada ou com erro"
        else:
            description = "presenca/versao nao confirmadas"
        code = row["installer_exit_code"]
        if code is not None:
            description += "; codigo do instalador " + str(code)
        lines.append(row["requested"] + ": " + description)
    lines.append("Presenca no inventario nao comprova funcionamento, licenca ou quem instalou o programa.")
    return "\n".join(lines)


def validated_summary(result):
    """Only typed assessments may promote software jobs beyond UNKNOWN."""
    if (not isinstance(result, dict) or type(result.get("assessment_version")) is not int
            or result["assessment_version"] != 1 or result.get("verification_method") != "winget_export"
            or result.get("status") not in {"SUCCESS", "PARTIAL", "ERROR", "UNKNOWN"}):
        raise ValueError("Avaliacao ausente")
    rows = result.get("package_results")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError("Pacotes invalidos")
    package_list([row.get("requested") for row in rows])
    if len({row["requested"].casefold() for row in rows}) != len(rows):
        raise ValueError("Pacotes duplicados")
    for row in rows:
        if set(row) != {"requested", "manager", "installer_exit_code", "installer_reported_success", "status", "version"}:
            raise ValueError("Campos invalidos")
        if row["manager"] not in {"unknown", "winget", "chocolatey", "scoop"} or row["status"] not in {"CONFIRMED_PRESENT", "PRESENT_WITH_UNCONFIRMED_INSTALL", "UNCONFIRMED"}:
            raise ValueError("Estado invalido")
        if row["installer_reported_success"] is not None and type(row["installer_reported_success"]) is not bool:
            raise ValueError("Tentativa invalida")
        if row["installer_exit_code"] is not None and type(row["installer_exit_code"]) is not int:
            raise ValueError("Codigo invalido")
        if row["version"] is not None and (not isinstance(row["version"], str) or not VERSION.fullmatch(row["version"]) or row["version"].casefold() in {"unknown", "latest"}):
            raise ValueError("Versao invalida")
        if row["status"] != "UNCONFIRMED" and not row["version"]:
            raise ValueError("Presenca sem versao")
    if result["status"] == "SUCCESS" and (result.get("success") is not True or not result.get("install_report_valid")
            or result.get("status_code") != 0 or any(row["status"] != "CONFIRMED_PRESENT"
            or row["installer_reported_success"] is not True for row in rows)):
        raise ValueError("Sucesso sem confirmacao")
    return result["status"], rows

def verify_preparation_packages(executor, ip, packages):
    """Check requested IDs after preparation, without another install."""
    packages = package_list(packages)
    nonce = uuid.uuid4().hex
    response = executor.run_script_file(ip, "Verify-InstalledPackages.ps1",
                                       params={"Packages": packages, "RunId": nonce})
    if response.get("success") is not True or response.get("status_code") != 0:
        return {package: None for package in packages}
    found = _report(response, VERIFY_MARKER, packages, nonce, verification=True)
    return {package: (found[package.casefold()]["version"]
                      if found[package.casefold()]["status"] == "CONFIRMED_PRESENT" else None)
            for package in packages}
