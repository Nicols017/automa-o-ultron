# 🤖 Ultron Lab Automation - Pense Rede

Sistema inteligente de orquestração, provisionamento e automação de bancada/remoto, com validação de hardware por IA local (RTX 5060 Ti / Ollama), execução remota via WinRM/PowerShell e emissão automática de laudos técnicos em PDF para clientes corporativos da **Pense Rede**.

---

## 🌐 Ultron Anywhere (Automação Flexível Sem Dependência de Switch)

O Ultron foi projetado para operar tanto na **bancada física do laboratório** quanto em **qualquer lugar da rede / remoto**, sem estar restrito a uma porta de switch específica.

### 📌 1. Execução Universal via One-Liner PowerShell (Qualquer Máquina)
Em qualquer computador com Windows (no Wi-Fi, em outra filial, pós-formatação ou na bancada), basta abrir o PowerShell como Administrador e executar:

```powershell
irm http://192.168.57.43:8000/bootstrap.ps1 | iex
```
*(Substitua pelo IP/DNS do servidor Ultron ou pelo IP do túnel Tailscale/VPN)*.

**O que o Bootstrap faz automaticamente:**
1. Coleta a **Service Tag / Número de Série**, modelo, MAC e IP.
2. Configura e habilita o serviço **WinRM** e regras de Firewall necessárias.
3. Registra a máquina no Ultron Server (`/api/v1/mdt/completed`) e inicia a esteira se configurado.

---

## 🏛️ Topologia e Conectividade da Rede

* **Ultron Server (Host Linux + RTX 5060 Ti):** `http://192.168.57.43:8000` ou `http://localhost:8000`
* **Servidor PXE / MDT & Repositório de Softwares:** `192.168.57.87` (Compartilhamento `\\192.168.57.87\MilvusAgents`)
* **Servidor Storage de Backups Macrium:** `192.168.57.112` (Compartilhamento `\\192.168.57.112\Backups`)
* **Subrede Padrão da Bancada:** `192.168.57.0/24` (Suporta também qualquer subrede arbitrária ou IP individual).

---

## 📁 Estrutura Completa do Projeto

```
automa-o-ultron/
├── config/
│   ├── settings.yaml            # Configurações globais (IPs, TrueConf, WinRM, Ollama, Switch)
│   ├── clients.yaml             # Mapeamento dos 15 clientes (Tokens Milvus, Domínios e OUs)
│   └── profiles/                # Perfis YAML de software/política por cliente
│       ├── cliente_padrao.yaml  # Perfil genérico de bancada
│       ├── extinbras.yaml       # Perfil específico Extinbras
│       └── white_group.yaml     # Perfil específico White Group
├── core/
│   ├── orchestrator.py          # Esteira ponta a ponta (Pipeline mestre)
│   ├── winrm_executor.py        # Execução remota de scripts PowerShell via WinRM
│   ├── network_scanner.py       # Varredura de rede concorrente
│   ├── profile_manager.py       # Leitor e consolidador de perfis de clientes
│   ├── diagnostic_analyzer.py   # Diagnóstico de hardware com LLM local (Ollama)
│   └── switch_identifier.py     # Leitura de portas de switch (opcional)
├── mdt/
│   └── scripts/
│       └── Notify-Ultron.ps1    # Script chamado na etapa final da Task Sequence do MDT
├── reports/
│   ├── report_generator.py      # Gerador de Laudos Técnicos em PDF (ReportLab)
│   └── output/                  # Armazenamento dos PDFs gerados
├── scripts/powershell/          # Scripts executados nas máquinas cliente
│   ├── Bootstrap-Ultron.ps1     # Inicializador universal One-Liner (Ultron Anywhere)
│   ├── Install-LabStandard.ps1  # Instalação padrão (AnyDesk, Office, Milvus, Ativação MAS)
│   ├── Install-MilvusAgent.ps1  # Instalação do agente Milvus com token do cliente
│   ├── Join-CustomerDomain.ps1  # Ingresso automático no Active Directory do cliente
│   ├── Run-LabBurnIn.ps1        # Teste de estresse de CPU/RAM e validação de drivers
│   ├── Inspect-SystemLogs.ps1   # Coleta S.M.A.R.T, BSODs e logs de eventos
│   ├── Configure-TrueConfClient.ps1 # Configuração do cliente TrueConf
│   ├── Map-SPAShares.ps1        # Mapeamento de unidades de rede
│   ├── Install-Flutter.ps1      # Ambiente de desenvolvimento Flutter
│   └── Backup-UserData.ps1      # Backup de dados de perfil de usuário
├── static/                      # Interface Web (CSS e JavaScript)
├── templates/                   # Template HTML do Dashboard
├── trueconf/
│   └── bot.py                   # Bot de notificações TrueConf para técnicos
├── tests/                       # Testes automatizados
│   ├── test_components.py       # Testes unitários dos módulos internos
│   └── test_api.py              # Testes de integração da API FastAPI
├── Dockerfile                   # Build da imagem Linux para produção
├── docker-compose.yml           # Orquestração Docker com network_mode: host
├── requirements.txt             # Dependências Python
├── ultron.service               # Unidade systemd para Linux daemon
└── main.py                      # Servidor FastAPI e Web Dashboard
```

---

## 🛠️ Configuração no Ambiente de Desenvolvimento / IDE

### 1. Criar e Ativar Ambiente Virtual Python:
```bash
python -m venv venv
# No Windows PowerShell:
.\venv\Scripts\Activate.ps1
# No Linux:
source venv/bin/activate
```

### 2. Instalar Dependências:
```bash
pip install -r requirements.txt
```

### 3. Ajustar Configurações no `config/settings.yaml`:
* **`network`**: Ajuste os IPs do servidor Ultron, MDT e Storage de Backups.
* **`winrm`**: Configure o usuário e senha padrão definidos na imagem padrão de bancada (`Administrator`).
* **`llm`**: Configure a URL do Ollama (`http://localhost:11434` ou o IP do servidor com a GPU) e o nome do modelo.
* **`trueconf`**: Insira o token do bot e URL do TrueConf da Pense Rede.
* **`switch`**: Deixe `enabled: false` para operação livre de switch ou `true` se quiser vincular aos cabos do lab.

### 4. Executar o Servidor em Modo de Desenvolvimento:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Acesse o painel em: **`http://localhost:8000`** ou **`http://<SEU_IP>:8000`**.

---

## 🚀 Execução em Produção (Docker / Linux Server)

```bash
docker compose up -d --build
```
> O container roda com `network_mode: host` para comunicação direta com a rede local e Ollama.

---

## 🧪 Executar Testes Automatizados

```bash
# Testes dos componentes internos (ProfileManager, PDF, Scanner, WinRM)
python tests/test_components.py

# Testes da API FastAPI e Dashboard
python tests/test_api.py
```
