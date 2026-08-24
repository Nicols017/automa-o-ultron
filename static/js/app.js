/**
 * Ultron Platform - Frontend Controller & Realtime Client
 */

// Application State
const state = {
    activeTab: 'bench',
    clients: [],
    milvusTickets: [],
    reports: [],
    discoveredDevices: [],
    isScanning: false,
    isRunningPipeline: false,
    wanData: null,
    thermalData: null,
    cveResults: [],
    cisaKevResults: [],
    toolVersions: [],
    milvusConfig: null,
    milvusClientTokens: []
};

// Application Initialization
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    loadClients();
    loadMilvusTickets();
    loadReports();
    scanBenchNetwork();
    checkInfraStatus();
    loadWanTelemetry();
    loadThermalTelemetry();
    checkNtpSync();
    checkToolVersions();
    loadCisaKevFeed();
    loadTechQuote();

    // Auto-refresh infrastructure and telemetry status every 30 seconds
    setInterval(() => {
        if (!state.isScanning && !state.isRunningPipeline) {
            checkInfraStatus();
            loadWanTelemetry(false);
            loadThermalTelemetry(false);
        }
    }, 30000);
});

function refreshIcons() {
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

// ==========================================================================
// Navigation & Tabs
// ==========================================================================
function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-item');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.tab;
            switchTab(target);
        });
    });
}

function switchTab(tabId) {
    state.activeTab = tabId;
    
    document.querySelectorAll('.tab-item').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tabId);
    });

    document.querySelectorAll('.view-section').forEach(sec => {
        sec.classList.toggle('active', sec.id === `section-${tabId}`);
    });

    if (tabId === 'reports') {
        loadReports();
    } else if (tabId === 'tools') {
        refreshAllTools();
    }
    refreshIcons();
}

// ==========================================================================
// Milvus & Clients Synchronizer
// ==========================================================================
async function loadClients(forceRefresh = false) {
    const badge = document.getElementById('client-count-badge');
    try {
        const res = await fetch(`/api/v1/clients?force_refresh=${forceRefresh}`);
        const data = await res.json();
        state.clients = data.clients || [];
        
        const clientSelect = document.getElementById('client-select');
        if (clientSelect) {
            clientSelect.innerHTML = '';

            const localGroup = document.createElement('optgroup');
            localGroup.label = 'Perfis Configurados';

            const milvusGroup = document.createElement('optgroup');
            milvusGroup.label = 'Empresas Sincronizadas (Milvus)';

            state.clients.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.nome;
                opt.dataset.clientName = c.nome;

                if (c.source === 'local' || c.has_dedicated_profile) {
                    localGroup.appendChild(opt);
                } else {
                    milvusGroup.appendChild(opt);
                }
            });

            if (localGroup.children.length > 0) clientSelect.appendChild(localGroup);
            if (milvusGroup.children.length > 0) clientSelect.appendChild(milvusGroup);
        }

        if (badge) {
            badge.textContent = `${state.clients.length} empresas`;
        }
    } catch (e) {
        showToast('Erro ao sincronizar clientes', 'error');
        if (badge) badge.textContent = 'Indisponível';
    }
}

async function loadMilvusTickets(forceRefresh = false) {
    const ticketSelect = document.getElementById('ticket-select');
    if (!ticketSelect) return;

    if (forceRefresh) {
        showToast('Sincronizando chamados do Milvus...', 'info');
    }

    try {
        const res = await fetch(`/api/v1/milvus/tickets?force_refresh=${forceRefresh}`);
        const data = await res.json();
        state.milvusTickets = data.tickets || [];

        ticketSelect.innerHTML = '<option value="">-- Seleção manual ou avulsa --</option>';

        if (state.milvusTickets.length === 0) {
            const opt = document.createElement('option');
            opt.value = "";
            opt.textContent = data.milvus_online ? "-- Nenhum chamado aberto --" : "-- Milvus Indisponível --";
            opt.disabled = true;
            ticketSelect.appendChild(opt);
            return;
        }

        state.milvusTickets.forEach(t => {
            const opt = document.createElement('option');
            opt.value = String(t.codigo);
            opt.textContent = `#${t.codigo} - ${t.cliente} | ${t.assunto.slice(0, 45)} (${t.status})`;
            opt.dataset.client = t.cliente;
            opt.dataset.tech = t.tecnico;
            opt.dataset.subject = t.assunto;
            ticketSelect.appendChild(opt);
        });

        if (forceRefresh) {
            await loadClients(true);
            showToast(`${state.milvusTickets.length} chamados e ${state.clients.length} clientes sincronizados`, 'success');
        }
    } catch (e) {
        console.warn('Falha ao consultar chamados Milvus:', e);
    }
}

function onMilvusTicketSelected() {
    const ticketSelect = document.getElementById('ticket-select');
    const selectedCode = ticketSelect?.value;
    if (!selectedCode) return;

    const ticket = state.milvusTickets.find(t => String(t.codigo) === String(selectedCode));
    if (!ticket) return;

    // 1. Tenta selecionar o cliente correspondente na lista
    const clientSelect = document.getElementById('client-select');
    if (clientSelect && ticket.cliente) {
        const targetName = ticket.cliente.trim().toLowerCase();
        for (let i = 0; i < clientSelect.options.length; i++) {
            const opt = clientSelect.options[i];
            const optText = opt.textContent.trim().toLowerCase();
            if (optText === targetName || optText.includes(targetName) || targetName.includes(optText)) {
                clientSelect.selectedIndex = i;
                break;
            }
        }
    }

    // 2. Preenche o técnico se informado
    const techInput = document.getElementById('tech-name');
    if (techInput && ticket.tecnico && ticket.tecnico !== 'Sem técnico') {
        techInput.value = ticket.tecnico;
    }

    showToast(`Chamado #${ticket.codigo} vinculado: ${ticket.cliente}`, 'info');
}

// ==========================================================================
// Network Scanner & Device Grid
// ==========================================================================
async function scanBenchNetwork() {
    const grid = document.getElementById('bench-grid');
    const scanBtn = document.getElementById('btn-scan');
    
    if (scanBtn) {
        scanBtn.disabled = true;
        scanBtn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> <span>Varrendo...</span>';
        refreshIcons();
    }
    state.isScanning = true;

    try {
        const res = await fetch('/api/v1/bench/scan?timeout=0.3');
        const data = await res.json();
        state.discoveredDevices = data.devices || [];
        renderBenchGrid(state.discoveredDevices);
        showToast(`Varredura concluída: ${state.discoveredDevices.length} dispositivo(s) encontrado(s)`, 'info');
    } catch (e) {
        showToast('Falha ao executar varredura de rede', 'error');
    } finally {
        state.isScanning = false;
        if (scanBtn) {
            scanBtn.disabled = false;
            scanBtn.innerHTML = '<i data-lucide="refresh-cw"></i> <span>Varrer Rede</span>';
            refreshIcons();
        }
    }
}

function renderBenchGrid(devices) {
    const grid = document.getElementById('bench-grid');
    if (!grid) return;

    if (devices.length === 0) {
        grid.innerHTML = `
            <div class="empty-state-box">
                <i data-lucide="hard-drive" style="width: 32px; height: 32px; margin-bottom: 0.5rem; color: var(--text-muted);"></i>
                <p style="font-weight: 600; color: var(--text-secondary);">Nenhum computador ativo detectado</p>
                <p style="font-size: 0.775rem; color: var(--text-muted); margin-top: 0.25rem;">Verifique os cabos de rede e se as máquinas estão ligadas na faixa 192.168.57.0/24.</p>
            </div>
        `;
        refreshIcons();
        return;
    }

    grid.innerHTML = devices.map(d => `
        <div class="device-card">
            <div>
                <div class="device-card-header">
                    <div>
                        <div class="device-hostname">
                            <span>${d.hostname || 'Host Desconhecido'}</span>
                            ${d.vendor && d.vendor !== 'Desconhecido' && d.vendor !== 'Genérico' ? `<span class="badge-oem" title="Fabricante OEM via MAC">${d.vendor}</span>` : ''}
                        </div>
                        <div class="device-ip">${d.ip}</div>
                        <div class="device-meta-tag">
                            <i data-lucide="map-pin" style="width: 12px; height: 12px;"></i>
                            <span>${d.bench_name || 'Bancada'} ${d.switch_port !== 'N/A' ? `(Porta ${d.switch_port})` : ''}</span>
                        </div>
                    </div>
                    <span class="badge-pill ${d.winrm_ready ? 'ready' : 'waiting'}">
                        ${d.winrm_ready ? 'WinRM Pronto' : 'Sem WinRM'}
                    </span>
                </div>
                <div class="device-card-body" style="margin-top: 0.85rem;">
                    <div class="device-info-row">
                        <span>Portas</span>
                        <span>${d.open_ports.join(', ')}</span>
                    </div>
                    <div class="device-info-row">
                        <span>Estado</span>
                        <span>${d.winrm_ready ? 'Pronto para Automação' : 'Inicializando'}</span>
                    </div>
                    ${d.mac ? `
                    <div class="device-info-row">
                        <span>MAC / OUI</span>
                        <span class="mono" style="font-size: 0.72rem;">${d.mac}</span>
                    </div>
                    ` : ''}
                </div>
            </div>

            <!-- Primary Actions -->
            <div class="device-primary-actions">
                <button class="btn btn-outline-blue btn-sm" onclick="runInstantDiagnosis('${d.ip}')">
                    <i data-lucide="activity"></i> Diagnóstico
                </button>
                <button class="btn btn-primary btn-sm" onclick="prepareMachine('${d.ip}')" ${!d.winrm_ready ? 'disabled' : ''}>
                    <i data-lucide="play"></i> Preparar
                </button>
            </div>

            <!-- Quick Bench Actions Grid -->
            <div class="device-quick-actions-grid">
                <button class="btn btn-secondary btn-sm" onclick="openBackupModal('${d.ip}', '${d.hostname || ''}')" ${!d.winrm_ready ? 'disabled' : ''} title="Backup de perfil para o Storage">
                    <i data-lucide="hard-drive"></i> Backup
                </button>
                <button class="btn btn-secondary btn-sm" onclick="openSoftwareModal('${d.ip}')" ${!d.winrm_ready ? 'disabled' : ''} title="Instalar pacotes avulsos">
                    <i data-lucide="box"></i> Softwares
                </button>
                <button class="btn btn-secondary btn-sm" onclick="openDomainModal('${d.ip}')" ${!d.winrm_ready ? 'disabled' : ''} title="Ingressar em domínio AD">
                    <i data-lucide="shield"></i> Domínio
                </button>
                <button class="btn btn-secondary btn-sm" onclick="confirmActivation('${d.ip}')" ${!d.winrm_ready ? 'disabled' : ''} title="Ativação permanente de Windows/Office">
                    <i data-lucide="key"></i> Ativar
                </button>
                <button class="btn btn-secondary btn-sm" onclick="openRenameModal('${d.ip}', '${d.hostname || ''}')" ${!d.winrm_ready ? 'disabled' : ''} title="Alterar nome do computador">
                    <i data-lucide="tag"></i> Renomear
                </button>
                <button class="btn btn-secondary btn-sm" onclick="openDeviceQrModal('${d.ip}', '${d.hostname || ''}', '${d.mac || ''}')" title="Gerar QR Code para celular">
                    <i data-lucide="qr-code"></i> QR
                </button>
                <button class="btn btn-outline-red btn-sm" onclick="confirmPowerAction('${d.ip}', 'restart')" ${!d.winrm_ready ? 'disabled' : ''} title="Reiniciar computador">
                    <i data-lucide="rotate-cw"></i> Reiniciar
                </button>
            </div>
        </div>
    `).join('');

    refreshIcons();
}

// ==========================================================================
// Instant Diagnostic
// ==========================================================================
async function runInstantDiagnosis(ip) {
    showModal(`Diagnóstico de Hardware: ${ip}`, `
        <div style="text-align: center; padding: 2rem;">
            <i data-lucide="loader-2" class="spin-icon" style="width: 32px; height: 32px; margin-bottom: 1rem;"></i>
            <p style="font-weight: 600; color: var(--text-primary);">Inspecionando máquina ${ip} via WinRM...</p>
            <p style="color: var(--text-muted); font-size: 0.8rem; margin-top: 0.35rem;">Coletando telemetria S.M.A.R.T, CPU, memória e eventos de sistema.</p>
        </div>
    `);

    try {
        const res = await fetch('/api/v1/bench/diagnose', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip })
        });
        const data = await res.json();
        
        const telemetry = data.telemetry || {};
        const aiText = (data.ai_diagnosis || '').replace(/\n/g, '<br/>');

        const content = `
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                <div style="background: var(--bg-input); padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
                    <h4 style="color: var(--brand-accent); font-size: 0.85rem; font-weight: 700; margin-bottom: 0.5rem;">Inventário de Hardware</h4>
                    <p style="font-size: 0.8rem; line-height: 1.6;"><b>Host:</b> ${telemetry.computer_name || 'N/A'} | <b>Serial:</b> ${telemetry.serial_number || 'N/A'}</p>
                    <p style="font-size: 0.8rem; line-height: 1.6;"><b>Processador:</b> ${telemetry.cpu || 'N/A'}</p>
                    <p style="font-size: 0.8rem; line-height: 1.6;"><b>Memória RAM:</b> ${telemetry.ram_gb || 'N/A'} GB</p>
                    <p style="font-size: 0.8rem; line-height: 1.6;"><b>Discos:</b> ${(telemetry.disks || []).map(d => `${d.model} (${d.size_gb}GB - ${d.health})`).join(', ') || 'Nenhum'}</p>
                </div>

                <div style="background: rgba(37, 99, 235, 0.08); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-active);">
                    <h4 style="color: var(--brand-accent); font-size: 0.85rem; font-weight: 700; margin-bottom: 0.6rem;">Parecer Técnico</h4>
                    <div style="font-size: 0.825rem; line-height: 1.6; color: #CBD5E1;">
                        ${aiText || '<i>Sem informações adicionais.</i>'}
                    </div>
                </div>
            </div>
        `;
        showModal(`Diagnóstico: ${ip}`, content);
    } catch (e) {
        showModal('Erro no Diagnóstico', `<p style="color: var(--status-red)">Falha ao coletar diagnóstico: ${e.message}</p>`);
    }
}

// ==========================================================================
// Quick Bench Actions (Modals & Executions)
// ==========================================================================

// 1. User Profile Backup
function openBackupModal(ip, hostname) {
    const clientOptions = state.clients.map(c => `<option value="${c.nome}">${c.nome}</option>`).join('');
    const ticketOptions = (state.milvusTickets || []).map(t => `<option value="${t.codigo}" data-client="${t.cliente}">#${t.codigo} - ${t.cliente} (${t.assunto.slice(0, 35)}...)</option>`).join('');

    const content = `
        <form onsubmit="submitBackupAction(event, '${ip}')" class="form-stack">
            <p style="color: var(--text-muted); font-size: 0.825rem;">
                Copia os perfis de usuário em <code>C:\\Users\\*</code> via Robocopy para o Storage Macrium <b>(192.168.57.112\\Backups)</b>.
            </p>
            ${ticketOptions ? `
            <div class="form-field">
                <label>Chamado Milvus (Preenchimento Automático)</label>
                <select id="backup-ticket-select" class="form-select" onchange="onBackupTicketSelected()">
                    <option value="">-- Selecione o chamado --</option>
                    ${ticketOptions}
                </select>
            </div>` : ''}
            <div class="form-field">
                <label>Cliente / Pasta de Destino</label>
                <select id="backup-client" class="form-select" required>
                    ${clientOptions || '<option value="CLIENTE_GERAL">Cliente Pense Rede</option>'}
                </select>
            </div>
            <div class="form-field">
                <label>Número do Chamado / Ticket</label>
                <input type="text" id="backup-ticket" class="form-input" placeholder="Ex: 10938" required>
            </div>
            <div class="form-field">
                <label>Unidade de Origem</label>
                <input type="text" id="backup-drive" class="form-input" value="C:" required>
            </div>
            <div style="display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1.25rem;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancelar</button>
                <button type="submit" id="btn-submit-backup" class="btn btn-primary">Iniciar Backup</button>
            </div>
        </form>
    `;
    showModal(`Backup de Usuário: ${hostname || ip}`, content);
}

function onBackupTicketSelected() {
    const sel = document.getElementById('backup-ticket-select');
    const ticketInput = document.getElementById('backup-ticket');
    const clientSelect = document.getElementById('backup-client');
    if (!sel || !sel.value) return;

    if (ticketInput) ticketInput.value = sel.value;

    const opt = sel.options[sel.selectedIndex];
    const clientName = opt?.dataset?.client?.trim().toLowerCase();
    if (clientName && clientSelect) {
        for (let i = 0; i < clientSelect.options.length; i++) {
            const val = clientSelect.options[i].value.toLowerCase();
            if (val === clientName || val.includes(clientName) || clientName.includes(val)) {
                clientSelect.selectedIndex = i;
                break;
            }
        }
    }
}

async function submitBackupAction(e, ip) {
    e.preventDefault();
    const clientName = document.getElementById('backup-client').value;
    const ticketNumber = document.getElementById('backup-ticket').value.trim();
    const sourceDrive = document.getElementById('backup-drive').value.trim();
    const btn = document.getElementById('btn-submit-backup');

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> <span>Copiando arquivos...</span>';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/bench/action/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ip: ip,
                client_name: clientName,
                ticket_number: ticketNumber,
                source_drive: sourceDrive
            })
        });
        const data = await res.json();
        if (data.success) {
            showModal(`Backup Concluído: ${ip}`, `
                <div style="padding: 1rem; background: var(--status-green-bg); border: 1px solid var(--status-green-border); border-radius: var(--radius-md);">
                    <h4 style="color: var(--status-green); font-size: 0.9rem; font-weight: 700; margin-bottom: 0.35rem;">Backup concluído com sucesso</h4>
                    <p style="font-size: 0.8rem; color: var(--text-secondary);">Destino: <code>\\\\${data.backup_server}\\Backups\\${clientName} - ${ticketNumber}</code></p>
                </div>
            `);
            showToast('Backup concluído com sucesso', 'success');
        } else {
            showToast(`Falha no backup: ${data.stderr || 'Erro de execução'}`, 'error');
        }
    } catch (err) {
        showToast(`Erro de comunicação: ${err.message}`, 'error');
    }
}

// 2. Rename Computer
function openRenameModal(ip, currentName) {
    const content = `
        <form onsubmit="submitRenameAction(event, '${ip}')" class="form-stack">
            <div class="form-field">
                <label>Hostname Atual</label>
                <input type="text" class="form-input" value="${currentName || 'DESCONHECIDO'}" disabled>
            </div>
            <div class="form-field">
                <label>Novo Nome do Computador</label>
                <input type="text" id="rename-new-name" class="form-input" placeholder="Ex: LAB-PC-01" required>
            </div>
            <label class="custom-checkbox">
                <input type="checkbox" id="rename-restart" checked>
                <span class="checkbox-text">Reiniciar o computador agora para aplicar a alteração</span>
            </label>
            <div style="display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1.25rem;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancelar</button>
                <button type="submit" id="btn-submit-rename" class="btn btn-primary">Renomear</button>
            </div>
        </form>
    `;
    showModal(`Renomear Host: ${ip}`, content);
}

async function submitRenameAction(e, ip) {
    e.preventDefault();
    const newName = document.getElementById('rename-new-name').value.trim();
    const restart = document.getElementById('rename-restart').checked;
    const btn = document.getElementById('btn-submit-rename');

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> <span>Aplicando...</span>';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/bench/action/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip, new_name: newName, restart })
        });
        const data = await res.json();
        if (data.success) {
            closeModal();
            showToast(`Hostname alterado para ${newName}`, 'success');
            setTimeout(scanBenchNetwork, 2000);
        } else {
            showToast(`Falha ao renomear: ${data.stderr || 'Erro'}`, 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = 'Renomear'; }
        }
    } catch (err) {
        showToast(`Erro de comunicação: ${err.message}`, 'error');
        if (btn) { btn.disabled = false; btn.innerHTML = 'Renomear'; }
    }
}

// 3. MAS Activation
function confirmActivation(ip) {
    const content = `
        <div>
            <p style="color: var(--text-secondary); font-size: 0.85rem; line-height: 1.6; margin-bottom: 1.25rem;">
                Executar ativação permanente <b>Massgrave (MAS)</b> na máquina <code>${ip}</code>?<br>
                Aplica licença digital HWID para Windows e Ohook para Microsoft Office.
            </p>
            <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancelar</button>
                <button type="button" id="btn-submit-activation" class="btn btn-primary" onclick="submitActivationAction('${ip}')">
                    Executar Ativação
                </button>
            </div>
        </div>
    `;
    showModal(`Ativação de Licença: ${ip}`, content);
}

async function submitActivationAction(ip) {
    const btn = document.getElementById('btn-submit-activation');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> <span>Ativando...</span>';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/bench/action/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip })
        });
        const data = await res.json();
        closeModal();
        if (data.success) {
            showToast('Processo de ativação concluído', 'success');
        } else {
            showToast(`Alerta na ativação: ${data.stderr || 'Verifique conexão'}`, 'warning');
        }
    } catch (err) {
        showToast(`Erro ao ativar: ${err.message}`, 'error');
    }
}

// 4. Install Standalone Packages
function openSoftwareModal(ip) {
    const popularPackages = [
        { id: 'AnyDeskSoftwareGmbH.AnyDesk', name: 'AnyDesk' },
        { id: 'Google.Chrome', name: 'Google Chrome' },
        { id: 'Mozilla.Firefox', name: 'Mozilla Firefox' },
        { id: 'Microsoft.Office', name: 'Microsoft Office 365' },
        { id: 'Microsoft.VisualStudioCode', name: 'Visual Studio Code' },
        { id: '7zip.7zip', name: '7-Zip' },
        { id: 'Notepad++.Notepad++', name: 'Notepad++' },
        { id: 'Adobe.Acrobat.Reader.64-bit', name: 'Adobe Acrobat Reader' }
    ];

    const packageItemsHtml = popularPackages.map(p => `
        <label class="package-choice-card">
            <input type="checkbox" name="pkg-checkbox" value="${p.id}">
            <div>
                <div class="package-choice-title">${p.name}</div>
                <div class="package-choice-id">${p.id}</div>
            </div>
        </label>
    `).join('');

    const content = `
        <form onsubmit="submitInstallSoftwareAction(event, '${ip}')" class="form-stack">
            <p style="color: var(--text-muted); font-size: 0.8rem;">
                Selecione os pacotes para instalação silenciosa via Winget em <b>${ip}</b>:
            </p>
            <div class="package-selection-grid">
                ${packageItemsHtml}
            </div>
            <div class="form-field">
                <label>Outro ID de Pacote Winget (Opcional)</label>
                <input type="text" id="custom-pkg-id" class="form-input" placeholder="Ex: Git.Git">
            </div>
            <div style="display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1.25rem;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancelar</button>
                <button type="submit" id="btn-submit-software" class="btn btn-primary">Instalar Selecionados</button>
            </div>
        </form>
    `;
    showModal(`Instalação de Pacotes: ${ip}`, content);
}

async function submitInstallSoftwareAction(e, ip) {
    e.preventDefault();
    const checkboxes = document.querySelectorAll('input[name="pkg-checkbox"]:checked');
    const customPkg = document.getElementById('custom-pkg-id').value.trim();
    const btn = document.getElementById('btn-submit-software');

    const selectedPackages = Array.from(checkboxes).map(cb => cb.value);
    if (customPkg) {
        selectedPackages.push(customPkg);
    }

    if (selectedPackages.length === 0) {
        showToast('Selecione pelo menos um pacote para instalar', 'warning');
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="spin-icon"></i> <span>Instalando ${selectedPackages.length} pacote(s)...</span>`;
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/bench/action/install-software', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip, packages: selectedPackages })
        });
        const data = await res.json();
        closeModal();
        if (data.success) {
            showToast(`${data.installed.length} software(s) instalados com sucesso`, 'success');
        } else {
            showToast(`Concluído com alertas: ${data.errors.length} erro(s)`, 'warning');
        }
    } catch (err) {
        showToast(`Erro na instalação: ${err.message}`, 'error');
    }
}

// 5. Remote Reboot / Shutdown
function confirmPowerAction(ip, action) {
    const isShutdown = (action === 'shutdown');
    const actionLabel = isShutdown ? 'Desligar' : 'Reiniciar';

    const content = `
        <div>
            <p style="color: var(--text-secondary); font-size: 0.85rem; line-height: 1.6; margin-bottom: 1.25rem;">
                Confirma a ordem de <b>${actionLabel.toLowerCase()}</b> forçadamente o computador <code>${ip}</code>?
            </p>
            <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancelar</button>
                <button type="button" id="btn-submit-power" class="btn btn-outline-red" onclick="submitPowerAction('${ip}', '${action}')">
                    Confirmar ${actionLabel}
                </button>
            </div>
        </div>
    `;
    showModal(`${actionLabel} Máquina: ${ip}`, content);
}

async function submitPowerAction(ip, action) {
    const btn = document.getElementById('btn-submit-power');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> <span>Enviando...</span>';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/bench/action/power', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip, action })
        });
        const data = await res.json();
        closeModal();
        if (data.success) {
            showToast(data.message, 'success');
            setTimeout(scanBenchNetwork, 3000);
        } else {
            showToast(`Falha no comando: ${data.stderr || 'Erro de execução'}`, 'error');
        }
    } catch (err) {
        showToast(`Erro de comunicação: ${err.message}`, 'error');
    }
}

// 6. Dynamic Domain Join Action
function openDomainModal(ip) {
    const content = `
        <form onsubmit="submitDomainJoinAction(event, '${ip}')" class="form-stack">
            <p style="color: var(--text-muted); font-size: 0.8rem;">
                Insira as credenciais do Active Directory para ingressar a máquina <b>${ip}</b> no domínio:
            </p>
            <div class="form-field">
                <label>Nome do Domínio (AD)</label>
                <input type="text" id="modal-dom-name" class="form-input" placeholder="cliente.local" required>
            </div>
            <div class="grid-2-col">
                <div class="form-field">
                    <label>DNS / IP do Servidor</label>
                    <input type="text" id="modal-dom-dns" class="form-input" placeholder="192.168.1.10" required>
                </div>
                <div class="form-field">
                    <label>IP Estático (Opcional)</label>
                    <input type="text" id="modal-dom-static-ip" class="form-input" placeholder="192.168.1.150">
                </div>
            </div>
            <div class="grid-2-col">
                <div class="form-field">
                    <label>Usuário Administrador</label>
                    <input type="text" id="modal-dom-user" class="form-input" placeholder="admin.suporte" required>
                </div>
                <div class="form-field">
                    <label>Senha do AD</label>
                    <input type="password" id="modal-dom-pass" class="form-input" placeholder="••••••••" required>
                </div>
            </div>
            <div class="form-field">
                <label>Unidade Organizacional (OU Path - Opcional)</label>
                <input type="text" id="modal-dom-ou" class="form-input" placeholder="OU=Computadores,DC=dominio,DC=local">
            </div>
            <div style="display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1.25rem;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancelar</button>
                <button type="submit" id="btn-submit-domain" class="btn btn-primary">Ingressar no Domínio</button>
            </div>
        </form>
    `;
    showModal(`Ingresso em Domínio: ${ip}`, content);
}

async function submitDomainJoinAction(e, ip) {
    e.preventDefault();
    const domainName = document.getElementById('modal-dom-name').value.trim();
    const dnsServer = document.getElementById('modal-dom-dns').value.trim();
    const staticIp = document.getElementById('modal-dom-static-ip').value.trim();
    const domainUser = document.getElementById('modal-dom-user').value.trim();
    const domainPassword = document.getElementById('modal-dom-pass').value;
    const ouPath = document.getElementById('modal-dom-ou').value.trim();
    const btn = document.getElementById('btn-submit-domain');

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> <span>Ingressando...</span>';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/bench/action/domain-join', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ip: ip,
                domain_name: domainName,
                dns_server: dnsServer,
                static_ip: staticIp,
                domain_user: domainUser,
                domain_password: domainPassword,
                ou_path: ouPath
            })
        });
        const data = await res.json();
        closeModal();
        if (data.success) {
            showToast(`Máquina ingressada no domínio ${domainName}`, 'success');
        } else {
            showToast(`Falha no ingresso: ${data.stderr || 'Verifique credenciais e DNS'}`, 'error');
        }
    } catch (err) {
        showToast(`Erro de comunicação: ${err.message}`, 'error');
    }
}

function toggleDomainInputs() {
    const chk = document.getElementById('check-domain');
    const container = document.getElementById('domain-inputs-container');
    if (chk && container) {
        if (chk.checked) {
            container.classList.remove('hidden');
            const currentClientId = document.getElementById('client-select')?.value;
            const client = state.clients.find(c => c.id === currentClientId);
            if (client && client.dominio && !document.getElementById('dom-name').value) {
                document.getElementById('dom-name').value = client.dominio;
            }
        } else {
            container.classList.add('hidden');
        }
    }
}

// ==========================================================================
// Pipeline Execution & WebSocket Realtime Streamer
// ==========================================================================
let activePipelineSocket = null;
let currentAnyDeskId = "";

function prepareMachine(ip) {
    switchTab('pipeline');
    const ipInput = document.getElementById('target-ip');
    if (ipInput) ipInput.value = ip;
}

function updateWsStatus(status) {
    const dot = document.getElementById('ws-status-dot');
    const text = document.getElementById('ws-status-text');
    if (!dot || !text) return;

    if (status === 'online') {
        dot.className = 'status-indicator online';
        text.textContent = 'ONLINE';
        text.style.color = 'var(--status-green)';
    } else if (status === 'connecting') {
        dot.className = 'status-indicator';
        text.textContent = 'CONECTANDO';
        text.style.color = 'var(--status-amber)';
    } else {
        dot.className = 'status-indicator offline';
        text.textContent = 'OFFLINE';
        text.style.color = 'var(--status-red)';
    }
}

function setStageProgress(stageNum, totalStages, stageName) {
    const fill = document.getElementById('stage-progress-bar');
    const nameEl = document.getElementById('stage-name-text');
    const pctEl = document.getElementById('stage-percent-text');
    if (!fill || !nameEl || !pctEl) return;

    if (!stageNum) return;
    const pct = Math.min(100, Math.round((stageNum / (totalStages || 7)) * 100));
    fill.style.width = `${pct}%`;
    pctEl.textContent = `${pct}%`;
    if (stageName) {
        nameEl.textContent = `[Etapa ${stageNum}/${totalStages || 7}] ${stageName}`;
    }
}

function showAnyDeskId(anydeskId) {
    currentAnyDeskId = anydeskId;
    const card = document.getElementById('anydesk-live-card');
    const valEl = document.getElementById('anydesk-id-val');
    if (card && valEl) {
        valEl.textContent = anydeskId;
        card.classList.remove('hidden');
        refreshIcons();
    }
}

function copyAnyDeskId() {
    if (!currentAnyDeskId || currentAnyDeskId === "--- --- ---") {
        showToast('Nenhum AnyDesk ID disponível para cópia', 'warning');
        return;
    }
    navigator.clipboard.writeText(currentAnyDeskId).then(() => {
        showToast(`AnyDesk ID (${currentAnyDeskId}) copiado!`, 'success');
    }).catch(() => {
        showToast(`ID: ${currentAnyDeskId}`, 'info');
    });
}

function toggleSoftwareSelector() {
    const chk = document.getElementById('check-custom-softwares');
    const container = document.getElementById('software-selector-container');
    if (chk && container) {
        if (chk.checked) {
            container.classList.remove('hidden');
        } else {
            container.classList.add('hidden');
        }
    }
}

async function startPipelineExecution(e) {
    if (e) e.preventDefault();
    
    const ip = document.getElementById('target-ip').value.trim();
    const clientId = document.getElementById('client-select').value;
    const techName = document.getElementById('tech-name').value.trim() || 'Nicolas Silva';
    const skipBurnin = !document.getElementById('check-burnin').checked;
    const terminal = document.getElementById('terminal-logs');
    const submitBtn = document.getElementById('btn-run-pipeline');
    const anydeskCard = document.getElementById('anydesk-live-card');

    if (!ip) {
        showToast('Informe o endereço IP do computador de bancada', 'error');
        return;
    }

    // Coleta softwares selecionados se o checkbox estiver ativo
    let customPackages = [];
    const checkCustomSoftwares = document.getElementById('check-custom-softwares');
    if (checkCustomSoftwares && checkCustomSoftwares.checked) {
        const checkedPkgs = document.querySelectorAll('input[name="pkg-select"]:checked');
        checkedPkgs.forEach(cb => {
            if (cb.value) customPackages.push(cb.value.trim());
        });
        const extraInput = document.getElementById('custom-extra-pkgs')?.value.trim();
        if (extraInput) {
            extraInput.split(',').forEach(p => {
                const clean = p.trim();
                if (clean && !customPackages.includes(clean)) customPackages.push(clean);
            });
        }
    }

    // Dynamic Domain Configuration
    let domainConfig = null;
    const checkDomain = document.getElementById('check-domain');
    if (checkDomain && checkDomain.checked) {
        const dName = document.getElementById('dom-name')?.value.trim();
        const dDns = document.getElementById('dom-dns')?.value.trim();
        const dStaticIp = document.getElementById('dom-static-ip')?.value.trim();
        const dUser = document.getElementById('dom-user')?.value.trim();
        const dPass = document.getElementById('dom-pass')?.value || '';
        const dOu = document.getElementById('dom-ou')?.value.trim();

        if (!dName || !dUser || !dPass) {
            showToast('Preencha os campos obrigatórios do domínio (Nome, Usuário e Senha)', 'warning');
            return;
        }

        domainConfig = {
            ip: ip,
            domain_name: dName,
            dns_server: dDns,
            static_ip: dStaticIp,
            domain_user: dUser,
            domain_password: dPass,
            ou_path: dOu
        };
    }

    // Reset UI State
    state.isRunningPipeline = true;
    currentAnyDeskId = "";
    if (anydeskCard) anydeskCard.classList.add('hidden');
    terminal.innerHTML = '';
    setStageProgress(1, 7, 'Conectando ao orquestrador...');
    updateWsStatus('connecting');

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> <span>Executando Esteira...</span>';
        refreshIcons();
    }

    // Close previous websocket
    if (activePipelineSocket) {
        try { activePipelineSocket.close(); } catch (err) {}
    }

    // Establish WebSocket connection
    const sessionId = `ws_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/pipeline/${sessionId}`;

    appendLog(`[${new Date().toLocaleTimeString()}] Conectando ao canal WebSocket...`, 'info');

    try {
        activePipelineSocket = new WebSocket(wsUrl);

        activePipelineSocket.onopen = async () => {
            updateWsStatus('online');
            appendLog(`[${new Date().toLocaleTimeString()}] Canal estabelecido. Disparando esteira...`, 'success');

            try {
                const res = await fetch('/api/v1/bench/run?async_mode=true', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ip: ip,
                        client_id: clientId,
                        technician_name: techName,
                        tech_user_id: 'nicolas',
                        skip_burnin: skipBurnin,
                        custom_packages: customPackages,
                        session_id: sessionId,
                        domain_config: domainConfig
                    })
                });

                if (!res.ok) {
                    const errData = await res.json();
                    appendLog(`Erro ao iniciar esteira: ${errData.detail || 'Falha no servidor'}`, 'error');
                    finalizePipeline(false);
                }
            } catch (err) {
                appendLog(`Falha ao contactar servidor: ${err.message}`, 'error');
                finalizePipeline(false);
            }
        };

        activePipelineSocket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                
                if (data.type === 'log') {
                    appendLog(data.message, data.level || 'info');
                    if (data.stage) {
                        setStageProgress(data.stage, data.total_stages || 7, data.stage_name);
                    }
                } else if (data.type === 'stage_progress') {
                    setStageProgress(data.stage, data.total_stages, data.stage_name);
                } else if (data.type === 'anydesk_detected') {
                    showAnyDeskId(data.anydesk_id);
                    appendLog(`[AnyDesk] ID Capturado: ${data.anydesk_id}`, 'success');
                } else if (data.type === 'finished') {
                    finalizePipeline(data.success);
                    if (data.success) {
                        setStageProgress(7, 7, 'Esteira Concluída com Sucesso');
                        showToast('Esteira de preparação finalizada com sucesso!', 'success');
                    } else {
                        showToast('Esteira finalizada com alertas.', 'warning');
                    }
                } else if (data.type === 'error') {
                    appendLog(`Erro no processo: ${data.error}`, 'error');
                    finalizePipeline(false);
                }
            } catch (e) {
                appendLog(event.data, 'info');
            }
        };

        activePipelineSocket.onerror = () => {
            updateWsStatus('offline');
            appendLog('Falha no canal de streaming WebSocket.', 'error');
        };

        activePipelineSocket.onclose = () => {
            updateWsStatus('offline');
        };

    } catch (err) {
        showToast(`Erro ao conectar WebSocket: ${err.message}`, 'error');
        finalizePipeline(false);
    }
}

function finalizePipeline(success) {
    state.isRunningPipeline = false;
    const submitBtn = document.getElementById('btn-run-pipeline');
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i data-lucide="play"></i> <span>Iniciar Esteira</span>';
        refreshIcons();
    }
    loadReports();
}

function appendLog(text, type = 'info') {
    const terminal = document.getElementById('terminal-logs');
    if (!terminal) return;

    const div = document.createElement('div');
    div.className = `log-row ${type}`;
    div.textContent = text;
    terminal.appendChild(div);
    terminal.scrollTop = terminal.scrollHeight;
}

// ==========================================================================
// Reports Center
// ==========================================================================
async function loadReports() {
    const tbody = document.getElementById('reports-tbody');
    if (!tbody) return;

    try {
        const res = await fetch('/api/v1/reports/list');
        const data = await res.json();
        state.reports = data.reports || [];

        if (state.reports.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 3rem 1rem;">
                        Nenhum laudo emitido até o momento.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = state.reports.map(r => `
            <tr>
                <td>
                    <div style="display: flex; align-items: center; gap: 0.6rem;">
                        <i data-lucide="file-text" style="color: var(--brand-accent); width: 18px; height: 18px;"></i>
                        <span style="font-weight: 600;">${r.filename}</span>
                    </div>
                </td>
                <td style="font-family: var(--font-mono); color: var(--text-secondary);">${r.size_kb} KB</td>
                <td style="color: var(--text-muted);">${new Date(r.created_at * 1000).toLocaleString('pt-BR')}</td>
                <td style="text-align: right;">
                    <a href="/api/v1/reports/download/${r.filename}" class="btn btn-secondary btn-sm" download>
                        <i data-lucide="download"></i> Download
                    </a>
                </td>
            </tr>
        `).join('');

        refreshIcons();
    } catch (e) {
        showToast('Erro ao carregar laudos técnicos', 'error');
    }
}

// ==========================================================================
// Infrastructure Status Monitor
// ==========================================================================
async function checkInfraStatus() {
    try {
        const res = await fetch('/api/v1/infra/status');
        const data = await res.json();
        
        updateStatusDot('status-ultron', data.ultron);
        updateStatusDot('status-mdt', data.mdt_server);
        updateStatusDot('status-macrium', data.backup_storage);
        updateStatusDot('status-milvus', data.milvus_dashboard);
        updateStatusDot('status-trueconf', data.trueconf);
    } catch (e) {
        updateStatusDot('status-ultron', false);
        updateStatusDot('status-milvus', false);
        updateStatusDot('status-trueconf', false);
    }
}

function updateStatusDot(elementId, isOnline) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.className = `status-indicator ${isOnline ? 'online' : 'offline'}`;
}

async function testTrueConfPrompt() {
    const defaultUser = document.getElementById('tech-name')?.value || 'nicolas';
    showModal('Notificação TrueConf Bot', `
        <form onsubmit="sendTrueConfTestMessage(event)" class="form-stack">
            <p class="text-sm text-secondary mb-2">
                O TrueConf Bot envia alertas em <strong>Mensagem Direta (Privado 1-on-1)</strong> para o técnico quando uma máquina termina o MDT ou conclui a esteira com o AnyDesk ID e o Laudo PDF.
            </p>
            <div class="form-field">
                <label>ID do Usuário Técnico no TrueConf</label>
                <input type="text" id="tc-test-user" class="form-input mono" value="nicolas" required>
                <span class="field-hint">Seu identificador de usuário no servidor TrueConf (ex: <code>nicolas</code>).</span>
            </div>
            <div class="form-field">
                <label>Mensagem de Teste</label>
                <textarea id="tc-test-msg" class="form-input" rows="3">🤖 [Ultron] Teste de Notificação Direta: O bot de bancada está ativo e sincronizado com o Dashboard!</textarea>
            </div>
            <div class="form-actions-split mt-3">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancelar</button>
                <button type="submit" id="btn-send-tc" class="btn btn-primary">
                    <i data-lucide="send"></i> Enviar Mensagem Direta
                </button>
            </div>
        </form>
    `);
    refreshIcons();
}

async function sendTrueConfTestMessage(event) {
    event.preventDefault();
    const userId = document.getElementById('tc-test-user')?.value.trim() || 'nicolas';
    const message = document.getElementById('tc-test-msg')?.value.trim();
    const btn = document.getElementById('btn-send-tc');

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> Enviando...';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/trueconf/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, message: message })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            closeModal();
        } else {
            showToast(data.message, 'warning');
        }
    } catch (e) {
        showToast(`Erro ao testar TrueConf: ${e.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="send"></i> Enviar Mensagem Direta';
            refreshIcons();
        }
    }
}

// ==========================================================================
// Modal & Toasts
// ==========================================================================
function showModal(title, bodyHtml) {
    const modal = document.getElementById('main-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    
    if (modal && modalTitle && modalBody) {
        modalTitle.textContent = title;
        modalBody.innerHTML = bodyHtml;
        modal.classList.add('active');
        refreshIcons();
    }
}

function closeModal() {
    const modal = document.getElementById('main-modal');
    if (modal) modal.classList.remove('active');
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast-item ${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}

function copyTextToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showToast('Copiado para a área de transferência!', 'success');
        }).catch(() => {
            showToast('Falha ao copiar texto', 'error');
        });
    } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        showToast('Copiado para a área de transferência!', 'success');
    }
}

// ==========================================================================
// Milvus Connection & Token Center
// ==========================================================================
async function openMilvusModal() {
    const modal = document.getElementById('milvus-modal');
    if (!modal) return;
    modal.classList.add('active');
    refreshIcons();
    await loadMilvusConfig();
    await loadMilvusClientTokens();
}

function closeMilvusModal() {
    const modal = document.getElementById('milvus-modal');
    if (modal) modal.classList.remove('active');
}

function switchMilvusModalTab(subTab) {
    const connBtn = document.getElementById('milvus-tab-conn-btn');
    const tokensBtn = document.getElementById('milvus-tab-tokens-btn');
    const connView = document.getElementById('milvus-view-conn');
    const tokensView = document.getElementById('milvus-view-tokens');

    if (subTab === 'conn') {
        connBtn?.classList.add('active');
        tokensBtn?.classList.remove('active');
        connView?.classList.remove('hidden');
        tokensView?.classList.add('hidden');
    } else {
        tokensBtn?.classList.add('active');
        connBtn?.classList.remove('active');
        tokensView?.classList.remove('hidden');
        connView?.classList.add('hidden');
        loadMilvusClientTokens();
    }
    refreshIcons();
}

async function loadMilvusConfig() {
    try {
        const res = await fetch('/api/v1/milvus/config');
        const data = await res.json();
        state.milvusConfig = data;

        const urlInput = document.getElementById('milvus-cfg-url');
        const tokenInput = document.getElementById('milvus-cfg-token');
        const demoCheckbox = document.getElementById('milvus-cfg-demo');

        if (urlInput) urlInput.value = data.dashboard_url || 'http://192.168.57.7';
        if (tokenInput) tokenInput.value = data.api_token || '';
        if (demoCheckbox) demoCheckbox.checked = !!data.demo_mode;
    } catch (e) {
        showToast('Erro ao carregar configurações do Milvus', 'error');
    }
}

async function saveMilvusConfigForm(event) {
    event.preventDefault();
    const url = document.getElementById('milvus-cfg-url')?.value.trim();
    const token = document.getElementById('milvus-cfg-token')?.value.trim();
    const demoMode = document.getElementById('milvus-cfg-demo')?.checked;

    try {
        const res = await fetch('/api/v1/milvus/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dashboard_url: url,
                api_token: token,
                demo_mode: demoMode
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Configurações do Milvus salvas com sucesso!', 'success');
            await loadMilvusTickets(true);
            await checkInfraStatus();
        } else {
            showToast(data.detail || 'Falha ao salvar configurações', 'error');
        }
    } catch (e) {
        showToast(`Erro ao salvar: ${e.message}`, 'error');
    }
}

async function testMilvusLiveConnection() {
    const testBtn = document.getElementById('btn-test-milvus');
    const resultBox = document.getElementById('milvus-test-card');
    const url = document.getElementById('milvus-cfg-url')?.value.trim();
    const token = document.getElementById('milvus-cfg-token')?.value.trim();

    if (testBtn) {
        testBtn.disabled = true;
        testBtn.innerHTML = '<i data-lucide="loader-2" class="spin-icon"></i> Testando ping...';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/milvus/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                custom_url: url || null,
                custom_token: token || null
            })
        });
        const data = await res.json();
        
        if (resultBox) {
            resultBox.classList.remove('hidden');
            resultBox.className = `diagnostic-feedback-box ${data.online ? 'success' : 'error'}`;
            resultBox.innerHTML = `
                <div class="feedback-header">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="status-indicator ${data.online ? 'online' : 'offline'}"></span>
                        <strong>${data.online ? 'Conexão Estabelecida com Sucesso' : 'Falha na Conexão com a Dashboard'}</strong>
                    </div>
                    <span class="mono text-sm">${data.latency_ms} ms</span>
                </div>
                <p class="feedback-msg text-sm mt-1">${data.message}</p>
                <div class="endpoints-status-grid mt-2">
                    <div class="endpoint-item">
                        <span class="ep-name">Chamados Abertos (/api/chamados-abertos):</span>
                        <span class="ep-badge ${data.endpoints?.chamados_abertos?.status === 'ok' ? 'ok' : 'fail'}">${(data.endpoints?.chamados_abertos?.status || 'N/A').toUpperCase()}</span>
                    </div>
                    <div class="endpoint-item">
                        <span class="ep-name">Chamados Pendentes (/api/chamados-pendentes):</span>
                        <span class="ep-badge ${data.endpoints?.chamados_pendentes?.status === 'ok' ? 'ok' : 'fail'}">${(data.endpoints?.chamados_pendentes?.status || 'N/A').toUpperCase()}</span>
                    </div>
                    <div class="endpoint-item">
                        <span class="ep-name">Empresas & Contatos (/api/contatos):</span>
                        <span class="ep-badge ${data.endpoints?.contatos?.status === 'ok' ? 'ok' : 'fail'}">${(data.endpoints?.contatos?.status || 'N/A').toUpperCase()}</span>
                    </div>
                </div>
            `;
            refreshIcons();
        }
    } catch (e) {
        showToast(`Erro ao testar conexão: ${e.message}`, 'error');
    } finally {
        if (testBtn) {
            testBtn.disabled = false;
            testBtn.innerHTML = '<i data-lucide="wifi"></i> Testar Conectividade Agora';
            refreshIcons();
        }
    }
}

async function loadMilvusClientTokens() {
    const tbody = document.getElementById('milvus-client-tokens-tbody');
    if (!tbody) return;

    try {
        const res = await fetch('/api/v1/milvus/client-tokens');
        const data = await res.json();
        state.milvusClientTokens = data.clients || [];

        if (state.milvusClientTokens.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted p-4">Nenhum cliente cadastrado em clients.yaml.</td></tr>`;
            return;
        }

        tbody.innerHTML = state.milvusClientTokens.map(c => `
            <tr>
                <td>
                    <div style="font-weight: 600;">${c.nome}</div>
                    <span class="mono text-xs text-muted">${c.client_id}</span>
                </td>
                <td>
                    <span class="mono text-sm">${c.dominio || '<span class="text-muted">Sem domínio</span>'}</span>
                </td>
                <td>
                    <div class="inline-edit-group">
                        <input type="text" id="token-input-${c.client_id}" class="form-input mono form-input-sm" value="${c.milvus_token || ''}" placeholder="TOKEN_MILVUS_...">
                    </div>
                </td>
                <td style="text-align: right; white-space: nowrap;">
                    <div style="display: inline-flex; gap: 0.4rem; justify-content: flex-end;">
                        ${c.has_token ? `
                        <a href="/api/v1/milvus/agent/download/${c.client_id}" class="btn btn-secondary btn-sm" title="Baixar instalador MSI para ${c.nome}">
                            <i data-lucide="download"></i> MSI
                        </a>
                        ` : ''}
                        <button type="button" class="btn btn-primary btn-sm" onclick="saveClientMilvusToken('${c.client_id}')" title="Salvar token para ${c.nome}">
                            <i data-lucide="save"></i> Salvar
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');

        refreshIcons();
    } catch (e) {
        showToast('Erro ao carregar tokens de clientes', 'error');
    }
}

async function syncAllMilvusAgents() {
    try {
        showToast('Iniciando sincronização de todos os instaladores MSI...', 'info');
        const res = await fetch('/api/v1/milvus/agent/sync-all', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
        } else {
            showToast(data.error || 'Erro ao sincronizar MSIs', 'error');
        }
    } catch (e) {
        showToast(`Erro ao sincronizar: ${e.message}`, 'error');
    }
}


async function saveClientMilvusToken(clientId) {
    const input = document.getElementById(`token-input-${clientId}`);
    const tokenVal = input ? input.value.trim() : '';

    try {
        const res = await fetch('/api/v1/milvus/client-tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                client_id: clientId,
                milvus_token: tokenVal
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Token de ${clientId} salvo com sucesso!`, 'success');
            await loadClients(true);
        } else {
            showToast(data.detail || 'Erro ao atualizar token', 'error');
        }
    } catch (e) {
        showToast(`Erro ao salvar token: ${e.message}`, 'error');
    }
}

function togglePasswordVisibility(inputId) {
    const input = document.getElementById(inputId);
    const eye = document.getElementById(`${inputId}-eye`);
    if (!input) return;

    if (input.type === 'password') {
        input.type = 'text';
        if (eye) eye.setAttribute('data-lucide', 'eye-off');
    } else {
        input.type = 'password';
        if (eye) eye.setAttribute('data-lucide', 'eye');
    }
    refreshIcons();
}

// ==========================================================================
// Telemetry & Public Tools (Free APIs Suite)
// ==========================================================================

async function loadWanTelemetry(forceRefresh = false) {
    const headerPill = document.getElementById('header-wan-text');
    const toolIp = document.getElementById('tool-wan-ip');
    const toolPing = document.getElementById('tool-wan-ping');
    const toolIsp = document.getElementById('tool-wan-isp');
    const toolAsn = document.getElementById('tool-wan-asn');
    const toolGeo = document.getElementById('tool-wan-geo');

    try {
        const res = await fetch('/api/v1/telemetry/wan');
        const data = await res.json();
        state.wanData = data;

        if (headerPill) {
            headerPill.textContent = `WAN: ${data.wan_ip || 'Online'}`;
        }
        if (toolIp) toolIp.textContent = data.wan_ip || 'N/A';
        if (toolPing) toolPing.textContent = `${data.ping_ms || 12} ms`;
        if (toolIsp) toolIsp.textContent = data.isp || 'Pense Rede';
        if (toolAsn) toolAsn.textContent = data.asn || 'AS-LOCAL';
        if (toolGeo) toolGeo.textContent = `${data.city || 'Vitória'}, ${data.region || 'ES'} - ${data.country || 'Brasil'}`;

        if (forceRefresh) {
            showToast('Telemetria WAN atualizada', 'info');
        }
    } catch (e) {
        if (headerPill) headerPill.textContent = 'WAN: Offline';
    }
}

async function loadThermalTelemetry(forceRefresh = false) {
    const headerPill = document.getElementById('header-temp-text');
    const toolTemp = document.getElementById('tool-thermal-temp');
    const toolApp = document.getElementById('tool-thermal-app');
    const toolRh = document.getElementById('tool-thermal-rh');
    const toolNote = document.getElementById('tool-thermal-note');
    const badge = document.getElementById('thermal-rating-badge');

    try {
        const res = await fetch('/api/v1/telemetry/thermal');
        const data = await res.json();
        state.thermalData = data;

        if (headerPill) {
            headerPill.textContent = `Lab: ${data.temperature_c}°C`;
        }
        if (toolTemp) toolTemp.textContent = `${data.temperature_c}°C`;
        if (toolApp) toolApp.textContent = `${data.apparent_temperature_c}°C`;
        if (toolRh) toolRh.textContent = `${data.relative_humidity_pct}%`;
        if (toolNote) toolNote.innerHTML = `<strong>${data.thermal_headroom_rating}</strong>: ${data.thermal_delta_note}`;
        
        if (badge) {
            badge.textContent = data.temperature_c <= 27 ? 'Ideal' : 'Quente';
            badge.className = data.temperature_c <= 27 ? 'badge-status-ok' : 'badge-status-warn';
        }

        if (forceRefresh) {
            showToast('Telemetria térmica do laboratório atualizada', 'info');
        }
    } catch (e) {
        if (headerPill) headerPill.textContent = 'Lab: --°C';
    }
}

async function onLookupWindowsError(event) {
    if (event) event.preventDefault();
    const code = document.getElementById('win-error-input')?.value.trim();
    if (!code) return;
    await lookupWindowsErrorCode(code);
}

function quickLookupError(code) {
    const input = document.getElementById('win-error-input');
    if (input) input.value = code;
    lookupWindowsErrorCode(code);
}

async function lookupWindowsErrorCode(code) {
    const resultBox = document.getElementById('win-error-result');
    if (!resultBox) return;

    resultBox.classList.remove('hidden');
    resultBox.innerHTML = '<div class="text-center p-3"><i data-lucide="loader-2" class="spin-icon"></i> Analisando código de erro...</div>';
    refreshIcons();

    try {
        const res = await fetch(`/api/v1/tools/windows-error/lookup?code=${encodeURIComponent(code)}`);
        const data = await res.json();

        resultBox.innerHTML = `
            <div class="error-card-inner">
                <div class="error-header-row">
                    <div style="display: flex; align-items: center; gap: 0.6rem;">
                        <span class="badge-code mono">${data.code}</span>
                        <strong class="text-primary">${data.name}</strong>
                    </div>
                    <span class="badge-subtle">${data.category}</span>
                </div>
                <div class="error-cause mt-2">
                    <span class="text-muted text-xs uppercase font-bold">Causa Provável:</span>
                    <p class="text-sm mt-1">${data.cause}</p>
                </div>
                <div class="error-solution mt-2">
                    <span class="text-muted text-xs uppercase font-bold">Solução & Procedimento Técnico:</span>
                    <p class="text-sm mt-1">${data.solution}</p>
                </div>
                ${data.command ? `
                <div class="error-command-box mt-3">
                    <div class="cmd-box-header">
                        <span>Comando PowerShell de Correção</span>
                        <button type="button" class="btn-copy-code" onclick="copyTextToClipboard('${data.command.replace(/'/g, "\\'")}')">
                            <i data-lucide="copy"></i> Copiar
                        </button>
                    </div>
                    <pre class="cmd-snippet mono">${data.command}</pre>
                </div>
                ` : ''}
            </div>
        `;
        refreshIcons();
    } catch (e) {
        resultBox.innerHTML = `<p class="text-danger p-2">Erro ao consultar código: ${e.message}</p>`;
    }
}

async function onSearchCve(event) {
    if (event) event.preventDefault();
    const pkg = document.getElementById('cve-package-input')?.value.trim();
    const ver = document.getElementById('cve-version-input')?.value.trim();
    if (!pkg) return;
    await searchCveVulnerabilities(pkg, ver);
}

function quickSearchCve(pkg) {
    const input = document.getElementById('cve-package-input');
    if (input) input.value = pkg;
    searchCveVulnerabilities(pkg);
}

async function searchCveVulnerabilities(pkg, ver = '') {
    const container = document.getElementById('cve-results-container');
    if (!container) return;

    container.innerHTML = '<div class="text-center p-3"><i data-lucide="loader-2" class="spin-icon"></i> Consultando base OSV.dev e CIRCL...</div>';
    refreshIcons();

    try {
        const url = `/api/v1/tools/cve/search?package=${encodeURIComponent(pkg)}${ver ? `&version=${encodeURIComponent(ver)}` : ''}`;
        const res = await fetch(url);
        const data = await res.json();
        state.cveResults = data.vulnerabilities || [];

        if (state.cveResults.length === 0) {
            container.innerHTML = `
                <div class="alert-box-clean success">
                    <i data-lucide="check-circle"></i>
                    <div>
                        <strong>Nenhuma vulnerabilidade crítica recente reportada para '${data.package}'</strong>
                        <p class="text-xs text-muted mt-1">Pacote auditado contra as bases públicas de segurança.</p>
                    </div>
                </div>
            `;
            refreshIcons();
            return;
        }

        container.innerHTML = `
            <div class="cve-count-header mb-2">
                <span>Encontradas <strong>${data.total_found}</strong> vulnerabilidade(s) para <code>${data.package}</code>:</span>
            </div>
            <div class="cve-items-stack">
                ${state.cveResults.map(v => `
                    <div class="cve-card-item">
                        <div class="cve-header">
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <span class="cve-id mono">${v.id}</span>
                                <span class="severity-badge severity-${v.severity.toLowerCase()}">${v.severity}</span>
                            </div>
                            <span class="text-muted text-xs mono">${v.published}</span>
                        </div>
                        <p class="cve-summary text-sm mt-1">${v.summary}</p>
                        ${v.references && v.references.length > 0 ? `
                        <div class="cve-refs mt-2">
                            ${v.references.map(r => `<a href="${r}" target="_blank" rel="noopener noreferrer" class="cve-link"><i data-lucide="external-link"></i> ${r}</a>`).join('')}
                        </div>
                        ` : ''}
                    </div>
                `).join('')}
            </div>
        `;
        refreshIcons();
    } catch (e) {
        container.innerHTML = `<p class="text-danger p-2">Falha na consulta CVE: ${e.message}</p>`;
    }
}

function toggleCveSubTab(subTab) {
    const searchBtn = document.getElementById('tab-cve-search-btn');
    const kevBtn = document.getElementById('tab-cve-kev-btn');
    const searchView = document.getElementById('cve-search-view');
    const kevView = document.getElementById('cve-kev-view');

    if (subTab === 'search') {
        searchBtn?.classList.add('active');
        kevBtn?.classList.remove('active');
        searchView?.classList.remove('hidden');
        kevView?.classList.add('hidden');
    } else {
        kevBtn?.classList.add('active');
        searchBtn?.classList.remove('active');
        kevView?.classList.remove('hidden');
        searchView?.classList.add('hidden');
        loadCisaKevFeed();
    }
    refreshIcons();
}

async function loadCisaKevFeed(forceRefresh = false) {
    const container = document.getElementById('cisa-kev-container');
    if (!container) return;

    if (forceRefresh) {
        container.innerHTML = '<div class="text-center p-3"><i data-lucide="loader-2" class="spin-icon"></i> Atualizando catálogo CISA...</div>';
        refreshIcons();
    }

    try {
        const res = await fetch('/api/v1/tools/cve/kev?limit=6');
        const data = await res.json();
        state.cisaKevResults = data.recent_vulnerabilities || [];

        container.innerHTML = `
            <div class="cve-items-stack">
                ${state.cisaKevResults.map(k => `
                    <div class="cve-card-item">
                        <div class="cve-header">
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <span class="cve-id mono">${k.cveID}</span>
                                <span class="severity-badge severity-critical">EXPLORAÇÃO ATIVA</span>
                            </div>
                            <span class="text-muted text-xs mono">Adicionado: ${k.dateAdded}</span>
                        </div>
                        <div class="cve-vendor-prod mt-1">
                            <strong>${k.vendorProject}</strong> &bull; <span>${k.product}</span>: <em class="text-secondary">${k.vulnerabilityName}</em>
                        </div>
                        <p class="cve-summary text-sm mt-1">${k.shortDescription}</p>
                        <div class="cve-action-note mt-2">
                            <i data-lucide="alert-triangle" class="text-warning"></i>
                            <span>Ação recomendada: ${k.requiredAction}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
        refreshIcons();
    } catch (e) {
        container.innerHTML = `<p class="text-danger p-2">Erro ao obter catálogo CISA: ${e.message}</p>`;
    }
}

async function onInspectDnsDomain(event) {
    if (event) event.preventDefault();
    const domain = document.getElementById('dns-domain-input')?.value.trim();
    if (!domain) return;

    const resultBox = document.getElementById('dns-inspect-result');
    if (!resultBox) return;

    resultBox.innerHTML = '<div class="text-center p-3"><i data-lucide="loader-2" class="spin-icon"></i> Consultando DNS e registros SRV...</div>';
    refreshIcons();

    try {
        const res = await fetch(`/api/v1/tools/dns/inspect?domain=${encodeURIComponent(domain)}`);
        const data = await res.json();

        resultBox.innerHTML = `
            <div class="dns-result-box ${data.reachable ? 'success' : 'error'}">
                <div class="dns-header">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="status-indicator ${data.reachable ? 'online' : 'offline'}"></span>
                        <strong>${data.domain}</strong>
                    </div>
                    <span class="badge-subtle">${data.reachable ? 'Resolvível' : 'Inacessível'}</span>
                </div>
                <p class="text-sm mt-1">${data.message}</p>
                ${data.resolved_ips && data.resolved_ips.length > 0 ? `
                <div class="dns-ips mt-2">
                    <span class="text-xs text-muted uppercase font-bold">IPs Resolvidos:</span>
                    <div class="ip-tags-row mt-1">
                        ${data.resolved_ips.map(ip => `<span class="tag-ip mono">${ip}</span>`).join('')}
                    </div>
                </div>
                ` : ''}
                ${data.srv_dc_records && data.srv_dc_records.length > 0 ? `
                <div class="dns-srv mt-2">
                    <span class="text-xs text-muted uppercase font-bold">Controladores de Domínio AD (SRV):</span>
                    <ul class="srv-list mt-1">
                        ${data.srv_dc_records.map(srv => `<li class="mono text-xs">${srv}</li>`).join('')}
                    </ul>
                </div>
                ` : ''}
            </div>
        `;
        refreshIcons();
    } catch (e) {
        resultBox.innerHTML = `<p class="text-danger p-2">Erro ao inspecionar domínio: ${e.message}</p>`;
    }
}

async function checkNtpSync(forceRefresh = false) {
    const timeEl = document.getElementById('ntp-local-time');
    const driftEl = document.getElementById('ntp-drift-val');
    const kerbEl = document.getElementById('ntp-kerberos-status');
    const badge = document.getElementById('ntp-status-badge');

    try {
        const res = await fetch('/api/v1/tools/ntp/check');
        const data = await res.json();

        if (timeEl) timeEl.textContent = data.local_datetime || new Date().toLocaleString();
        if (driftEl) driftEl.textContent = `${data.drift_seconds} s`;
        if (kerbEl) {
            kerbEl.textContent = data.ntp_synced ? 'Compatível com Kerberos AD (< 300s)' : 'ALERTA: Desvio excessivo!';
            kerbEl.className = data.ntp_synced ? 't-val text-success' : 't-val text-danger';
        }
        if (badge) {
            badge.textContent = data.ntp_synced ? 'Sincronizado' : 'Desalinhado';
            badge.className = data.ntp_synced ? 'badge-status-ok' : 'badge-status-err';
        }

        if (forceRefresh) {
            showToast(data.message, data.ntp_synced ? 'info' : 'warning');
        }
    } catch (e) {
        if (timeEl) timeEl.textContent = new Date().toLocaleTimeString();
    }
}

async function checkToolVersions(forceRefresh = false) {
    const list = document.getElementById('github-tools-list');
    if (!list) return;

    try {
        const res = await fetch('/api/v1/tools/versions/check');
        const data = await res.json();
        state.toolVersions = data.tools || [];

        list.innerHTML = state.toolVersions.map(t => `
            <div class="tool-version-row">
                <div class="tool-v-info">
                    <span class="tool-v-name">${t.name}</span>
                    <a href="${t.html_url}" target="_blank" rel="noopener noreferrer" class="tool-v-repo mono">${t.repo}</a>
                </div>
                <div class="tool-v-meta">
                    <span class="badge-code mono">${t.latest_version}</span>
                    <span class="text-xs text-muted">${t.published_at}</span>
                </div>
            </div>
        `).join('');

        if (forceRefresh) {
            showToast('Versões das ferramentas atualizadas via GitHub API', 'info');
        }
    } catch (e) {
        list.innerHTML = '<p class="text-muted text-xs">Indisponível no momento.</p>';
    }
}

async function loadTechQuote() {
    try {
        const res = await fetch('/api/v1/tools/quote');
        const data = await res.json();
        if (data.quote) {
            const terminal = document.getElementById('terminal-logs');
            if (terminal && terminal.children.length <= 1) {
                appendLog(`💡 "${data.quote}" — ${data.author || 'Tech Wisdom'}`, 'info');
            }
        }
    } catch (e) {
        // Silently skip
    }
}

async function generateMobileQr() {
    const input = document.getElementById('qr-input-text')?.value.trim();
    const container = document.getElementById('qr-display-container');
    if (!container || !input) return;

    container.innerHTML = '<div class="text-center p-2"><i data-lucide="loader-2" class="spin-icon"></i> Gerando QR Code...</div>';
    refreshIcons();

    try {
        const res = await fetch(`/api/v1/tools/qr?data=${encodeURIComponent(input)}&size=200`);
        const data = await res.json();

        container.innerHTML = `
            <div class="qr-result-card">
                <img src="${data.qr_url}" alt="QR Code" class="qr-img" loading="lazy">
                <div class="qr-caption mono text-xs mt-2 text-muted">${data.data}</div>
            </div>
        `;
    } catch (e) {
        container.innerHTML = `<p class="text-danger text-xs">Erro ao gerar QR: ${e.message}</p>`;
    }
}

function openDeviceQrModal(ip, hostname, mac) {
    const modal = document.getElementById('qr-modal');
    const title = document.getElementById('qr-modal-title');
    const imageBox = document.getElementById('qr-modal-image-box');
    const caption = document.getElementById('qr-modal-caption');
    if (!modal) return;

    if (title) title.textContent = `Acesso Mobile: ${hostname || ip}`;
    if (caption) caption.textContent = `IP: ${ip} | MAC: ${mac || 'N/A'}`;
    
    const targetUrl = `http://${window.location.host}/dashboard#ip=${ip}`;
    if (imageBox) {
        imageBox.innerHTML = `
            <img src="/api/v1/tools/qr?data=${encodeURIComponent(targetUrl)}&size=240" alt="QR Code" class="qr-img" style="border-radius: 8px;">
        `;
    }

    modal.classList.add('active');
    refreshIcons();
}

function closeQrModal() {
    const modal = document.getElementById('qr-modal');
    if (modal) modal.classList.remove('active');
}

function refreshAllTools() {
    loadWanTelemetry(true);
    loadThermalTelemetry(true);
    checkNtpSync(true);
    checkToolVersions(true);
    loadCisaKevFeed(true);
}

