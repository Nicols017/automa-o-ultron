# ⚡ MDT & Zero-Touch Automation - Ultron Lab

Se você está com **preguiça de configurar o MDT (Microsoft Deployment Toolkit)** do zero ou quer uma solução mais rápida, este diretório contém **3 alternativas prontas**, desde a dispensa total do servidor MDT até a configuração automática em 2 minutos.

---

## 🎯 As 3 Formas de Operar (Escolha a mais fácil para você)

### 🥇 Opção 1: Ultron Anywhere (Dispensa 100% o Servidor MDT)
* **Quando usar:** Em máquinas novas saídas da caixa, computadores já formatados por pendrive comum, no Wi-Fi ou fora da bancada.
* **Como fazer:** No Windows, abra o PowerShell como Administrador e execute:
```powershell
irm http://192.168.57.43:7000/bootstrap.ps1 | iex
```
* **O que acontece:**
  1. Identifica automaticamente a Service Tag / Serial, Modelo, IP e MAC.
  2. Cria o usuário de automação `UltronAdmin` e configura o WinRM / Firewall.
  3. Notifica o Ultron Server (`/api/v1/mdt/completed`).
  4. O Ultron assume a máquina e roda a esteira completa (Softwares, Milvus, Domínio, Laudo PDF).

---

### 🥈 Opção 2: Pendrive USB Zero-Touch (Formata Sozinho Sem Servidor MDT)
* **Quando usar:** Quando você precisa formatar um PC do zero na bancada, mas não quer subir/configurar o servidor MDT/PXE.
* **Como fazer:**
  1. Crie um pendrive de instalação do Windows 10 ou 11 (via Rufus ou Media Creation Tool).
  2. Copie o arquivo [`autounattend.xml`](file:///mdt/autounattend.xml) para a **raiz do pendrive**.
  3. Dê boot pelo pendrive no computador da bancada.
* **O que acontece:**
  - O Windows é instalado de forma 100% autônoma (particiona o disco, pula telas de idioma/conta Microsoft/OOBE, bypass de requisitos de TPM/SecureBoot).
  - No primeiro boot, ele executa o bootstrap do Ultron automaticamente.

---

### 🥉 Opção 3: MDT Plug-and-Play (Configuração em 2 Minutos)
* **Quando usar:** Se você quiser usar a infraestrutura PXE/MDT oficial no servidor `192.168.57.87`.
* **Como fazer:**
  1. No servidor MDT, execute o script PowerShell:
     ```powershell
     .\Setup-MDT-Automation.ps1 -DeploymentSharePath "D:\DeploymentShare$"
     ```
  2. Na sua **Task Sequence do MDT**, adicione na última etapa (*State Restore*):
     - **Add** > **General** > **Run PowerShell Script**
     - Script: `%SCRIPTROOT%\Notify-Ultron.ps1`
* **Arquivos incluídos e pré-configurados:**
  - [`CustomSettings.ini`](file:///mdt/CustomSettings.ini): Pula todas as telas do assistente do MDT (Zero-Touch puro), nomeia a máquina automaticamente como `LAB-%SerialNumber%` e define senha administrativa.
  - [`Bootstrap.ini`](file:///mdt/Bootstrap.ini): Conecta direto no compartilhamento `\\192.168.57.87\DeploymentShare$` sem pedir credenciais.
  - [`Notify-Ultron.ps1`](file:///mdt/scripts/Notify-Ultron.ps1): Habilita WinRM e envia o Webhook ao Ultron ao término da imagem.

---

## 📁 Estrutura dos Arquivos Deste Diretório

| Arquivo | Finalidade |
| :--- | :--- |
| [`CustomSettings.ini`](file:///mdt/CustomSettings.ini) | Regras Zero-Touch do MDT (pula telas, nome por serial, idioma pt-BR). |
| [`Bootstrap.ini`](file:///mdt/Bootstrap.ini) | Autenticação automática no compartilhamento de rede do MDT. |
| [`autounattend.xml`](file:///mdt/autounattend.xml) | Instalação autônoma via Pendrive USB sem servidor PXE. |
| [`Setup-MDT-Automation.ps1`](file:///mdt/Setup-MDT-Automation.ps1) | Script para injetar as configurações no Deployment Share do MDT. |
| [`scripts/Notify-Ultron.ps1`](file:///mdt/scripts/Notify-Ultron.ps1) | Webhook disparado no final da Task Sequence para o Ultron. |
