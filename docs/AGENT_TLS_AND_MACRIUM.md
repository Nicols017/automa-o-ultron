# Segurança de agente e gate Macrium — somente homologação

NÃO IMPLANTAR NO JARVIS. O servidor atual usa HTTP na porta 7000; o novo protocolo exige HTTPS e credenciais por dispositivo. A produção permanece intocada.

## Constatações técnicas

O script Backup-UserData.ps1 copia pastas de usuários com Robocopy. Não cria imagem de disco Macrium Reflect 8 e não verifica a integridade de uma imagem. Por isso a formatação MDT continua bloqueada em todas as rotas TrueConf.

O novo core/backup_gate.py valida a assinatura e os metadados de um comprovante emitido por um verificador confiável, mas NÃO executa Macrium Verify, NÃO verifica os bytes da imagem de backup e NÃO autoriza formatação sozinho.

## Autenticação de agentes — futura homologação

- Criar tokens aleatórios individuais com pelo menos 32 caracteres por número de série; nunca usar senha de automação compartilhada como token.
- No servidor de HOMOLOGAÇÃO, criar arquivo JSON fora do Git, como /etc/ultron/agent-credentials.json, com mapeamento serial-token. Arquivo com modo 0600, pasta restrita.
- Variável ULTRON_AGENT_CREDENTIALS_FILE aponta ao arquivo. Sem configuração, API de agentes falha fechada.
- No Windows de HOMOLOGAÇÃO, salvar token em %ProgramData%\Ultron\agent.token, com ACL apenas de SYSTEM e Administradores, não no executável.
- O agente envia X-Ultron-Agent-ID igual ao serial e Authorization Bearer com o token daquela máquina. Outros dispositivos não podem buscar tarefas nem enviar resultados para esse serial.
- Registro, heartbeat, alertas, consulta da fila e envio de resultados precisam de token válido. Com HTTP, o agente se recusa a enviar credenciais e a API rejeita.
- É necessária uma frente HTTPS com certificado confiável e encaminhamento seguro de proxy, configurando hosts explicitamente permitidos. Não confiar em cabeçalho X-Forwarded-Proto arbitrário da rede.
- A rota de limpeza remota permanece bloqueada mesmo quando um operador envia credenciais válidas.

ATENÇÃO: Outros endpoints administrativos do sistema, bem como os mecanismos legados de WinRM, Bootstrap e download OTA, ainda precisam de revisão e autenticação. Não afirmar que o sistema inteiro esteja seguro.

## Comprovação Macrium Reflect 8

Um verificador independente, autorizado e isolado da IA deve:
1. Criar/conferir a imagem real de disco Macrium (.mrimg) com local de armazenamento e serial corretos.
2. Executar Macrium Verify Image e registrar o resultado original e log, confirmar arquivo presente, tamanho e hash SHA-256 calculado do arquivo.
3. Emitir comprovante com kind macrium_reflect_8_image, verify_method macrium_reflect_8_verify, verification_status SUCCESS, verifier_id, serial, source_ip, storage_path, sha256, size_bytes, verified_at, issued_at e expires_at.
4. Assinar os dados com HMAC SHA-256 e chave exclusiva do verificador, fora do repositório. O servidor consulta ULTRON_MACRIUM_VERIFIER_KEY_FILE e ULTRON_MACRIUM_BACKUP_SHARE; sem chave ou compartilhamento autorizados, recusa.
5. O operador deve vincular a evidência ao equipamento, checar o resultado e autorizar manualmente o MDT. Homologar restauração com mídia de teste e destino isolado.

IMPORTANTE: A validação de assinatura NÃO prova por si só que a imagem seja restaurável ou ainda esteja íntegra. Não existe ainda o verificador real, nem integração para liberar o MDT. A formatação segue desabilitada.

## Bloqueios de produção

- Credenciais legadas e senhas estáticas no código público devem ser revogadas/rotacionadas e removidas.
- Endpoints de administração e execução WinRM precisam de autorização de operador.
- HTTPS funcional e certificado confiável para agentes; rollout coordenado dos tokens.
- Compilação e integração real do UltronAgent C# e TrueConf em ambiente independente.
- Verificador Macrium e teste de restauração de mídia, antes de qualquer wipe.
- Backup/rollback do código Ultron antes de mudança; autorização explícita antes de reiniciar SOMENTE ultron.service.
- Não alterar ou reiniciar Ubuntu, Docker, outros sistemas do Jarvis, rede global ou discos da produção.
