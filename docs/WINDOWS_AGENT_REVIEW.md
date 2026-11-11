# Revisao Windows — desenvolvimento, sem implantacao

WinRM e recurso nativo do Windows (WS-Management/PowerShell Remoting).
UltronAgent e um executavel separado, instalado como UltronService.
Um pode estar funcionando enquanto o outro falha. Token da API nao e senha
Windows. Instalar o agente nao deve abrir portas nem criar um administrador.

## Diagnostico encontrado
O agente antigo reclassificava redes como privadas, alterava UAC e ExecutionPolicy,
abria SMB/RPC/RDP/WinRM, ativava Basic/AllowUnencrypted e TrustedHosts=*,
criava administrador com senha fixa e repetia quickconfig no monitoramento.
O executor tentava contas conhecidas e repetia comandos ate tres vezes:
risco de bloqueio de conta e de repetir uma operacao ja executada.
O bootstrap misturava provisionamento, registro e inicio da esteira.
O instalador C# duplicado ignorava falhas de copia/sc e anunciava sucesso.
URL passada no console nao persistia para o servico.

## Comportamento revisado
- Mantidos coleta de hardware, alertas, heartbeat, polling autenticado e contratos
  de resultados; registro nao informa senha Windows.
- Removidos provisionamento automatico, auto-instalacao e OTA sem verificacao
  de assinatura. Entradas C# de instalacao agora orientam ao instalador PowerShell.
- Bootstrap antigo falha explicitamente. Nao inicia pipeline nem chama MDT.
- server.url persistente em %ProgramData%/Ultron, origem HTTPS obrigatoria.
  --server continua aceito para uso interativo; servico le o arquivo persistente.
- agent.token individual (32+ caracteres), identidade BIOS atual e HTTPS; nao
  ha autoenrollment: administrador cadastra a mesma identidade no servidor.
  Redirect HTTP nao e seguido em requisicoes autenticadas.
- Instalar: revisar agent/Install-Agent.ps1, fornecer SourceExe e ExpectedSha256
  obtido por canal confiavel, usar -WhatIf primeiro. Esse modo ainda le arquivos,
  valida hash/ACL e pode falhar nas precondicoes, mas nao instala.
  O script exige ACL da configuracao restrita a SYSTEM/Administradores,
  para o servico com espera limitada, guarda backup unico, copia, configura e
  verifica Running. Nao executamos esse instalador nesta revisao.
- Instalacao continua como LocalSystem: privilégio alto, preservado para tarefas
  existentes. Migrar para conta restrita exige inventario de tarefas e homologacao.
- WinRM: uma identidade explicita, ou cache por host, ou padrao configurado.
  Nenhuma lista de contas/senhas adivinhadas. Campos de retorno existentes mantidos.
  TLS validado, HTTPS/5986 padrao, NTLM com criptografia de mensagens obrigatoria.
  HTTP/5985 antigo requer scheme=http, port=5985 e allow_http_ntlm=true explicitos.
  Isso nao habilita Basic nem AllowUnencrypted no Windows.
- Comando executado uma unica vez; timeout/transporte retorna outcome=UNKNOWN,
  retry_safe=false. Verifique o resultado antes de repetir. Scripts nao sao
  minificados nem carregados por arquivo temporario compartilhado.
  Strings de parametros sao literais PowerShell; nomes de parametros validados.

## Procedimento de investigacao (somente em laboratorio autorizado)
1. Registro/API: diferencie DNS/TLS de HTTP 401 (token/identidade), 403 (alvo),
   426 (HTTPS) e 503 (mapa de credenciais/ACL/configuracao do servidor).
   Em Linux o arquivo ULTRON_AGENT_CREDENTIALS_FILE exige modo 0600.
   Nao copie token para comandos, tickets ou logs; nao confie em forwarded headers
   de proxies arbitrarios. Serial generico/duplicado exige resolucao manual antes
   do cadastro; este patch nao altera IDs existentes.
2. WinRM: examine Get-Service WinRM e winrm enumerate winrm/config/listener.
   Inspecione Get-NetConnectionProfile e regras efetivas de firewall/GPO.
   Porta TCP acessivel nao prova autenticacao nem permissao de executar scripts.
3. HTTPS: confira cadeia/CA, expiracao, SAN e listener 5986. IP so funciona com
   SAN correspondente; prefira FQDN. Nunca solucione ignorando certificado.
4. 401: confira senha/conta e formato HOST\usuario ou DOMINIO\usuario. Interrompa
   tentativas antes de bloquear a conta. Token Ultron nao autentica WinRM.
5. Access denied/0x80070005: investigue autorizacao do endpoint e filtragem UAC
   de contas locais. Nao desative UAC remoto globalmente como reparo automatico.
6. Kerberos/SPN/relogio: a implementacao atual usa NTLM; nao promete Kerberos.
   Projetar Kerberos exige dependencias, FQDN/SPN e homologacao separada.
7. Timeout/refused: diferencie rota/VPN, perfil publico, GPO, listener, firewall,
   quotas e falha de comando. Consulte Microsoft-Windows-WinRM/Operational
   localmente. O classificador nao confirma causa raiz nem faz reparos.

## Compatibilidade e migracao
**Nao implantar diretamente.** Agentes atuais continuam com a API existente
(serial + token + HTTPS), sem mudanca de schemas. Versoes antigas sem token/HTTP
ja nao atendiam a seguranca da branch. Nao adicionamos bypass.
Contas fixas previamente usadas so funcionarao se fornecidas explicitamente;
o patch nao remove contas nem desfaz politicas existentes. Elas precisam de
inventario e rotacao manual autorizada antes de migrar. Credenciais presentes
no historico Git devem ser consideradas expostas.
Nao alteramos Jarvis, WDS, DHCP, FOG, dominios ou servicos reais.

Os .exe versionados sao antigos, **nao representam este fonte**. Download HTTP
do agente retorna 503 por padrao; ULTRON_AGENT_DOWNLOAD_ENABLED=true somente
depois de pacote recompilado/revisado e validacao de compatibilidade. Nao houve
publicacao de binario. O builder legado ainda nao possui manifesto de proveniencia:
nao usar mtime/tamanho como garantia de correspondencia. OTA de agentes antigos
tambem requer controle operacional; este patch nao atualiza maquinas existentes.

Rollback: guardar versao/configuracao/ACL e hash anteriores; parar somente
UltronService em laboratorio autorizado, restaurar pacote e arquivos, verificar
registro/heartbeat. O backup do instalador e local e nao restaura automaticamente
o servico se a copia/inicio falhar; falha exige intervencao. Nunca reverter para
HTTP sem token nem reativar conta/senha compartilhada. Nao ha rollback de WinRM
neste patch porque a nova instalacao nao o modifica. Desinstalador antigo ainda
tem limpeza de regras Ultron: nao executar sem inventario e autorizacao.

## Verificacao offline e limites
tests/test_windows_agent_review.py usa clientes falsos: nenhuma conexao e aberta.
Inclui ausencia de credenciais implicitas, precedencia de identidade, execucao
unica no timeout, nao vazamento de excecoes, erro de script separado de auth,
TLS/criptografia, opt-in HTTP, classificacao e parametros literais.
CI executa regressao offline em Ubuntu e Windows; Windows tambem compila o C#
e analisa sintaxe PowerShell, sem executar agente ou instalador.
Isso nao comprova SCM, ACL efetiva, WinRM real, VPN/GPO, serial unico, tarefas
privilegiadas ou compatibilidade com todos os Windows. Exigem VMs descartaveis
com autorizacao futura. NAO foram testados em maquinas reais.

Fontes:
- [Microsoft: seguranca do WinRM](https://learn.microsoft.com/en-us/powershell/scripting/learn/remoting/winrmsecurity)
- [Microsoft: troubleshooting remoto](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_remote_troubleshooting)
