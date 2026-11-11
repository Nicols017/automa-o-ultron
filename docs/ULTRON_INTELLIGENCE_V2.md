# Ultron IA v2 — interpretação contextual e segura

**Estado:** estágio de desenvolvimento e testes offline. Nenhum deploy no
Jarvis. Nenhuma reinicialização de Jarvis, WDS, storage ou outros serviços.

## Por que o roteamento atual falha

O TrueConf ChatOps mistura:
- comandos exatos (slash);
- regex e listas extensas de palavras-chave que podem confundir perguntas
  com ordens de execução;
- o IntentRouter com score relativo: quando apenas uma regra fraca casa,
  ela pode aparecer com confiança relativa elevada;
- o LLM de fallback, que recebe um prompt longo e entrega texto livre.
  O texto livre não é uma chamada de ferramenta validada;
- contexto de sessão em memória, sem plano tipado, sem separação clara
  entre interpretação, autorização, execução e verificação de resultado.

Isso explica erros reportados como "não entendi" para pedidos legítimos e
interpretações inesperadas de comandos vagos. Não é possível atribuir
todos os incidentes ao modelo sem revisar os logs de cada um.

## Melhoria 1 — pré-interpretação segura (concluída em branch)

core/intent_preflight.py distingue:
- perguntas / explicações: encaminha para IA sem executar;
- negações explícitas (não reinicie, não formate);
- pedido combinado backup + formatação: requer separação;
- backup de imagem FOG não disponível: não converter em Robocopy;
- verificar backup existente: não converter em nova cópia.

O TrueConf chama esse preflight antes das regras administrativas legadas.
Comandos explícitos prefixados por / mantêm roteamento anterior.

## Melhoria 2 — IA devolve JSON, não comandos (prévia concluída em branch)

core/structured_intent.py pede ao modelo um objeto JSON com:
- intent (tipo de solicitação)
- mode (question/request/unknown)
- target_ip
- confidence
- missing_fields

O resultado passa por validação com lista fechada de intenções, alvo
declarado na frase ou explicitamente confirmado pelo servidor, limites de
confiança, e campos permitidos. Não existe executor conectado a esse
interpretador. Exceções e outputs inválidos não disparam ação.

TrueConf preview:

    /entender diagnostique o PC 192.168.57.50
    /entender como posso verificar um backup?
    /entender faz um backup de imagem e depois formata o PC 57.50

O comando /entender retorna o plano e informa que nada foi executado.

NOTA: o LLM atual não foi homologado com esse prompt em ambiente real.
"confidence" é uma autoestimativa do modelo, não probabilidade calibrada;
a regra de autorização deve depender de validação objetiva e confirmação,
não de um percentual dado pelo modelo.

## Evolução proposta para uso real

1. Classificador estruturado com ferramenta de teste e evals.
2. Resolução de entidades: IP, MAC, serial, host, chamado, cliente e
   equipamentos mencionados pelo técnico, resolvidos por inventário confiável.
3. Contexto de tarefas persistido no servidor: acompanhamento de job,
   última ação, dispositivo alvo, quem solicitou, quando, expiração e
   idempotência, sem depender do histórico livre do LLM.
4. Policy/permissions antes do executor: operações read-only automáticas
   somente com alvo explícito; ações de impacto requerem autorização; backup,
   restauração, alteração de DHCP/PXE, formatação, desligamento de servidor
   e exclusões precisam de fluxos próprios.
5. Executor com catálogo fechado de operações. LLM NUNCA gera PowerShell,
   bash, SQL, chamadas WinRM genéricas ou parâmetros arbitrários.
6. Observabilidade: logs com trace_id e motivo de classificação,
   mascarando credenciais e conteúdo pessoal; replay offline de mensagens
   de TrueConf desidentificadas para medir falsos positivos e falhas.
7. FOG: integração restrita à API para cadastro de host, imagem por chamado,
   Capture e consulta de tarefas. Deploy separado, autorizado e com checagem
   de disco/serial. Não automatizar mudança de DHCP no início.
8. Revisar a autenticação de entrada do webhook TrueConf. Um user_id
   recebido do payload não comprova identidade; não habilitar ações críticas
   via webhook sem verificação de proveniência.

## Métricas antes da ativação

- Repositório de pelo menos 100 frases reais de técnicos, desidentificadas,
  incluindo falhas anteriores, gírias, erros de digitação e perguntas.
- Taxa de intenção correta (por categoria) e de alvo correto.
- Taxa de execução indevida obrigatoriamente **zero** no conjunto de testes.
- Perguntas, citações, negações e operações indisponíveis nunca executam.
- Separar "entendeu o pedido" de "ferramenta conseguiu executar".
- Validar mudanças em ambiente isolado e migrar gradualmente, com rollback.

## Infra FOG proposta

FOG em VM Linux própria em hypervisor disponível 24/7 (Proxmox,
Hyper-V ou outro), nunca instalado diretamente no Jarvis de produção.
Instalação FOG sem ativar servidor DHCP/ProxyDHCP por padrão. WDS e
DHCP atuais permanecem intactos durante homologação. Storage usa volume
compatível com FOG, separado dos antigos .mrimg; validar NFS e espaço
antes de escolher onde persistir /images.

Referências: https://docs.fogproject.org/en/latest/installation/server/requirements/
e https://vm.fogproject.org/download.php
