# Verificador Macrium Reflect 8 — guia de laboratório

Status: implementado no GitHub e testado somente com MRVerify.exe simulado. NÃO
testado contra Macrium real, .mrimg real ou storage da Pense Rede.

**Não instalar no Jarvis, não testar no storage real e não desbloquear MDT.**

## Base oficial

Macrium Reflect 8 inclui MRVerify.exe em
C:\Program Files\Macrium\Reflect\MRVerify.exe. Segundo a documentação, deve
executar como administrador e usa --set para verificar o conjunto completo,
--logfile para registrar o resultado, código 0 para sucesso e 1 para erro.
A opção --fix altera imagens em caso de recuperação e NUNCA é usada.

Fonte: https://knowledgebase-old.macrium.com/display/KNOW80/Verifying+image+and+backup+files+from+the+command+line

Não confundir com reflect.exe -v: isso valida XML de definição, não a integridade
de uma imagem Macrium.

## Máquina Windows independente

Utilizar VM Windows licenciada de laboratório, Python 3, Macrium Reflect 8 e
um compartilhamento de imagens de TESTE, com permissão de leitura, fora do
ambiente de produção. A máquina não precisa de acesso ao Jarvis ou TrueConf.

Inventário de teste mantido pelo técnico em:
C:\UltronVerifier\private\devices.json

Exemplo fictício JSON:

~~~json
{
  "devices": {
    "SN-TESTE-001": {
      "source_ip": "192.0.2.50",
      "image_path": "\\\\192.0.2.112\\Backups\\laboratorio\\teste.mrimg"
    }
  }
}
~~~

Os endereços 192.0.2.x são reservados para documentação, não são endereços
reais do storage da Pense Rede.

Inventário e chave do verificador devem ter ACL de leitura restrita e ficar
fora do Git. Não aceitar serial/IP/arquivo da máquina cliente sem conferência
independente. A imagem não é analisada automaticamente para extrair serial.

Chave de assinatura binária aleatória de no mínimo 32 bytes:
C:\UltronVerifier\private\verifier.key

Nunca colocar a chave no comando, logs ou TrueConf. O argumento aponta apenas
para o caminho do arquivo, não para o conteúdo secreto.

## Executar em PowerShell na estação de laboratório

Comando único (substituir SOMENTE por destinos de TESTE):

~~~powershell
python .\verifier\macrium_verify.py --serial "SN-TESTE-001" --inventory "C:\UltronVerifier\private\devices.json" --share "\\192.0.2.112\Backups" --signing-key "C:\UltronVerifier\private\verifier.key" --output "C:\UltronVerifier\audit" --verifier-id "lab-windows-verifier-01"
~~~

A ferramenta chama MRVerify.exe com caminho completo de imagem,
--set e --logfile. Nunca chama --fix. Exige status zero e log de sucesso,
calcula SHA-256 da imagem, verifica se tamanho e horário não mudaram e
emite JSON assinado HMAC. Em falha não emite comprovante.

O core/backup_gate.py recebe o comprovante, valida assinatura, serial/IP,
caminho autorizado e validade. A API NÃO possui rota que libere MDT por isso.

## Limites e validação futura

O hash emitido cobre apenas o arquivo selecionado. MRVerify --set é invocado
para conferir todos os arquivos necessários ao conjunto, mas o script não
calcula SHA-256 individual para cada incremento/diferencial. Uma verificação
bem-sucedida não substitui restauração em máquina descartável.

Os testes de CI são offline e utilizam arquivo inventado + executável
simulado. NÃO significam verificação de imagem real.

Antes de qualquer uso real:
- Confirmar CLI e saída de MRVerify.exe com imagem de laboratório.
- Testar corrupção, conjunto incompleto, imagem protegida por senha e timeout.
- Testar restauração em disco descartável, isolado dos computadores de cliente.
- Conferir ACLs da chave, inventário, logs, arquivos .mrimg e comprovantes.
- Conectar a um processo de autorização humana, com trilha de auditoria.
- Validar HTTPS/segredos do Ultron antes de atualizar agentes.
- Ter rollback e aprovação específica para reiniciar apenas ultron.service.

O Jarvis, o Docker e os demais serviços da Pense Rede continuam intocados.
