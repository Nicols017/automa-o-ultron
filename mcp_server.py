import asyncio
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
import mcp.types as types

from core.winrm_executor import WinRMExecutor
import json

# Instancia o executor do Ultron
winrm = WinRMExecutor()
server = Server("ultron-mcp-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_powershell",
            description="Executa um script PowerShell via WinRM na máquina alvo",
            inputSchema={
                "type": "object",
                "properties": {
                    "ip": {"type": "string"},
                    "command": {"type": "string"}
                },
                "required": ["ip", "command"]
            }
        ),
        types.Tool(
            name="check_winrm_status",
            description="Verifica se a porta 5985 está aberta na máquina",
            inputSchema={
                "type": "object",
                "properties": {
                    "ip": {"type": "string"}
                },
                "required": ["ip"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    if name == "run_powershell":
        ip = arguments.get("ip")
        cmd = arguments.get("command")
        res = winrm.run_powershell_code(ip, cmd)
        return [types.TextContent(
            type="text",
            text=f"Success: {res.get('success')}\nStdout: {res.get('stdout')}\nStderr: {res.get('stderr')}"
        )]
    elif name == "check_winrm_status":
        ip = arguments.get("ip")
        is_open = winrm.test_connection(ip)
        return [types.TextContent(
            type="text",
            text=f"WinRM on {ip} is {'OPEN' if is_open else 'CLOSED'}."
        )]
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    options = InitializationOptions(
        server_name="ultron-mcp-server",
        server_version="1.0.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        )
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            options,
            raise_exceptions=True
        )

if __name__ == "__main__":
    asyncio.run(main())
