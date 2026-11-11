# Ultron — Automação de Bancada da Pense Rede

O Ultron é um serviço FastAPI e bot do TrueConf para suporte técnico e
automação de bancada. **Não possui dashboard web** nesta versão. A interface
do técnico é o TrueConf; a API fornece tarefas, agentes, diagnósticos e laudos.

## Estado deste branch

Branch de homologação. **Não fazer merge, deploy nem reiniciar serviços do
Jarvis sem autorização e plano de migração.** A versão corrente em produção
pode utilizar HTTP, enquanto este branch possui autenticação HTTPS e
mudanças no protocolo dos agentes. Os binários atuais não são
automaticamente compatíveis.

O **FOG Project foi escolhido** para o futuro motor de captura e recuperação
de imagem via PXE. **Não existe integração FOG neste código**; nenhum DHCP,
WDS, PXE ou armazenamento foi alterado.

## Arquitetura

- Ultron/TrueConf: Jarvis, 192.168.57.43. Apenas controle e orquestração.
- WDS/MDT: Windows Server, 192.168.57.87. Instalação Windows atual.
- Storage: 192.168.57.112, compartilhamento \`backups3\`.
- FOG: implantação futura em Linux isolado, em VM ou host dedicado,
  sem DHCP/ProxyDHCP ativo durante a homologação.
- Windows de testes: 192.168.57.77, não será usado como produção.

## Funções preservadas

- TrueConf e processamento de solicitações;
- diagnóstico (WinRM, modo leitura), automação Windows e agentes;
- geração de laudos técnicos PDF (com logo local);
- backup de pastas selecionadas por Robocopy, rotulado explicitamente como
  **backup de arquivos, não imagem completa**;
- verificação de imagens Macrium existentes, em estação autorizada;
- APIs de agentes e operações administrativas, mediante autenticação.

O **MDT continua bloqueado para formatação automatizada**, porque ainda
não existe uma prova confiável de captura e validação de imagem vinculada
ao equipamento.

## Entendimento da IA v2

A entrada do TrueConf possui:
1. filtro de perguntas, negações e pedidos conflitantes;
2. classificador LLM de saída JSON tipada (intenção, alvo, confiança, campos
   faltantes);
3. política determinística: modelo não executa PowerShell nem gera comandos;
4. memória SQLite restrita a usuário/último equipamento e status de tarefa;
5. catálogo de ações: apenas consultas/diagnósticos explicitamente permitidos
   podem ser executados na modalidade semântica;
6. rastreabilidade e testes de frases reais de bancada.

### Comandos de homologação

- \`/entender <texto>\`: mostra o entendimento do modelo sem executar ações.
- \`/contexto\`: mostra apenas o contexto operacional do próprio técnico.
- \`/backup <IP> <CLIENTE> <CHAMADO>\`: cópia de arquivos, com flag de habilitação.
- \`/status_backup files_<id>\`: consulta a tarefa de backup de arquivos.
- \`/verificar_backup <caminho.mrimg>\`: verificação Macrium, se autorizada.

Roteador semântico: **desativado por padrão**. Para uma homologação controlada,
a configuração do processo (não do host todo) precisa incluir:

    ULTRON_SEMANTIC_ROUTER_ENABLED=1
    ULTRON_SEMANTIC_ALLOWED_TRUECONF_USERS=<tecnicos_validos>
    ULTRON_SEMANTIC_READONLY_ENABLED=1
    ULTRON_SEMANTIC_ALLOWED_SUBNET=<CIDR_de_PCs_de_teste>
    ULTRON_OPERATIONAL_DB=data/operational_context.sqlite3

A opção READONLY habilita apenas diagnóstico em IP explicitamente informado
e listagem de bancada. Reinicialização, instalação, formatação, backup de
imagem e restauração não são liberados pela IA. Confiança retornada pelo
modelo não é autorização nem probabilidade calibrada.

### Segurança da API

A API administrativa utiliza HTTPS e \`ULTRON_ADMIN_API_TOKEN\` (32+ caracteres)
para endpoints internos e de modificação. O webhook HTTP do TrueConf exige
HTTPS e \`ULTRON_TRUECONF_WEBHOOK_SECRET\` de 32+ caracteres enviado no header
\`X-Ultron-TrueConf-Secret\`; sem isso, o webhook fica indisponível.

O bot TrueConf conectado por seu próprio transporte autenticado é uma
integração separada. Nunca confiar em um \`user_id\` enviado por terceiros
como autorização de uma operação.

Credenciais devem ficar fora do Git. Validar autenticação do WinRM e migração
de agentes antes de ativar a API em produção. Rejeitar comandos não é falha:
é o comportamento seguro quando permissões ou dados estão incompletos.

## Desenvolvimento e testes

    python -m venv venv
    pip install -r requirements.txt

Testes de segurança são executados pela GitHub Actions no Linux e Windows,
sem rede nem execução de tarefas em equipamentos reais. Para executar a
mesma suíte em ambiente de desenvolvimento:

    python -m unittest discover -s tests -p 'test_operational_memory.py' -v
    python -m unittest discover -s tests -p 'test_semantic_dispatch.py' -v
    python -m unittest discover -s tests -p 'test_headless_api.py' -v

O endpoint \`GET /\` retorna apenas o status do serviço. Rotas de downloads
de agente, webhook, relatórios e automação continuam existentes.

## Documentos de projeto

- \`docs/ULTRON_INTELLIGENCE_V2.md\`: IA, critérios de teste e segurança.
- \`docs/TRUECONF_PREFORMAT_BACKUP.md\`: backup de arquivos e suas limitações.
- \`docs/ULTRON_MACRIUM_INTEGRATION.md\`: verificação Macrium existente.
- Plano FOG: ainda a preparar, sem instalação ou integração operacional.

## Agente Windows e WinRM

WinRM e nativo do Windows; UltronAgent e separado. Consulte [revisao e migracao](docs/WINDOWS_AGENT_REVIEW.md). Distribuicao suspensa por padrao ate homologacao do pacote revisado.

## Consolidacao do projeto

Consulte [correcoes gerais e proximas prioridades](docs/PROJECT_CONSOLIDATION.md). TrueConf agora exige usuarios explicitamente autorizados, identidade do SDK e TLS validado; configure o ambiente antes de homologar. Corpus de entendimento: 45 frases, com novos casos sinteticos de negacoes e exemplos.

## Acompanhamento de tarefas

Diagnosticos, instalacoes de softwares e backups de arquivos passam a ter historico persistente: /tarefas, /tarefa <ID> e /status_backup <ID>. Veja [estados, migracao e limites](docs/UNIFIED_TASKS.md). Reinicio deixa tarefas inacabadas como UNKNOWN e nunca as reexecuta automaticamente.
