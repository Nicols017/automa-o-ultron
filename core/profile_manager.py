import os
import glob
import yaml
import re
from typing import Dict, Any, List, Optional
from .milvus_sync import MilvusSyncService

class ProfileManager:
    def __init__(self, base_dir: Optional[str] = None):
        if not base_dir:
            self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            self.base_dir = base_dir

        self.config_dir = os.path.join(self.base_dir, "config")
        self.profiles_dir = os.path.join(self.config_dir, "profiles")
        self.settings_file = os.path.join(self.config_dir, "settings.yaml")
        self.clients_file = os.path.join(self.config_dir, "clients.yaml")

        settings = self.get_settings()
        milvus_url = settings.get("network", {}).get("milvus_dashboard_url", "http://192.168.57.7")
        milvus_token = settings.get("network", {}).get("milvus_api_token", "")
        demo_mode = settings.get("network", {}).get("milvus_demo_mode", False)
        self.milvus = MilvusSyncService(base_url=milvus_url, api_token=milvus_token, demo_mode=demo_mode)

    def get_settings(self) -> Dict[str, Any]:
        """Retorna as configurações globais do servidor Ultron"""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"⚠️ Erro ao ler {self.settings_file}: {e}")
        return {}

    def get_milvus_config(self) -> Dict[str, Any]:
        """Retorna as configurações atuais da Dashboard Milvus"""
        settings = self.get_settings()
        net = settings.get("network", {})
        url = net.get("milvus_dashboard_url", "http://192.168.57.7")
        token = net.get("milvus_api_token", "")
        demo_mode = net.get("milvus_demo_mode", False)
        return {
            "dashboard_url": url,
            "api_token": token,
            "has_token": bool(token),
            "masked_token": (token[:4] + "••••" + token[-4:]) if len(token) > 8 else ("••••" if token else ""),
            "demo_mode": demo_mode,
            "cache_ttl": self.milvus.cache_ttl
        }

    def save_milvus_config(self, milvus_url: str, milvus_token: str, demo_mode: bool = False) -> bool:
        """Atualiza e persiste as configurações da Dashboard Milvus em settings.yaml"""
        settings = self.get_settings()
        if "network" not in settings:
            settings["network"] = {}

        settings["network"]["milvus_dashboard_url"] = milvus_url.strip()
        settings["network"]["milvus_api_token"] = milvus_token.strip()
        settings["network"]["milvus_demo_mode"] = bool(demo_mode)

        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                yaml.dump(settings, f, allow_unicode=True, default_flow_style=False)
            self.milvus.update_config(base_url=milvus_url, api_token=milvus_token, demo_mode=demo_mode)
            return True
        except Exception as e:
            print(f"❌ Erro ao salvar settings.yaml: {e}")
            return False

    def get_client_tokens(self) -> List[Dict[str, Any]]:
        """Retorna a lista de todos os clientes e seus tokens de agente Milvus mapeados"""
        clients_raw = self.get_all_clients_raw()
        res = []
        for cid, info in clients_raw.items():
            tok = info.get("milvus_token", "")
            res.append({
                "client_id": cid,
                "nome": info.get("nome", cid.replace("_", " ").title()),
                "dominio": info.get("dominio", ""),
                "milvus_token": tok,
                "has_token": bool(tok and "TOKEN_MILVUS" not in tok)
            })
        return res

    def get_all_clients_raw(self) -> Dict[str, Any]:
        """Retorna o dicionário bruto de clientes do arquivo clients.yaml"""
        if os.path.exists(self.clients_file):
            try:
                with open(self.clients_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    return data.get("clientes", {})
            except Exception as e:
                print(f"⚠️ Erro ao ler {self.clients_file}: {e}")
        return {}

    def update_client_token(self, client_id: str, new_token: str) -> bool:
        """Atualiza o token de instalação do agente Milvus para um cliente específico em clients.yaml"""
        if not os.path.exists(self.clients_file):
            return False
        try:
            with open(self.clients_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            
            if "clientes" not in data:
                data["clientes"] = {}

            if client_id in data["clientes"]:
                data["clientes"][client_id]["milvus_token"] = new_token.strip()
            else:
                data["clientes"][client_id] = {
                    "nome": client_id.replace("_", " ").title(),
                    "milvus_token": new_token.strip(),
                    "dominio": ""
                }

            with open(self.clients_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            return True
        except Exception as e:
            print(f"❌ Erro ao atualizar token de cliente em clients.yaml: {e}")
            return False

    def list_profiles(self) -> List[str]:
        """Retorna a lista de nomes de perfis encontrados em config/profiles/"""
        if not os.path.exists(self.profiles_dir):
            return []
        files = glob.glob(os.path.join(self.profiles_dir, "*.yaml")) + glob.glob(os.path.join(self.profiles_dir, "*.yml"))
        return [os.path.splitext(os.path.basename(f))[0] for f in files]

    def list_clients(self, force_refresh_milvus: bool = False) -> List[Dict[str, Any]]:
        """
        Retorna lista estruturada de todos os clientes registrados localmente
        combinados com todas as empresas sincronizadas dinamicamente da Dashboard Milvus (192.168.57.7).
        """
        clients_raw = self.get_all_clients_raw()
        available_profiles = self.list_profiles()
        client_list = []
        known_names = set()

        # 1. Clientes configurados localmente em clients.yaml
        for cid, info in clients_raw.items():
            has_profile = cid in available_profiles
            name = info.get("nome", cid.replace("_", " ").title())
            known_names.add(name.strip().lower())
            known_names.add(cid.lower())
            client_list.append({
                "id": cid,
                "nome": name,
                "dominio": info.get("dominio", ""),
                "milvus_token": info.get("milvus_token", ""),
                "has_dedicated_profile": has_profile,
                "source": "local"
            })

        # 2. Perfis avulsos em config/profiles/
        for p in available_profiles:
            if p not in clients_raw:
                p_name = p.replace("_", " ").title()
                known_names.add(p_name.strip().lower())
                known_names.add(p.lower())
                client_list.append({
                    "id": p,
                    "nome": p_name,
                    "dominio": "",
                    "milvus_token": "",
                    "has_dedicated_profile": True,
                    "source": "local"
                })

        # 3. Empresas sincronizadas dinamicamente da Dashboard Milvus (/api/contatos)
        milvus_companies = self.milvus.get_companies(force_refresh=force_refresh_milvus)
        for comp in milvus_companies:
            comp_clean = comp.strip()
            norm_name = comp_clean.lower()
            slug_id = "milvus_" + re.sub(r'[^a-zA-Z0-9_]+', '_', norm_name).strip('_')

            # Verifica se já existe cliente configurado com nome similar
            already_exists = False
            for kn in known_names:
                if kn in norm_name or norm_name in kn:
                    already_exists = True
                    break

            if not already_exists:
                client_list.append({
                    "id": slug_id,
                    "nome": comp_clean,
                    "dominio": "",
                    "milvus_token": "",
                    "has_dedicated_profile": False,
                    "source": "milvus"
                })
                known_names.add(norm_name)

        return client_list

    def get_client_profile(self, client_id: str) -> Dict[str, Any]:
        """
        Retorna o perfil completo e resolvido de um cliente.
        Se houver arquivo específico em config/profiles/{client_id}.yaml, ele é mesclado.
        Caso contrário, usa o perfil base (cliente_padrao.yaml) com dados do clients.yaml ou Milvus.
        """
        clients_raw = self.get_all_clients_raw()
        client_meta = clients_raw.get(client_id, {})

        # 1. Carrega o perfil padrão de fallback
        default_profile_path = os.path.join(self.profiles_dir, "cliente_padrao.yaml")
        profile = {}
        if os.path.exists(default_profile_path):
            try:
                with open(default_profile_path, "r", encoding="utf-8") as f:
                    profile = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"⚠️ Erro ao ler cliente_padrao.yaml: {e}")

        # 2. Carrega perfil específico se existir
        specific_path = os.path.join(self.profiles_dir, f"{client_id}.yaml")
        if not os.path.exists(specific_path):
            specific_path = os.path.join(self.profiles_dir, f"{client_id}.yml")

        if os.path.exists(specific_path):
            try:
                with open(specific_path, "r", encoding="utf-8") as f:
                    specific_data = yaml.safe_load(f) or {}
                    profile.update(specific_data)
            except Exception as e:
                print(f"⚠️ Erro ao ler perfil específico {specific_path}: {e}")

        # 3. Garante campos principais
        profile["cliente_id"] = client_id
        if "nome_exibicao" not in profile or not profile["nome_exibicao"]:
            if client_meta.get("nome"):
                profile["nome_exibicao"] = client_meta.get("nome")
            elif client_id.startswith("milvus_"):
                profile["nome_exibicao"] = client_id.replace("milvus_", "").replace("_", " ").title()
            else:
                profile["nome_exibicao"] = client_id.replace("_", " ").title()

        if "milvus_token" not in profile or not profile["milvus_token"]:
            profile["milvus_token"] = client_meta.get("milvus_token", "")

        # Se domínio veio do clients.yaml e não do profile
        if client_meta.get("dominio") and ("dominio" not in profile or not isinstance(profile["dominio"], dict)):
            profile["dominio"] = {
                "inserir": True,
                "nome": client_meta.get("dominio"),
                "ou_path": "",
                "credencial_key": ""
            }

        return profile
