#!/bin/bash
# Ultron Automation Server - Startup Script (Linux)
# Pense Rede Network Solutions - Laboratorio de TI

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "  ULTRON AUTOMATION SERVER - LINUX DAEMON (24/7)"
echo "  Pense Rede Lab | Server IP: 192.168.57.43"
echo "========================================================"
echo ""

# Detecta ou cria ambiente virtual Python
if [ -d "venv" ]; then
    echo "[*] Ativando virtualenv Python (venv)..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "[*] Ativando virtualenv Python (.venv)..."
    source .venv/bin/activate
else
    echo "[!] Virtualenv não encontrado. Usando python3 do sistema..."
fi

# Instala dependências se necessário
if [ -f "requirements.txt" ]; then
    pip install -q -r requirements.txt || true
fi

echo "[*] Iniciando Ultron Server na porta 7000..."
python3 main.py
