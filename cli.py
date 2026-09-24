from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
import time
import json
import os

console = Console()

def generate_dashboard() -> Layout:
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    
    layout["header"].update(Panel("[bold cyan]🤖 Ultron Lab Automation - Terminal Dashboard[/]", style="white on blue"))
    
    # Monta a tabela da bancada
    table = Table(title="Máquinas na Bancada (Mock / Live)")
    table.add_column("IP", justify="right", style="cyan", no_wrap=True)
    table.add_column("Hostname", style="magenta")
    table.add_column("Status WinRM", justify="center")
    table.add_column("Última Ação")

    # Exemplo estático (em prod, isso consumiria o DB ou core/network_scanner.py)
    table.add_row("192.168.57.100", "PC-CLIENTE-01", "[green]Online[/]", "Auto-Cura Concluída")
    table.add_row("192.168.57.101", "DESKTOP-ABC", "[red]Offline[/]", "Aguardando Boot")
    
    layout["main"].update(Panel(table, title="[yellow]Status em Tempo Real[/]"))
    
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
        
    layout["footer"].update(Panel(f"🧠 Custos IA (Sessão): {tokens} Tokens | {cost} | [green]Pronto para comandos.[/]", style="bold green"))
    
    return layout

if __name__ == "__main__":
    console.clear()
    with Live(generate_dashboard(), refresh_per_second=1) as live:
        try:
            while True:
                live.update(generate_dashboard())
                time.sleep(2)
        except KeyboardInterrupt:
            console.print("[red]Encerrando Ultron TUI...[/]")
