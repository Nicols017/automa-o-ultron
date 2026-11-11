"""Exact, offline inventory lookup. A mapping never proves the host's identity."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time


class InventoryError(ValueError):
    pass


def reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
        raise InventoryError("Identificador invalido.")
    return value.casefold()


def mac(value):
    compact = re.sub(r"[:-]", "", value)
    return compact.casefold() if re.fullmatch(r"[a-fA-F0-9]{12}", compact) else ""


class DeviceInventory:
    def __init__(self, path=None, clock=time.time, max_age=900):
        self.path = path or os.environ.get("ULTRON_DEVICE_INVENTORY_FILE", "")
        self.clock, self.max_age = clock, max_age

    def resolve(self, query):
        key = reference(query)
        try:
            if not self.path:
                raise ValueError()
            path = Path(self.path)
            if os.name == "posix" and path.stat().st_mode & 0o022:
                raise ValueError()
            if path.stat().st_size > 1024 * 1024:
                raise ValueError()
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list) or len(records) > 1000:
                raise ValueError()
            rows = []
            now = self.clock()
            for item in records:
                if not isinstance(item, dict) or set(item) != {"serial", "hostname", "mac", "ip", "seen_at"}:
                    raise ValueError()
                serial, hostname = reference(item["serial"]), reference(item["hostname"])
                address = ipaddress.IPv4Address(item["ip"])
                timestamp = item["seen_at"]
                if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                        or not timestamp <= now or timestamp < now - self.max_age
                        or address.is_unspecified or address.is_multicast or not mac(item["mac"])):
                    raise ValueError()
                rows.append(dict(serial=serial, hostname=hostname, mac=mac(item["mac"]), ip=str(address)))
            matched = [row for row in rows if key in (row["serial"], row["hostname"], row["mac"])
                       or (mac(key) and mac(key) == row["mac"])]
            if len(matched) != 1:
                raise InventoryError("Equipamento ausente ou identificador ambiguo; informe o IP completo.")
            selected = matched[0]
            if any(row is not selected and any(row[field] == selected[field]
                       for field in ("serial", "hostname", "mac", "ip")) for row in rows):
                raise InventoryError("Inventario conflitante; nao selecionei equipamento.")
            return selected
        except InventoryError:
            raise
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            raise InventoryError("Inventario indisponivel, invalido ou desatualizado; informe o IP completo.") from None


def device_binding(device):
    return hashlib.sha256(json.dumps(device, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
