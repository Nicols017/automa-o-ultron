# Registro unificado de tarefas — primeira etapa

Desenvolvimento somente na branch/PR draft. Sem merge, deploy ou acesso a
maquinas/servicos reais. TrueConf permanece interface; sem dashboard e sem FOG.

## Fluxos integrados
- Diagnostico pelo TrueConf e pela API administrativa.
- Instalacao de softwares por /softwares e rotas que chamam esse handler.
- Backup de arquivos pelo TrueConf e pela API administrativa.
- IDs files_* existentes nas novas copias sao preservados.
- /tarefas lista as ultimas 10 tarefas do proprio tecnico.
- /tarefa <ID> e /status_tarefa <ID> consultam uma tarefa do proprio tecnico.
- /status_backup <ID> mantem a permissao de backup e usa historico persistente.
- /contexto inclui a ultima tarefa do novo registro, com fallback ao antigo.
- GET /api/v1/tasks e GET /api/v1/tasks/{ID} exigem operador HTTPS/autenticado.
  A API compartilha o proprietario api_operator: o token administrativo atual
  nao identifica operadores individuais. Nao lista tarefas dos tecnicos.

## Estados e evidencias
core/task_registry.py usa data/tasks.sqlite3 (ULTRON_JOB_DB).
Guarda ID, proprietario, IP, acao, estado, evidencia e horarios.
Nao guarda comandos, argumentos brutos, senhas, tokens, stdout ou laudos.
Para software, task_packages guarda resumo tipado por programa solicitado;
consulte SOFTWARE_VERIFICATION.md.

QUEUED: registrado antes da thread.
RUNNING: entrega ao executor reservada atomicamente, uma unica vez por ID.
SUCCESS: executor informou sucesso ou relatorio passou no validador.
PARTIAL: somente parte da instalacao foi confirmada.
ERROR: falha explicita ou tarefa nao iniciada.
UNKNOWN: transporte/resultado sem confirmacao ou encerramento antes de concluir.

EXECUTOR_REPORTED_SUCCESS nao e verificacao independente.
SOFTWARE_PRESENCE_VERIFIED identifica presenca/versao no inventario, nao saude/licenca.
BACKUP_REPORT_VALIDATED e apenas relatorio Robocopy validado, nao imagem completa.
NOT_STARTED identifica worker que nao iniciou entrega.
Nenhum estado libera formatacao, restauracao ou prova de imagem Macrium/FOG.

Nao mostramos porcentagem inventada: acompanhamento por estado.
Cancelamento legado interrompe notificacoes locais, sem prometer parada remota.
O resultado ainda e registrado para consulta.

## Concorrencia e reinicio
Indice SQLite permite uma tarefa QUEUED/RUNNING por IP entre os tres fluxos.
IPs diferentes podem executar simultaneamente. Isso ainda nao coordena todos
os comandos antigos, a fila do agente ou processos externos.

Lock local do sistema operacional impede dois servidores executores no mesmo
banco. Startup adquire exclusividade antes de recuperar tarefas. Leitores nao
reclassificam tarefas ativas. Lock permanece ate o processo sair: pode haver
workers no shutdown. Nao remover lock nem executar multiplos workers/replicas.
Esta arquitetura suporta um executor por banco em disco local.

Startup converte tarefas antigas QUEUED/RUNNING para UNKNOWN. Nao recria threads,
reenfileira comandos ou infere conclusao pelo silencio.
UNKNOWN nao impede NOVA solicitacao explicita: verificar o equipamento antes
de repetir continua obrigatorio. Reserva do IP protege estados ativos conhecidos.

## Compatibilidade e migracao
- Banco separado; schemas da memoria operacional e fila do agente preservados.
- Historico antigo em memoria nao e recuperavel retroativamente. Fallback de
  /contexto nao promove registros antigos a prova de sucesso.
- Backup no processo atual devolve dados completos; apos reinicio recupera
  metadados, sem destino/contagem/erro completo. Confira evidencia no storage.
- Preservar data/ em backup consistente. Nao usar NFS/SMB para este banco.
  Definir ACL Windows e permissoes privadas Linux antes de homologar.
- Ainda nao ha expurgo automatico; retencao/arquivo precisam de politica.
- Falha de gravacao antes da entrega impede executar. Falha depois da execucao
  pode deixar UNKNOWN; nenhuma repeticao automatica e feita.
- Registro nao concede autorizacao. Permissoes existentes precedem os handlers.

## Validacao e limites
Testes offline: bancos temporarios, executores falsos e threads controladas.
Cobrem isolamento, concorrencia, entrega unica, evidencias, reinicio, lock do
processo, falhas, backup e instalacao com ID em resposta/notificacao.
Nenhum equipamento ou servico de producao e contactado.

Ainda faltam: esteira completa, ativacao, dominio, energia, verificacao Macrium,
agendamento de mensagens e reconciliacao da fila do agente. Esses comandos
nao foram removidos nem anunciados como migrados.
Proximas etapas: inventario por serial/hostname, esclarecimento pela IA,
cancelamento por PID/job comprovado, limites globais e testes HTTP completos.
