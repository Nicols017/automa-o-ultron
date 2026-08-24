"""
Módulo de Sincronização com a Dashboard Milvus (192.168.57.7) - Pense Rede
Coleta e sincroniza empresas/clientes e chamados em aberto em tempo real.
Inclui suporte a teste de conexão com telemetria e fallback de simulação para desenvolvimento.
"""

import time
import requests
from typing import List, Dict, Any, Optional

class MilvusSyncService:
    def __init__(self, base_url: str = "http://192.168.57.7", api_token: str = "", cache_ttl: int = 60, demo_mode: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.cache_ttl = cache_ttl
        self.demo_mode = demo_mode
        self._companies_cache: List[str] = []
        self._companies_last_fetch = 0
        self._tickets_cache: List[Dict[str, Any]] = []
        self._tickets_last_fetch = 0

    def update_config(self, base_url: Optional[str] = None, api_token: Optional[str] = None, demo_mode: Optional[bool] = None):
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        if api_token is not None:
            self.api_token = api_token
        if demo_mode is not None:
            self.demo_mode = demo_mode
        # Invalida cache ao mudar configuração
        self._companies_cache = []
        self._tickets_cache = []

    def _get_headers(self, custom_token: Optional[str] = None) -> Dict[str, str]:
        """Constrói os cabeçalhos de autenticação para a Dashboard Milvus"""
        headers = {}
        token = custom_token if custom_token is not None else self.api_token
        if token:
            headers["x-api-key"] = token
            headers["Authorization"] = token
        return headers

    def test_connection(self, custom_url: Optional[str] = None, custom_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Testa a conectividade com o servidor da Dashboard Milvus, retornando latência e status dos endpoints.
        """
        target_url = (custom_url or self.base_url).rstrip("/")
        headers = self._get_headers(custom_token)
        has_token = bool(custom_token if custom_token is not None else self.api_token)
        
        t0 = time.time()
        res = {
            "target_url": target_url,
            "has_token": has_token,
            "online": False,
            "latency_ms": 0,
            "status_code": 0,
            "message": "",
            "demo_mode": self.demo_mode,
            "endpoints": {
                "chamados_abertos": {"status": "untested", "code": 0},
                "chamados_pendentes": {"status": "untested", "code": 0},
                "contatos": {"status": "untested", "code": 0}
            }
        }

        try:
            r = requests.get(f"{target_url}/api/chamados-abertos", headers=headers, timeout=2.0)
            latency = round((time.time() - t0) * 1000, 1)
            res["latency_ms"] = latency
            res["status_code"] = r.status_code
            res["endpoints"]["chamados_abertos"] = {"status": "ok" if r.status_code == 200 else "error", "code": r.status_code}
            
            # Testa endpoints complementares se o servidor respondeu
            if r.status_code in (200, 401, 403):
                try:
                    r_pend = requests.get(f"{target_url}/api/chamados-pendentes", headers=headers, timeout=1.5)
                    res["endpoints"]["chamados_pendentes"] = {"status": "ok" if r_pend.status_code == 200 else "error", "code": r_pend.status_code}
                except Exception:
                    res["endpoints"]["chamados_pendentes"] = {"status": "timeout", "code": 0}

                try:
                    r_cont = requests.get(f"{target_url}/api/contatos", headers=headers, timeout=1.5)
                    res["endpoints"]["contatos"] = {"status": "ok" if r_cont.status_code == 200 else "error", "code": r_cont.status_code}
                except Exception:
                    res["endpoints"]["contatos"] = {"status": "timeout", "code": 0}

            if r.status_code == 200:
                res["online"] = True
                res["message"] = f"Conexão com a Dashboard Milvus estabelecida com sucesso ({latency}ms)"
            elif r.status_code in (401, 403):
                res["online"] = False
                res["message"] = f"Servidor Milvus acessível ({latency}ms), porém o Token de API foi rejeitado (HTTP {r.status_code})"
            else:
                res["message"] = f"Servidor Milvus respondeu com código HTTP {r.status_code}"
        except requests.exceptions.ConnectTimeout:
            res["message"] = f"Timeout ao conectar em {target_url}. Servidor offline ou fora da rota de rede."
        except requests.exceptions.ConnectionError:
            res["message"] = f"Falha de conexão com {target_url}. Verifique se o IP 192.168.57.7 está ativo na rede."
        except Exception as e:
            res["message"] = f"Erro ao testar conexão: {str(e)}"

        return res

    def is_online(self, timeout: float = 1.5) -> bool:
        """Verifica rapidamente se a Dashboard Milvus está acessível na rede ou em modo demo"""
        if self.demo_mode:
            return True
        try:
            r = requests.get(f"{self.base_url}/api/chamados-abertos", headers=self._get_headers(), timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    def get_demo_companies(self) -> List[str]:
        return [
            "AGILIS LABORATORIO DE PATOLOGIA",
            "ANGIO SUTURE",
            "ARAUJO & ADVOGADOS ASSOCIADOS",
            "AUTENTICA",
            "CSV BENETECH BRASIL",
            "CONDOMINIO DO SHOPPING VITORIA",
            "EXTINBRAS EXTINTORES DO BRASIL",
            "MACHINE DESENVOLVIMENTO LTDA",
            "MEDICAL HOPE ASSISTENCIA TECNICA",
            "NOVA VIA PEÇAS E ACESSORIOS",
            "PENSE REDE NETWORK SOLUTION",
            "REDE BACHOUR",
            "SUPERIOR TRANSPORTES",
            "WHITE GROUP HOLDING"
        ]

    def get_demo_tickets(self) -> List[Dict[str, Any]]:
        return [
            {
                "codigo": 10452,
                "assunto": "Setup e Implantação de Notebook Dell Vostro para Engenharia",
                "cliente": "CSV BENETECH BRASIL",
                "tecnico": "Nicolas Silva",
                "status": "Em Atendimento",
                "data_criacao": "2026-08-23 09:15:00"
            },
            {
                "codigo": 10448,
                "assunto": "Formatação, Ingresso no Domínio e Agente Milvus",
                "cliente": "NOVA VIA PEÇAS E ACESSORIOS",
                "tecnico": "Nicolas Silva",
                "status": "Aberto",
                "data_criacao": "2026-08-23 08:30:00"
            },
            {
                "codigo": 10439,
                "assunto": "Backup de Dados e Substituição de SSD NVMe",
                "cliente": "SUPERIOR TRANSPORTES",
                "tecnico": "Suporte N2",
                "status": "Pausado",
                "data_criacao": "2026-08-22 17:45:00"
            },
            {
                "codigo": 10425,
                "assunto": "Instalação de Softwares Padrão e VPN Corporativa",
                "cliente": "PENSE REDE NETWORK SOLUTION",
                "tecnico": "Nicolas Silva",
                "status": "Aberto",
                "data_criacao": "2026-08-22 14:10:00"
            }
        ]

    def get_companies(self, force_refresh: bool = False) -> List[str]:
        """
        Retorna a lista de empresas cadastradas na Dashboard Milvus (/api/contatos).
        Possui cache em memória para respostas instantâneas.
        """
        if self.demo_mode:
            return self.get_demo_companies()

        now = time.time()
        if not force_refresh and self._companies_cache and (now - self._companies_last_fetch < self.cache_ttl):
            return self._companies_cache

        try:
            r = requests.get(f"{self.base_url}/api/contatos", headers=self._get_headers(), timeout=2.5)
            if r.status_code == 200:
                data = r.json()
                contacts = data.get("contacts", [])
                companies = sorted(list(set([
                    c.get("company", "").strip()
                    for c in contacts
                    if c.get("company") and len(c.get("company", "").strip()) > 1
                ])))
                if companies:
                    self._companies_cache = companies
                    self._companies_last_fetch = now
                    return self._companies_cache
        except Exception as e:
            print(f"⚠️ [MILVUS SYNC] Falha ao consultar empresas em {self.base_url}: {e}")

        # Se falhou a requisição ao vivo e não temos cache, usa fallback das empresas base
        if not self._companies_cache:
            return self.get_demo_companies()

        return self._companies_cache

    def get_open_tickets(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Retorna os chamados abertos e pendentes na Dashboard Milvus (/api/chamados-pendentes e /api/chamados-abertos).
        """
        if self.demo_mode:
            return self.get_demo_tickets()

        now = time.time()
        if not force_refresh and self._tickets_cache and (now - self._tickets_last_fetch < self.cache_ttl):
            return self._tickets_cache

        tickets = []
        seen_codes = set()

        # 1. Chamados Pendentes / Pausados
        try:
            r_pend = requests.get(f"{self.base_url}/api/chamados-pendentes", headers=self._get_headers(), timeout=2.5)
            if r_pend.status_code == 200:
                for item in r_pend.json():
                    code = item.get("codigo")
                    if code and code not in seen_codes:
                        seen_codes.add(code)
                        tickets.append({
                            "codigo": code,
                            "assunto": item.get("assunto", "Sem assunto"),
                            "cliente": item.get("cliente", ""),
                            "tecnico": item.get("tecnico", ""),
                            "status": item.get("status", "Pausado"),
                            "data_criacao": item.get("data_criacao", "")
                        })
        except Exception as e:
            print(f"⚠️ [MILVUS SYNC] Erro ao buscar chamados pendentes: {e}")

        # 2. Chamados Abertos por Operador
        try:
            r_open = requests.get(f"{self.base_url}/api/chamados-abertos", headers=self._get_headers(), timeout=2.5)
            if r_open.status_code == 200:
                for group in r_open.json():
                    for ch in group.get("chamados", []):
                        code = ch.get("codigo")
                        if code and code not in seen_codes:
                            seen_codes.add(code)
                            tickets.append({
                                "codigo": code,
                                "assunto": ch.get("assunto", "Sem assunto"),
                                "cliente": ch.get("cliente", ""),
                                "tecnico": group.get("operador", "Sem técnico"),
                                "status": ch.get("status", "Aberto"),
                                "data_criacao": ch.get("data_criacao", "")
                            })
        except Exception as e:
            print(f"⚠️ [MILVUS SYNC] Erro ao buscar chamados abertos: {e}")

        if tickets:
            # Ordena pelos códigos mais recentes
            tickets.sort(key=lambda x: x.get("codigo", 0), reverse=True)
            self._tickets_cache = tickets
            self._tickets_last_fetch = now
            return self._tickets_cache

        # Se falhou e não temos cache, usa chamados de fallback
        if not self._tickets_cache:
            return self.get_demo_tickets()

        return self._tickets_cache

    def download_client_agent(self, client_id: str, client_name: str, token: str, output_dir: str) -> Dict[str, Any]:
        """
        Baixa o instalador do Agente Milvus oficial para um cliente usando seu Token e salva como MSI/EXE.
        """
        import os
        import re

        if not token or "TOKEN_MILVUS" in token:
            return {
                "success": False,
                "error": f"Token inválido ou não cadastrado para o cliente '{client_name}'."
            }

        os.makedirs(output_dir, exist_ok=True)
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '', client_name.replace(" ", "_"))
        target_filename = f"Milvus_{clean_name}.msi"
        target_path = os.path.join(output_dir, target_filename)

        # URLs de download do Milvus
        download_urls = [
            f"https://milvus.com.br/download/agent?token={token}&format=msi",
            f"https://milvus.com.br/download/agent?token={token}",
            f"https://painel.milvus.com.br/download/agent?token={token}&type=msi",
            f"https://api.milvus.com.br/v2/dispositivos/download-agente?token={token}&tipo=msi"
        ]

        headers = {
            "User-Agent": "UltronLabAutomation/1.4.0 (Windows NT 10.0; Win64; x64)"
        }

        downloaded = False
        last_error = ""

        for url in download_urls:
            try:
                r = requests.get(url, headers=headers, stream=True, timeout=15)
                if r.status_code == 200 and len(r.content) > 1024:
                    with open(target_path, "wb") as f:
                        f.write(r.content)
                    downloaded = True
                    break
                else:
                    last_error = f"HTTP {r.status_code}: {r.text[:100]}"
            except Exception as e:
                last_error = str(e)

        if downloaded and os.path.exists(target_path):
            file_size_kb = round(os.path.getsize(target_path) / 1024, 1)
            return {
                "success": True,
                "client_id": client_id,
                "client_name": client_name,
                "token": token,
                "filename": target_filename,
                "file_path": target_path,
                "size_kb": file_size_kb,
                "message": f"Instalador {target_filename} ({file_size_kb} KB) baixado com sucesso via Token Milvus!"
            }

        return {
            "success": False,
            "client_id": client_id,
            "client_name": client_name,
            "token": token,
            "error": f"Não foi possível baixar o instalador do Milvus para {client_name}. Detalhes: {last_error}"
        }

