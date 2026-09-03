import os
import re
import datetime
from typing import List, Dict, Any

class ObsidianMemory:
    """
    Sistema de Memória de Longo Prazo do Ultron baseado em arquivos Markdown.
    Atua como um Vault do Obsidian integrado localmente.
    """
    def __init__(self, vault_path: str = "obsidian_vault"):
        self.vault_path = vault_path
        self._ensure_vault_exists()

    def _ensure_vault_exists(self):
        if not os.path.exists(self.vault_path):
            try:
                os.makedirs(self.vault_path, exist_ok=True)
            except Exception as e:
                import logging
                logging.getLogger("obsidian").error(f"Erro ao criar cofre do Obsidian: {e}")

    def _sanitize_title(self, title: str) -> str:
        """Remove caracteres inválidos para nomes de arquivos."""
        sanitized = re.sub(r'[\\/*?:"<>|]', "", title)
        return sanitized.strip() or "Nota_Sem_Titulo"

    def save_note(self, title: str, content: str, tags: List[str] = None) -> bool:
        """
        Salva ou anexa conteúdo a uma nota no Obsidian.
        """
        self._ensure_vault_exists()
        safe_title = self._sanitize_title(title)
        file_path = os.path.join(self.vault_path, f"{safe_title}.md")
        
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        tags_str = ""
        if tags:
            tags_str = " ".join([f"#{t.replace(' ', '_')}" for t in tags]) + "\n\n"

        try:
            mode = "a" if os.path.exists(file_path) else "w"
            with open(file_path, mode, encoding="utf-8") as f:
                if mode == "w":
                    f.write(f"# {title}\n{tags_str}")
                
                f.write(f"\n## Anotação de {now}\n")
                f.write(f"{content}\n")
            return True
        except Exception as e:
            import logging
            logging.getLogger("obsidian").error(f"Erro ao salvar nota {title}: {e}")
            return False

    def search_notes(self, query: str, limit: int = 3) -> str:
        """
        Pesquisa no cofre do Obsidian por arquivos que contenham palavras-chave da query.
        Retorna um compilado do conteúdo encontrado.
        """
        if not os.path.exists(self.vault_path):
            return ""

        query_words = set(re.findall(r'\w{4,}', query.lower()))
        if not query_words:
            return ""

        results = []
        try:
            for filename in os.listdir(self.vault_path):
                if not filename.endswith(".md"):
                    continue
                    
                file_path = os.path.join(self.vault_path, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                score = sum(1 for word in query_words if word in content.lower() or word in filename.lower())
                if score > 0:
                    results.append({"filename": filename, "score": score, "content": content})
                    
            # Ordena por pontuação (mais hits de palavras-chave primeiro)
            results.sort(key=lambda x: x["score"], reverse=True)
            
            top_results = results[:limit]
            if not top_results:
                return ""
                
            compiled = "MEMÓRIA DE LONGO PRAZO ENCONTRADA (OBSIDIAN):\n\n"
            for res in top_results:
                compiled += f"--- Arquivo: {res['filename']} ---\n{res['content']}\n\n"
                
            return compiled.strip()
        except Exception as e:
            import logging
            logging.getLogger("obsidian").error(f"Erro ao pesquisar notas: {e}")
            return ""
