# Ultron — revisão de escopo, IA e remoção do dashboard

**Status:** código preparado na branch de homologação. Nenhuma mudança nos
servidores Jarvis, WDS/MDT, DHCP, storage ou nas máquinas da bancada.

## Itens removidos (sem comprometer o TrueConf)

- templates/index.html — painel HTML;
- static/js/app.js — lógica do dashboard;
- static/css/style.css — estilos do painel;
- static/favicon.ico — ícone exclusivo da interface;
- GET /dashboard e montagem pública de /static;
- WebSocket /ws/pipeline/{session_id} e streaming usado apenas pelo painel;
- 11 rotas auxiliares HTTP de telemetria, consulta e ferramentas dedicadas ao
  frontend (as funções internas de consulta do TrueConf foram mantidas);
- testes/test_api.py antigo, que partia do pressuposto da existência do
  dashboard e incluía chamadas de operação potencialmente reais;
- aproximadamente 12 mil caracteres de prompt conversacional redundante.

**Mantidos:** logo PNG/JPG para laudos/TrueConf, download de agentes,
FastAPI, verdadeiro bot TrueConf, relatórios PDF, agente Windows,
diagnósticos de leitura, automação de programas, backup de arquivos
Robocopy com resultado verificável e verificação Macrium existente.

O servidor é HEADLESS: o TrueConf é a interface operacional e o GET /
apresenta apenas status mínimo JSON.

## IA v2 — o que foi implementado

- core/intent_preflight.py: diferencia consulta, negação, tarefas compostas,
  backup de arquivos e captura de imagem. Não permite que pedidos FOG
  indisponíveis virem um Robocopy.
- core/structured_intent.py: modelo sugere intenção por JSON validado.
  A política de execução é separada e rejeita alvos não explícitos,
  operações arriscadas ou não implementadas.
- /entender <pedido>: prévia de como o modelo compreendeu a solicitação,
  sem executar.
- ULTRON_SEMANTIC_ROUTER_ENABLED=1: substituição **opt-in** do roteador
  legado para usuários permitidos. Com outros controles específicos,
  autoriza **apenas** diagnóstico de leitura de uma máquina explicitamente
  informada na sub-rede permitida e listagem da bancada. Não ativa FOG,
  formatação, reboot, desligamento ou instalação.
- core/operational_memory.py: guarda contexto do último alvo e estado
  resumido de tarefas em SQLite, por técnico, por até 7 dias. Não salva
  transcrições, senhas, tokens, logs de diagnóstico ou dados do cliente.
  Ao reiniciar, tarefas inacabadas passam a UNKNOWN, sem replay automático.
- /contexto: mostra somente memória operacional do próprio técnico.
- Logs de classificação não incluem texto cru da mensagem.
- Contexto de rede e Obsidian no prompt são opt-in (desligados por padrão).
- A conversa da IA não afirma executar ações sem evidência; o prompt de
  diagnóstico também deixou de alegar auto-reparo indiscriminado.

## Segurança: modificações que exigem plano de migração

- Endpoints administrativos e dados sensíveis passam a exigir
  require_operator, HTTPS e token próprio. Scripts de terceiros que
  usavam as antigas rotas sem autenticação precisam ser atualizados.
- O webhook HTTP TrueConf é desativado sem secret de 32+ caracteres e
  transporte HTTPS. A biblioteca de bot WebSocket do TrueConf é outro
  transporte e não deve ser confundida com o webhook.
- A API de relatórios valida o nome de arquivo e exige operador.
- O backend atual possui componentes legados com credenciais e WinRM que
  precisam de rotação, inventário e revisão de autenticação.
- A branch contém também alterações anteriores de TLS do UltronAgent.
  Deploy direto do PR pode desconectar agentes atuais — **proibido
  sem homologação e rollback**.

## Validação atual

GitHub Actions executa testes offline no Linux e Windows, incluindo
autorização de endpoint, precedência de classificação, negação de ações
perigosas, isolamento da memória, schema do plano do LLM e um corpus de
25 mensagens exemplificativas, todas desidentificadas.

A suíte antiga de teste de API ao vivo foi removida por pressupor o
dashboard e invocar operações em equipamentos. Precisamos construir testes
de integração seguros com FastAPI TestClient e dependências injetadas
antes de qualquer deploy. Testes offline não garantem compatibilidade
com produção ou desempenho do LLM.

## Dívidas ainda existentes

1. chatops/chatops.py continua um arquivo legado grande. A remoção direta
   das rotas não testadas poderia comprometer comandos em uso; decomposição
   em módulos por serviço deve ocorrer depois de inventário e testes.
2. A classificação por palavras-chave continua como fallback com
   ULTRON_SEMANTIC_ROUTER_ENABLED=0. Migrar gradualmente apenas após
   avaliar solicitações reais, taxa de falso positivo e latência.
3. A ação de cancelar tarefas legada pode encerrar processos globais;
   precisa de controle por PID e job antes de ser considerada segura.
4. Verificar credenciais e transporte da integração WinRM/TrueConf e
   certificados usados pelos serviços.
5. Backup de arquivos não equivale a imagem de disco. A integração FOG
   foi explicitamente adiada até existir infraestrutura e homologação.
6. Jobs de backup legados ainda são em memória; histórico em SQLite é
   apenas auditoria, não substitui um scheduler persistente confiável.
7. Configurar gerenciamento de segredos fora de arquivos no repositório.
8. Definir como o Linux do FOG será hospedado em host distinto do Jarvis.

## Próxima liberação

Não fazer merge/deploy por conta própria. Reunir plano TLS/agent, inventário
de consumidores das rotas HTTP removidas, backup do diretório da aplicação,
rollback, testes FastAPI em ambiente de homologação e autorização explícita
para reiniciar **somente ultron.service**. Nunca reiniciar Ubuntu ou serviços
não relacionados.
