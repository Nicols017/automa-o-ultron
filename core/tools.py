import json
from typing import Dict, Any, List
from core.winrm_executor import WinRMExecutor

class BaseTool:
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def execute(self, **kwargs) -> Any:
        raise NotImplementedError()

    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

class RunPowerShellTool(BaseTool):
    name = "run_powershell"
    description = "Executa um comando ou script PowerShell em uma máquina alvo via WinRM e retorna a saída. Use para corrigir problemas detectados na telemetria, reiniciar serviços (ex: msiserver), ou auto-cura."
    parameters = {
        "type": "object",
        "properties": {
            "ip": {"type": "string", "description": "IP da máquina alvo (ex: 192.168.57.100)"},
            "command": {"type": "string", "description": "Código PowerShell para executar"}
        },
        "required": ["ip", "command"]
    }
    
    def __init__(self, winrm_executor: WinRMExecutor):
        self.winrm = winrm_executor
        
    def execute(self, ip: str, command: str) -> str:
        res = self.winrm.run_powershell_code(ip, command)
        if res.get("success"):
            return f"SUCESSO:\n{res.get('stdout', '')}"
        else:
            return f"FALHA:\n{res.get('stderr', '')}\nSTDOUT:\n{res.get('stdout', '')}"
