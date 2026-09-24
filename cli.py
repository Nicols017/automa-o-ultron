from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
import time
import json
import threading

from core.network_scanner import NetworkScanner

console = Console()

# Estado global da bancada
live_devices = []
is_scanning = True

def scanner_worker():
    """Roda em background atualizando a lista de máquinas ativas na bancada"""
    global live_devices, is_scanning
    scanner = NetworkScanner()
    while True:
        try:
            # Faz varredura na rede com timeout maior para não pular máquinas lentas
            devices = scanner.scan_network(max_threads=150, timeout=1.5)
            live_devices = devices
            is_scanning = False
        except Exception:
            pass
        # Espera 10 segundos até a próxima varredura
        time.sleep(10)

def generate_dashboard() -> Layout:
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    
    layout["header"].update(Panel("[bold cyan]🤖 Ultron Lab Automation - Terminal Dashboard[/]", style="white on blue"))
    
    # Monta a tabela da bancada
    table_title = "Máquinas na Bancada (Live)" if not is_scanning else "Máquinas na Bancada (Varrendo a rede... 🔄)"
    table = Table(title=table_title, expand=True)
    table.add_column("IP", justify="right", style="cyan", no_wrap=True)
    table.add_column("Hostname / Bancada", style="magenta")
    table.add_column("MAC / Vendor", style="yellow")
    table.add_column("Status WinRM", justify="center")

    if not live_devices and not is_scanning:
        table.add_row("Nenhum", "Nenhuma máquina", "N/A", "[red]N/A[/]")
    else:
        for dev in live_devices:
            ip = dev.get("ip", "Desconhecido")
            host = f"{dev.get('hostname', '')} / {dev.get('bench_name', '')}"
            mac_vendor = f"{dev.get('mac', '')} ({dev.get('vendor', '')})"
            status = "[green]Online (Porta 5985)[/]" if dev.get("winrm_ready") else "[red]Offline / Fechada[/]"
            
            table.add_row(ip, host, mac_vendor, status)
    
    layout["main"].update(Panel(table, title="[yellow]Monitoramento em Tempo Real[/]"))
    
    # Consumo de tokens
    cost = "$0.00"
    tokens = "0"
    try:
        with open("reports/cost_tracking.json", "r") as f:
            data = json.load(f)
            cost = f"${data.get('total_cost_usd', 0):.4f}"
            tokens = str(data.get("total_tokens", 0))
    except:
        pass
        
    layout["footer"].update(Panel(f"🧠 Custos IA (Sessão): {tokens} Tokens | {cost} | [green]Serviço Operante.[/]", style="bold green"))
    
    return layout

if __name__ == "__main__":
    console.clear()
    
    # Inicia a thread de scanner em background para não travar a TUI
    scan_thread = threading.Thread(target=scanner_worker, daemon=True)
    scan_thread.start()

    with Live(generate_dashboard(), refresh_per_second=2) as live:
        try:
            while True:
                live.update(generate_dashboard())
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("[red]Encerrando Ultron TUI...[/]")
