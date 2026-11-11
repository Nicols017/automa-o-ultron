# Consolidacao do Ultron — desenvolvimento, sem deploy

Mantem as decisoes da conversa Entender projeto Ultron: TrueConf como interface,
sem dashboard, IA para entender e propor plano tipado, politica separada,
executor deterministico e resposta baseada em resultado. FOG continua adiado:
nenhuma integracao/alteracao em Jarvis, WDS, DHCP, FOG ou maquinas reais.

## Problemas concretos corrigidos nesta rodada

- 26 chamadas de metodos passavam trace_id a funcoes sem esse parametro.
  Menus e comandos poderiam falhar com TypeError antes de executar.
  Chamadas ajustadas sem remover comandos; teste usa assinaturas reais e
  corpos simulados para percorrer opcoes numericas e rotas slash.
- Transporte REST TrueConf centralizado em core/trueconf_transport.py:
  HTTPS obrigatorio, TLS validado, sem redirects com credenciais.
  WebSocket usa verify_ssl=True; nao existe modo de ignorar TLS.
- Autor ausente no evento nao e mais substituido pelo tecnico padrao.
  ID completo do SDK e preservado, inclusive realm. Permissao master exige
  identidade exata configurada; apelidos fixos como admin nao concedem acesso.
- Entrada de ChatOps verifica usuarios autorizados antes de sessoes/wizards
  ou handlers. Lista vazia nega operacoes; master configurado tambem e operador.
  O webhook HTTP continua exigindo segredo e HTTPS, independente do SDK.
- Credenciais TrueConf retiradas do YAML versionado. Ambiente/.env local
  pode provisionar URL, usuario, senha e token; vazio desabilita a credencial.
  Valores do historico Git continuam expostos: rotacao depende de acao
  operacional autorizada e nao foi realizada aqui.
- Texto de mensagens recebidas e excecoes de transporte nao entram em logs.
  Sincronizacao automatica do avatar no startup removida; logotipos preservados.
- core/message_inbox.py registra hash de servidor+autor+ID do evento em SQLite
  antes do handler. Evento repetido, inclusive apos restart, nao e reexecutado.
  Nao armazena texto, token, autor ou ID de evento em claro. Evento sem ID e
  ignorado; compatibilidade com IDs do SDK precisa de homologacao.
- Mensagens nao lidas anteriores ao restart nao sao solicitadas automaticamente.
  Falha/timeout ao responder via WebSocket nao causa novo envio por REST, pois
  a primeira entrega pode ter ocorrido. REST permanece para ausencia de conexao.
- Cancelamento legado nao encerra todos os processos powershell/winget.
  Interrompe acompanhamento local e informa que a operacao remota pode continuar.
  Cancelamento remoto real exige job/PID comprovadamente vinculado a tarefa.
- Preflight protege negacoes de instalar/preparar/ativar/remover/renomear/rodar
  e distingue textos reportados em log/chamado/exemplo de ordens de execucao.
  Corpus agora tem 45 casos: os 20 novos sao sinteticos, nao mensagens reais
  nem treinamento do modelo. Politica continua separada do LLM.
- Template Docker persiste data/ (fila do agente, memoria e inbox) e remove
  volume do dashboard inexistente. .dockerignore evita embutir .env, bancos,
  logs, binarios antigos e entradas privadas do verificador. Docker nao foi
  construido nem iniciado; e um template de homologacao.

## Migracao obrigatoria antes de habilitar
1. Provisionar ULTRON_TRUECONF_URL (origem HTTPS), BOT_USERNAME,
   BOT_PASSWORD/API_TOKEN com prefixo ULTRON_TRUECONF_. Nao reutilizar valores
   expostos no repositorio. Arquivo .env nao deve entrar no Git nem na imagem.
2. ULTRON_TRUECONF_ALLOWED_USERS e ULTRON_MASTER_TRUECONF_USERS recebem IDs
   exatos do SDK, separados por virgula, com realm quando presente. Usuario
   autorizado no roteador semantico tambem precisa estar autorizado aqui.
   IDs sem realm nao autorizam automaticamente IDs com realm e vice-versa.
3. REST pode usar ULTRON_TRUECONF_CA_BUNDLE apontando para CA confiavel.
   WebSocket usa validacao do SDK/sistema; homologar sua cadeia separadamente.
   Nao ha garantia de que CA customizada do REST configure o SDK.
4. Persistir data/, proteger banco contra leitura/escrita indevida e fazer backup
   consistente. ULTRON_INBOX_DB permite escolher caminho. Nao apagar o inbox
   para resolver falhas: isso remove a protecao contra repetir eventos antigos.
5. Se o processo cair depois de registrar um evento e antes de terminar a acao,
   o resultado precisa de reconciliacao humana: nunca ha replay automatico.
   O inbox nao substitui fila de jobs nem comprova sucesso de operacoes.
   O banco cresce com os eventos; retenção/arquivo exige politica futura que
   preserve a protecao contra replay.
6. Em homologacao isolada, testar identidade e IDs reais do SDK, cadeia TLS,
   reconexao, mensagens pendentes, permissoes e rollback antes de deploy.
   Rollback de codigo deve preservar os bancos; nao restaure bypasses de TLS
   nem credenciais compartilhadas.

## Validacao
tests/test_project_reliability.py testa transporte falso, permissoes, autor
ausente, fluxo do SDK simulado, entrega duplicada concorrente/apos restart,
privacidade do inbox, menu/slash, configuracao e cancelamento sem comando remoto.
Todos os transportes sao falsos; nenhum contato com TrueConf ou equipamento.
CI roda essa suite e as regressoes existentes no Linux e Windows.

## O que ainda falta no projeto
1. **Jobs unificados persistentes:** fila do agente ja e persistente; instalacoes,
   outros jobs de ChatOps e scheduler ainda misturam memoria/threads.
   Modelar estados, proprietario, idempotencia e reconciliacao antes de trocar
   transporte ou habilitar mais acoes automaticas.
2. **Identidade confiavel dos equipamentos:** inventario por serial/MAC/hostname,
   deteccao de serial duplicado e resolucao de cliente/chamado, sem adivinhar IP.
3. **IA homologada:** avaliar modelo real com mensagens revisadas/desidentificadas,
   especialmente ambiguidade e alvo; medir por categoria. O corpus sintetico
   nao comprova desempenho real. Roteador semantico permanece opt-in e restrito.
4. **API integrada:** ampliar testes HTTP com FastAPI TestClient e dependencias
   falsas; testes atuais nao cobrem todas as rotas ponta a ponta.
5. **Desmembrar ChatOps:** extrair catalogo de comandos e servicos por dominio
   preservando contratos testados, em vez de reescrever tudo de uma vez.
6. **Operacao:** lock de dependencias por plataforma, auditoria de dependencias,
   limites de concorrencia, health/readiness de dependencias, logs com trace_id,
   politica de backup/restauracao dos bancos e runbook de deploy.
7. **Privilegios e tarefas tipadas:** reduzir LocalSystem onde possivel e migrar
   execucao generica para catalogo fechado apos inventariar tarefas reais.
8. **FOG:** apenas apos infraestrutura e autorizacao especificas. Nao transformar
   backup de arquivos em suposta imagem validada nem desbloquear formatacao.

Nenhum desses itens pendentes e anunciado como concluido. Esta rodada corrige
falhas demonstraveis e cria limites/testes para continuar sem perder as funcoes.
