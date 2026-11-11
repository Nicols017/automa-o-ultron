# Ultron: verificação Macrium pelo TrueConf/API — sem Proxmox

**Estado:** implementado na branch de revisão; ainda não implantado no Jarvis. Não é necessário subir VMs ou restaurar imagens para verificar um .mrimg.

## Fluxo

1. Técnico autorizado envia /verificar_backup <caminho.mrimg> no TrueConf, ou utiliza a API autenticada.
2. O Ultron valida o caminho contra raízes permitidas e não aceita host Windows arbitrário do usuário.
3. WinRM executa Verify-MacriumImage.ps1 em uma única estação Windows aprovada com MRVerify.exe instalado.
4. MRVerify verifica o conjunto com --set e --logfile, sem --fix.
5. A estação compara retorno do MRVerify, mensagens de sucesso, arquivo e metadados. O log fica somente no Windows, em C:\ProgramData\Ultron\MacriumVerifyLogs.
6. O Ultron envia sucesso/erro ao TrueConf, mas nunca restaura, formata ou autoriza o MDT.

Esse resultado ainda NÃO é o comprovante de backup assinado de core/backup_gate.py. A verificação não comprova uma restauração real.

## Configuração quando houver autorização de homologação

Variáveis do processo do serviço Ultron — todas são necessárias, e o recurso fica desativado por padrão:

ULTRON_MACRIUM_VERIFY_ENABLED=1
ULTRON_MACRIUM_VERIFIER_HOST=192.168.57.XX
ULTRON_MACRIUM_ALLOWED_ROOTS=C:\Users\nicolas.silva\Desktop
ULTRON_MACRIUM_ALLOWED_TRUECONF_USERS=nicolas.silva

O IP XX precisa ser substituído pelo IP real da estação Windows que tem o Macrium e WinRM autorizados, não pelo IP do Jarvis. Não permitir acesso a PCs desconhecidos.

Primeiro teste: cópia local TIMENOW previamente verificada no Windows.

~~~text
/verificar_backup "C:\Users\nicolas.silva\Desktop\12282 - TIMENOW NÃO APAGAR\BADE766865EE753C-00-00.mrimg"
~~~

Depois, com permissão de leitura da estação Windows no storage, permitir o root UNC:

~~~text
ULTRON_MACRIUM_ALLOWED_ROOTS=\\192.168.57.112\backups3
~~~

Usar o arquivo exato no compartilhamento. Não listar/varrer/inspecionar automaticamente todos os backups, porque 31-185 GB de leitura podem sobrecarregar o armazenamento.

Importante: sessão WinRM às vezes não consegue acessar um segundo servidor SMB (double hop), embora o usuário interativo consiga. Isso requer um desenho seguro de autenticação delegada, não alterações globais no Jarvis ou liberação de WinRM Basic.

## Comandos TrueConf

~~~text
/verificar_backup "C:\Users\nicolas.silva\Desktop\12282 - TIMENOW NÃO APAGAR\BADE766865EE753C-00-00.mrimg"
/status_verificacao verify_ID
~~~

Só usuários explicitamente autorizados podem executar. O retorno de sucesso do MRVerify não significa que uma restauração foi testada, e a formatação permanece bloqueada.

## API segura

POST /api/v1/bench/action/verify-macrium
JSON: {"image_path":"C:\\Users\\nicolas.silva\\Desktop\\12282 - TIMENOW NÃO APAGAR\\BADE766865EE753C-00-00.mrimg"}

GET /api/v1/bench/action/verify-macrium/{job_id}

Ambas exigem HTTPS e Authorization: Bearer com ULTRON_ADMIN_API_TOKEN configurado fora do repositório. Nunca trafegar o token por HTTP.

## Limitações atuais

- Jobs são armazenados apenas em memória. Reiniciar o Ultron durante a execução pode deixar o resultado desconhecido. Não existe reenvio automático.
- O script ainda não foi testado por WinRM real. O CI valida o parser PowerShell no Windows e o resultado da ponte com WinRM falso.
- O WinRMExecutor legado possui tentativas de reconexão e credenciais fixas, que precisam de revisão e rotação antes de um deploy geral.
- O webhook TrueConf precisa de validação de identidade/autorização robusta antes de habilitar operações autenticadas em produção.
- Branch tem mudanças incompatíveis com agentes HTTP atuais; nunca implantar o PR completo sem um plano de migração TLS.
- Qualquer modificação ou reinício do Ultron exige homologação, backup e autorização explícita. Ubuntu, Docker e os outros serviços do Jarvis ficam intactos.
