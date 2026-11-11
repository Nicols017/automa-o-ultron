# Esclarecimento de alvo — diagnostico somente leitura

Branch de desenvolvimento; sem deploy. Mantem TrueConf como interface,
sem dashboard, FOG ou mudancas em infraestrutura real.

## Conversa suportada
1. Tecnico autorizado pede diagnostico, sem IP.
2. Modelo propoe diagnostico tipado com confianca minima exigida e apenas
   alvo faltante. Politica deve permitir diagnostico readonly.
3. Ultron pede IP completo ou identificador cadastrado.
4. IP completo retoma o pedido original e passa novamente pela politica.
   Nao e enviado sozinho ao modelo para tentar adivinhar sua intencao.
5. Hostname/serial/MAC exige correspondencia exata e unica no inventario.
   Ultron mostra candidato e pede que o tecnico confira e digite o IP completo.
6. Confirma o vinculo de serial, hostname, MAC e IP novamente antes da entrega.
   Se o inventario mudou, o pedido e descartado sem executar.
7. Diagnostico segue o handler existente, com registro persistente de tarefa/ID.

Exemplo: "diagnostica o computador" -> pergunta de alvo -> "PC-A" ->
confira o candidato e digite o IP -> diagnostico, se toda politica permitir.

## Limites e protecoes
- Apenas diagnostico. Nao habilita instalacao, preparacao, backup, reboot,
  energia, dominio, formatacao, FOG ou execucao generica por linguagem natural.
- Roteador semantico e readonly continuam opt-in com allowlists/sub-rede.
  Revalidados quando a resposta chega, junto com permissao geral do tecnico.
- IP isolado sem pedido pendente registra somente contexto e pede a acao,
  sem nova classificacao executavel do modelo. Resposta vencida nao revive pedido.
- IP da memoria anterior nao e autorizado automaticamente. IPs de infraestrutura
  existentes na politica continuam bloqueados; IP abreviado nao e expandido.
- Cada tecnico tem seu pedido, TTL de 5 minutos e consumo atomico de uma resposta.
  Alterar candidato gera novo identificador interno; respostas concorrentes
  antigas nao podem concluir o pedido novo.
- /cancelar, cancelar ou cancela descartam esclarecimento, sem cancelar processo.
  Menu, numero de opcao, novo comando slash ou nova frase descartam o pedido
  anterior e seguem roteamento normal. Menus numericos nao vao para o LLM.
- Reinicio limpa esclarecimentos pendentes antes de ligar o bot. Nada e retomado
  automaticamente. SQLite guarda apenas dados tipados, sem texto original,
  prompt, comandos, senhas ou tokens.
- Falha do banco ou inventario nao libera execucao por outro caminho.

## Inventario offline opcional
ULTRON_DEVICE_INVENTORY_FILE aponta para JSON provisionado pelo operador.
Ainda nao e um inventario automatico nem aprende equipamentos por conversa.

Formato: lista de objetos contendo exatamente serial, hostname, mac, ip, seen_at.
seen_at e timestamp Unix da ultima validacao real do registro, nao um campo
para renovar cegamente. Todos os registros precisam ser validos e recentes
(ate 15 minutos); arquivo com registro vencido ou futuro e recusado nesta fase.
Limites: 1000 registros e arquivo de ate 1 MiB. Correspondencia exata, sem fuzzy
matching. Duplicatas de serial, hostname, MAC ou IP impedem selecionar candidato.
Arquivo com escrita de grupo/outros no Linux e recusado.

config/device_inventory.example.json usa endereco de documentacao e timestamp
zero: **e intencionalmente invalido para uso operacional**. Nao e cadastro real.
Definir ACL apropriada no Windows, controlar escrita e atualizar por fonte
confiavel. Nenhum arquivo de inventario real foi criado neste trabalho. Nao versionar
inventario operacional; config/device_inventory.json esta no .gitignore.

Uma correspondencia, mesmo recente, NAO prova quem esta respondendo naquele IP
nem resolve sozinha DHCP/reuso de IP. Confirmacao do tecnico e TLS do transporte
continuam necessarios. Deteccao de identidade no proprio destino e futura.

## Testes e pendencias
25 testes offline usam inventario/bancos temporarios, relogio controlado,
modelo falso e handler falso. Cobrem conversa em duas mensagens sem repetir
classificacao, expiracao, isolamento, revogacao de permissoes, conflitos,
troca de identidade, concorrencia e pedidos de alteracao bloqueados.
Nenhum contato com TrueConf, LLM real, agente ou rede interna.

Pendentes: coleta confiavel de inventario pelos agentes, tratamento de dominios/
seriais genericos, avaliacao de frases reais e dialogos de outros tipos de
operacao com permissoes e campos proprios. Nao se afirma entendimento universal.
