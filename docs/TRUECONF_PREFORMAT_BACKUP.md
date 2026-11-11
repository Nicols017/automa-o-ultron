# Backup sob demanda pelo TrueConf (antes de formatar)

## Objetivo

O técnico pede o backup via TrueConf; o Ultron ordena uma cópia ao computador
Windows da bancada e salva o resultado no storage. A formatação é uma operação
separada e **continua bloqueada**.

## Modo implementado: cópia de pastas selecionadas (Robocopy)

Comando via TrueConf:

    /backup 192.168.57.50 TIMENOW 12282

Alternativa: abrir o menu do TrueConf, escolher backup, indicar IP, cliente e
chamado. O Ultron encaminha a solicitação via WinRM, com uma tarefa por vez,
e depois envia um retorno assíncrono ao técnico. Consulta:

    /status_backup files_<id>

Destino configurado, criado somente quando o backup for explicitamente
disparado:

    \\192.168.57.112\backups3\12282 - TIMENOW\ultron-files-<data>-<id>

Pastas copiadas se existirem:

- Desktop
- Documents
- Downloads
- Pictures
- Music
- Videos
- Favorites
- Favoritos do Chrome (arquivo Bookmarks no perfil Default)

O backup **não é completo**. Não inclui necessariamente dados de OneDrive
somente online, Outlook PST em outros caminhos, discos extras, aplicativos,
dados ocultos de programas, discos criptografados, partições de boot, arquivos
abertos que não podem ser copiados ou outros perfis/pastas fora da seleção.
Não substitui uma imagem de disco. O técnico deve inspecionar o escopo real
antes de formatar uma estação.

O script de cópia usa Robocopy com /E /XJ /R:2 /W:2; não usa /MIR nem /PURGE.
Uma execução sempre cria uma pasta nova, sem apagar backups anteriores.
Os códigos de retorno de Robocopy >= 4, ausência de arquivos e falhas
de acesso geram **ERROR**. Um retorno SUCCESS significa apenas que as pastas
selecionadas foram copiadas na execução; não significa recuperação testada.

## Configuração — desativado até ser autorizado

Na configuração do processo Ultron:

    ULTRON_FILES_BACKUP_ENABLED=1
    ULTRON_FILES_BACKUP_SHARE=\\192.168.57.112\backups3
    ULTRON_FILES_BACKUP_ALLOWED_SUBNET=192.168.57.0/24
    ULTRON_BACKUP_ALLOWED_TRUECONF_USERS=<usuarios_trueconf_autorizados>

Nunca colocar credenciais no Git. A estação Windows de origem necessita
de WinRM com autenticação forte e acesso de gravação ao storage. Em uma
sessão WinRM, o acesso a um segundo servidor SMB pode falhar por
**double hop**. Não habilitar CredSSP, WinRM Basic ou TrustedHosts global
sem um projeto de credenciais aprovado. Não configurar isso no Jarvis
automaticamente.

O Ultron rejeita como alvo o Jarvis (192.168.57.43), o WDS (192.168.57.87)
e o storage (192.168.57.112). Não executa tarefa quando configuração
obrigatória estiver ausente.

A API usa o mesmo mecanismo:

    POST /api/v1/bench/action/backup
    {"ip":"192.168.57.50","client_name":"TIMENOW",
     "ticket_number":"12282","source_drive":"C:"}

    GET /api/v1/bench/action/backup/files_<id>

Ambas exigem autenticação do operador e HTTPS. O retorno POST é uma
aceitação de tarefa, não confirmação de backup concluído. Jobs ficam
somente em memória; em caso de restart do Ultron o estado pode ser
desconhecido. Não repetir automaticamente sem inspeção da pasta no
storage para evitar cópias duplicadas e desperdício de espaço.

## Modo ainda necessário: imagem completa Macrium (.mrimg)

Usuário confirmou que o foco operacional é solicitar o backup do
computador antes da formatação pelo TrueConf. As imagens manuais existentes
no storage são arquivos .mrimg do Macrium Reflect.

**Essa etapa ainda não foi implementada.** O MRVerify.exe só verifica uma
imagem existente. Não cria um backup.

Opções técnicas que exigem validação e licenciamento:

1. Instalar/configurar um software de imagem na **máquina de origem**
   e disparar uma definição de backup por WinRM/Agente Ultron, enviando
   a imagem diretamente ao storage.
2. Inicialização em ambiente de recuperação/PXE com ferramenta de imagem
   licenciada, cuidadosamente coordenada com WDS/MDT, sem formatar até a
   imagem estar comprovadamente íntegra.

O instalador Macrium Reflect **Free** não instala no Windows Server WDS.
O servidor WDS estar ligado não significa que ele consiga ler setores
de disco de outra máquina remota sem agente ou boot controlado. Não
contornar bloqueio de licença.

O caminho do Macrium baseado em XML usa comandos oficiais do tipo
'reflect.exe -e -w -full <definicao.xml>' quando uma edição compatível
do Reflect estiver instalada e uma definição previamente preparada
estiver disponível. Não implantar de forma indiscriminada em clientes.

Referência: documentação Macrium Reflect 8 "Using Macrium Reflect from the
command line", https://knowledgebase.macrium.com/spaces/flyingpdf/pdfpageexport.action?pageId=7758544

**Nenhuma etapa de backup, nem mesmo um SUCCESS de Robocopy, autoriza MDT.**
O gate pré-formatação exige evidência independente de backup de disco,
prova de associação à máquina e aprovação do operador, a definir.

## Situação da implantação

Essa funcionalidade está apenas na branch GitHub de homologação, não no
Jarvis. Branch contém mudanças TLS e de agent incompatíveis com o HTTP
legado. É obrigatório plano de deploy/rollback, revisão do TrueConf e
WinRM e autorização antes de tocar o serviço Ultron. Não reiniciar
o Ubuntu, WDS, Docker, storage ou serviços não relacionados.
