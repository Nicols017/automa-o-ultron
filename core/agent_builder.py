"""
Ultron Agent Auto-Builder & Version Synchronizer
Garante que o executável UltronAgent.exe seja automaticamente recompilado
sempre que o código C# (UltronAgent.cs) for alterado, evitando a entrega de versões defasadas.
"""

import os
import re
import shutil
import subprocess
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("ultron_agent_builder")

CSC_PATHS = [
    r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
]

class AgentBuilder:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.agent_cs_path = os.path.join(self.base_dir, "agent", "UltronAgent.cs")
        self.agent_exe_path = os.path.join(self.base_dir, "agent", "UltronAgent.exe")
        self.downloads_dir = os.path.join(self.base_dir, "static", "downloads")
        self.static_exe_path = os.path.join(self.downloads_dir, "UltronAgent.exe")
        os.makedirs(self.downloads_dir, exist_ok=True)

    def find_compiler(self) -> Optional[str]:
        for p in CSC_PATHS:
            if os.path.exists(p):
                return p
        return shutil.which("csc.exe")

    def get_source_version(self) -> str:
        """Extrai a versão declarada em CurrentVersion dentro do UltronAgent.cs"""
        if not os.path.exists(self.agent_cs_path):
            return "2.2.0"
        try:
            with open(self.agent_cs_path, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(r'public\s+const\s+string\s+CurrentVersion\s*=\s*"([^"]+)"', content)
            if m:
                return m.group(1)
        except Exception as e:
            logger.warning(f"Erro ao ler versão de UltronAgent.cs: {e}")
        return "2.2.0"

    def needs_compilation(self) -> bool:
        """Verifica se o código fonte C# é mais recente que o executável compilado"""
        if not os.path.exists(self.agent_cs_path):
            return False
        if not os.path.exists(self.agent_exe_path) or not os.path.exists(self.static_exe_path):
            return True
        cs_mtime = os.path.getmtime(self.agent_cs_path)
        exe_mtime = os.path.getmtime(self.agent_exe_path)
        return cs_mtime > exe_mtime

    def compile(self, force: bool = False) -> Dict[str, Any]:
        """Recompila o UltronAgent.cs para UltronAgent.exe e atualiza os diretórios de distribuição"""
        if not force and not self.needs_compilation():
            version = self.get_source_version()
            return {
                "success": True,
                "recompiled": False,
                "version": version,
                "exe_path": self.agent_exe_path,
                "message": f"Executável UltronAgent.exe já está atualizado (v{version})."
            }

        compiler = self.find_compiler()
        if not compiler:
            return {
                "success": False,
                "error": "Compilador C# (csc.exe) não encontrado no sistema."
            }

        logger.info(f"🔨 Compilando UltronAgent.cs com {compiler}...")
        cmd = [
            compiler,
            "/target:exe",
            "/platform:anycpu",
            "/optimize+",
            "/r:System.Management.dll",
            "/r:System.ServiceProcess.dll",
            "/r:System.Drawing.dll",
            "/r:System.Windows.Forms.dll",
            f"/out:{self.agent_exe_path}",
            self.agent_cs_path
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if proc.returncode != 0:
                logger.error(f"Erro na compilação do C#: {proc.stderr or proc.stdout}")
                return {
                    "success": False,
                    "error": f"Falha na compilação: {proc.stderr or proc.stdout}"
                }

            # Copia para static/downloads/UltronAgent.exe
            shutil.copy2(self.agent_exe_path, self.static_exe_path)

            version = self.get_source_version()
            versioned_exe = os.path.join(self.downloads_dir, f"UltronAgent_v{version}.exe")
            shutil.copy2(self.agent_exe_path, versioned_exe)

            logger.info(f"✅ UltronAgent v{version} compilado e publicado com sucesso!")
            return {
                "success": True,
                "recompiled": True,
                "version": version,
                "exe_path": self.agent_exe_path,
                "versioned_exe": versioned_exe,
                "size_bytes": os.path.getsize(self.agent_exe_path)
            }
        except Exception as e:
            logger.error(f"Exceção ao compilar UltronAgent: {e}")
            return {"success": False, "error": str(e)}

    def get_latest_agent_binary(self) -> Dict[str, Any]:
        """Garante a compilação mais recente e retorna os caminhos e versão do executável pronto"""
        self.compile(force=False)
        version = self.get_source_version()
        file_path = self.agent_exe_path if os.path.exists(self.agent_exe_path) else self.static_exe_path
        size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        return {
            "version": version,
            "file_path": file_path,
            "filename": f"UltronAgent_v{version}.exe",
            "size_bytes": size
        }

agent_builder = AgentBuilder()
