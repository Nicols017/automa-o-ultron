# Verificacao por programa — sem deploy

Implementacao na branch/PR draft, sem merge, instalacao em maquina real ou
contato com gerenciadores de pacotes reais durante os testes.

## Antes e depois
Antes: exit code positivo do instalador podia gerar "SOFTWARES INSTALADOS".
Agora: tentativa e consulta sao separadas, vinculadas por RunId aleatorio.
A resposta informa cada pacote, versao encontrada e codigo do instalador.
Nao atribui a instalacao a esta tentativa se o programa ja estava presente.

Install-UnifiedPackages.ps1 preserva entrada por Packages e bundles, Winget,
Chocolatey e Scoop. Emite ULTRON_INSTALL_ATTEMPTS_JSON com manager, exit_code e
reported_success por pacote. Remove --force das tentativas Winget e nao considera
lista vazia como sucesso. Logs dizem retorno do instalador, nao presenca validada.

Verify-InstalledPackages.ps1 executa somente winget export --include-versions,
com source winget, para JSON temporario de nome unico. Consulta limitada a 60s;
se exceder, interrompe apenas seu proprio processo de consulta, nunca instaladores.
Arquivo temporario e removido best-effort. Nenhum source update/install/reparo
e executado pelo verificador. Comando export pode consultar fontes configuradas.

O verificador retorna somente itens solicitados. Confirmacao exige identificador
exato, uma correspondencia unica e versao valida. Sem parsing de tabela em ingles.
Ausencia no export nao prova ausencia no Windows: retorna UNCONFIRMED.

## Avaliacao no servidor
core/software_installation.py valida schema, RunId, conjunto exato de pacotes,
duplicatas, codigos e versoes. JSON ausente/invalido/duplicado ou saida antiga nao
promove exit 0 a sucesso. Strings de controle/versoes desconhecidas sao recusadas.
Limite da entrada: 1 a 50 identificadores; nomes amigaveis mantidos, mas somente
IDs reconhecidos no inventario podem receber confirmacao.

O servidor entrega o script de instalacao uma vez. Depois recebe relatorio
terminal e faz uma consulta de verificacao. Timeout/falha de transporte na
instalacao nao gera nova instalacao nem consulta concorrente: resultado UNKNOWN.
O verificador nao aciona fallback de instalacao para resolver itens ausentes.

SUCCESS: todos os itens encontrados com versao, tentativa positiva e comando
de instalacao concluido sem erro.
PARTIAL: apenas parte foi confirmada ou ha programa encontrado com erro/retorno
nao confirmado do instalador.
ERROR: instaladores reportaram falha explicita e nao houve presenca confirmada.
UNKNOWN: sem dados confiaveis suficientes, consulta falhou ou transporte incerto.
Estados individuais distinguem CONFIRMED_PRESENT, PRESENT_WITH_UNCONFIRMED_INSTALL
e UNCONFIRMED. Nenhum deles comprova licenca, abertura do aplicativo ou saude.

## Onde vale
- /softwares e caminhos que chamam esse handler: resposta por pacote e ID de tarefa.
- APIs /api/v1/packages/install e /api/v1/bench/action/install-software:
  mesma avaliacao e registro de tarefa de api_operator.
- Restauracao de bundle em UnifiedPackageManager: mesma avaliacao por pacote;
  migracao completa desse fluxo ao registro de tarefas ainda e separada.
- Preparacao completa (Install-LabStandard.ps1), upgrades e outros instaladores
  ainda nao foram migrados. Nao anunciamos verificacao onde ela nao existe.

## Persistencia e compatibilidade
TaskRegistry aceita PARTIAL e evidencia SOFTWARE_PRESENCE_VERIFIED.
Nova tabela aditiva task_packages guarda somente pacotes solicitados, gerenciador,
codigo do instalador, retorno positivo/negativo, estado de presenca e versao.
Sem inventario completo da maquina, stdout, comandos, credenciais ou transcripts.
Get por ID continua filtrado pelo proprietario; /tarefa <ID> recupera detalhes
apos restart. /tarefas mostra resumo. Registros antigos permanecem com evidencia
antiga e NAO se tornam verificados retroativamente.

Clientes precisam aceitar PARTIAL e consultar package_results/verification_method.
success agora significa todos os itens confirmados, nao apenas exit 0.
stdout/output ficam vazios nos fluxos migrados; usar os resultados estruturados.
installed da API de bancada e compatibilidade para itens encontrados, nao prova
de que esta chamada os instalou. Campos gerais e rotas autenticadas preservados.

Fonte PowerShell com texto PT-BR usa BOM UTF8 para Windows PowerShell 5.1;
loader WinRM usa utf-8-sig para remover BOM antes de montar scriptblock.

## Limites reais
WinGet export depende da correlacao do catalogo com os aplicativos registrados
e do contexto de execucao. Pode nao encontrar programas de outros usuarios,
apps sem correlacao, fontes indisponiveis ou instalacoes por outros managers.
Chocolatey/Scoop e consultas por nome continuam como tentativas legadas, mas
nao recebem confirmacao inventada se o ID nao aparecer no export Winget.

Ainda ha fallbacks/repeticoes internos ao instalador legado e atualizacao de
fontes na etapa de instalacao. Esta rodada nao afirma entrega unica por manager:
a garantia de nao reenviar refere-se ao comando remoto e a verificacao separada.
Homologar esses caminhos antes de ampliar uso. Sem verificacao de versao minima
ou versao solicitada nesta etapa: informa somente a versao observada.

Homologacao futura: WinGet presente/ausente, contexto SYSTEM vs usuario,
Windows PT/EN, licencas/fontes, reboot pendente, programa preexistente e
falhas reais dos instaladores em VMs descartaveis autorizadas.

## Testes
18 testes Python offline: exit 0 sem programa, parcial, falha com programa
presente, relatorios invalidos, RunId divergente, pacotes/versoes adulterados,
timeout sem replay e persistencia por proprietario.
Windows PowerShell 5.1: sete cenarios do verificador com WinGet falso e dois
cenarios de relatorio do instalador com TODOS os comandos nativos simulados.
Nao foram instalados programas nem usados bancos/inventarios de maquinas reais.

Fontes primarias:
- https://learn.microsoft.com/en-us/windows/package-manager/winget/export
- https://learn.microsoft.com/en-us/windows/package-manager/winget/list
