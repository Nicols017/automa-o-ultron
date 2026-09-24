import json
import re
from typing import List, Dict, Any, Optional
from core.tools import BaseTool
from core.diagnostic_analyzer import DiagnosticAnalyzer

class AgenticLoop:
    def __init__(self, analyzer: DiagnosticAnalyzer, tools: List[BaseTool]):
        self.analyzer = analyzer
        self.tools = {t.name: t for t in tools}
        
    def _build_system_prompt(self, base_prompt: str) -> str:
        tools_desc = []
        for t in self.tools.values():
            tools_desc.append(f"- {t.name}: {t.description}\n  Parâmetros: {json.dumps(t.parameters['properties'], ensure_ascii=False)}")
            
        tool_rules = (
            "\n\n*** MODO AGENTE AUTÔNOMO ATIVADO ***\n"
            "Você é um agente com acesso a ferramentas. Você deve analisar a telemetria fornecida.\n"
            "Se detectar problemas que podem ser corrigidos via PowerShell (ex: disco cheio, serviço travado, IP de DNS incorreto), USE a ferramenta 'run_powershell' para tentar corrigir ANTES de dar o diagnóstico final.\n\n"
            "Ferramentas Disponíveis:\n"
            f"{chr(10).join(tools_desc)}\n\n"
            "Para USAR uma ferramenta, responda EXATAMENTE neste formato JSON e NADA MAIS:\n"
            "```json\n"
            "{\n"
            '  "action": "nome_da_ferramenta",\n'
            '  "args": {"param1": "valor"}\n'
            "}\n"
            "```\n"
            "Após executar a ferramenta, você receberá o resultado e poderá chamar outra ferramenta ou finalizar.\n"
            "Para FINALIZAR e entregar o laudo técnico (quando a máquina estiver pronta ou se for falha de hardware irreversível), responda EXATAMENTE neste JSON:\n"
            "```json\n"
            "{\n"
            '  "action": "finish",\n'
            '  "args": {"result": "Seu parecer técnico estruturado seguindo o prompt original..."}\n'
            "}\n"
            "```\n"
        )
        return base_prompt + tool_rules

    def run(self, prompt: str, base_system_prompt: str, max_steps: int = 4, log_callback=None) -> str:
        system_prompt = self._build_system_prompt(base_system_prompt)
        messages = [{"role": "user", "content": prompt}]
        
        def log(msg):
            print(msg)
            if log_callback:
                try:
                    log_callback({"type": "log", "message": msg, "level": "info"})
                except:
                    pass

        for step in range(max_steps):
            response_text = self.analyzer.chat(messages, system_prompt=system_prompt)
            
            # Tenta parsear a resposta como JSON (Ação do Agente)
            action_data = self._extract_json_action(response_text)
            
            if not action_data:
                # Se não usou a estrutura, pode ser que o modelo ignorou as instruções. 
                # Assumimos como finish.
                return response_text
                
            action = action_data.get("action")
            args = action_data.get("args", {})
            
            if action == "finish":
                return args.get("result", response_text)
                
            if action in self.tools:
                tool = self.tools[action]
                log(f"🧠 [AGENTE ULTRON] Autocura detectada. Chamando '{action}' em {args.get('ip', 'alvo')}...")
                try:
                    tool_result = tool.execute(**args)
                    log(f"✅ [AGENTE ULTRON] Resultado recebido (Tamanho: {len(tool_result)} bytes)")
                except Exception as e:
                    tool_result = f"Erro ao executar ferramenta: {e}"
                
                messages.append({"role": "assistant", "content": json.dumps(action_data)})
                messages.append({"role": "user", "content": f"RESULTADO DA FERRAMENTA {action}:\n{tool_result}\nAnalise o resultado e decida se precisa usar outra ferramenta ou chamar 'finish'."})
            else:
                messages.append({"role": "assistant", "content": json.dumps(action_data)})
                messages.append({"role": "user", "content": f"Erro: Ferramenta '{action}' não existe. Use 'finish' ou uma ferramenta válida."})
                
        return "Falha de Automação: O agente Ultron não conseguiu concluir a análise no limite de passos. Diagnóstico abortado."

    def _extract_json_action(self, text: str) -> Optional[Dict[str, Any]]:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        try:
            if match:
                return json.loads(match.group(1))
            
            if text.strip().startswith("{") and text.strip().endswith("}"):
                return json.loads(text.strip())
        except Exception:
            pass
        return None
