import ipaddress
import re


def installation_command(text, aliases):
    """Offer an explicit command for a single, known application."""
    match = re.fullmatch(
        r"(?:instala|instale|instalar)\s+(?:o\s+|a\s+)?(.+?)"
        r"(?:\s+(?:no|na)\s+(?:(?:pc|computador|máquina|maquina)\s+)?([\d.]+))?",
        text.strip(), re.IGNORECASE)
    if not match:
        return None
    package = aliases.get(match[1].casefold())
    if not package:
        return None
    if match[2]:
        try:
            target = ipaddress.IPv4Address(match[2])
        except ValueError:
            return "Informe o IPv4 completo para preparar o pedido."
        return f"Para confirmar a instalação, envie /instalar {target} {package}"
    return f"Para iniciar o pedido, envie /instalar {package}. Vou perguntar o IP do equipamento."
