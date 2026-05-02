/* ─── LeadPilot Frontend App ─────────────────────── */
const API = '';
let currentLeadId = null;
let chatPollTimer = null;

// ─── Utility ──────────────────────
function $(id) { return document.getElementById(id); }
function show(el) { el.style.display = 'flex'; }
function hide(el) { el.style.display = 'none'; }

function toast(msg, type = 'success') {
    const c = $('toast-container');
    const t = document.createElement('div');
    t.className = `toast toast-${type}`;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

async function api(path, opts = {}) {
    try {
        const r = await fetch(API + path, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
            body: opts.body ? JSON.stringify(opts.body) : undefined,
        });
        return await r.json();
    } catch (e) {
        if (!opts.silent) toast('API Error: ' + e.message, 'error');
        return null;
    }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

function timeAgo(iso) {
    if (!iso) return '';
    const d = new Date(iso + (iso.includes('Z') ? '' : 'Z'));
    const s = Math.floor((Date.now() - d) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
}

function formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso + (iso.includes('Z') ? '' : 'Z'));
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function getInitials(name) {
    if (!name) return '?';
    return name.split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
}

// ─── Navigation ──────────────────────
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', e => {
        e.preventDefault();
        const view = item.dataset.view;
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        item.classList.add('active');
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        $(`view-${view}`).classList.add('active');
        $('page-title').textContent = item.textContent.trim();
        if (view === 'dashboard') loadDashboard();
        if (view === 'leads') loadLeads();
        if (view === 'messages') { loadChats(); startChatPolling(); }
        if (view === 'properties') {}
        if (view === 'ai') { checkAI(); loadKBStatus(); }
        // Stop polling when leaving messages
        if (view !== 'messages') stopChatPolling();
    });
});

$('menu-toggle').addEventListener('click', () => { $('sidebar').classList.toggle('open'); });

// ─── Dashboard ──────────────────────
async function loadDashboard() {
    const d = await api('/api/dashboard/stats', { silent: true });
    if (!d) return;
    $('stat-total').textContent = d.total_leads;
    $('stat-new').textContent = d.new_leads;
    $('stat-contacted').textContent = d.contacted;
    $('stat-converted').textContent = d.converted;
    $('stat-messages').textContent = d.total_messages;
    $('stat-followups').textContent = d.active_followups;

    const rl = $('recent-leads-list');
    if (d.recent_leads && d.recent_leads.length > 0) {
        rl.innerHTML = d.recent_leads.map(l => `
            <div class="recent-lead-item">
                <div><div class="recent-lead-name">${esc(l.name)}</div><div class="recent-lead-meta">${l.source} &middot; ${timeAgo(l.created_at)}</div></div>
                <span class="badge badge-${l.status}">${l.status}</span>
            </div>`).join('');
    } else { rl.innerHTML = '<div class="empty-state">No leads yet</div>'; }

    const sc = $('source-chart');
    const sources = d.leads_by_source || {};
    const maxVal = Math.max(...Object.values(sources), 1);
    if (Object.keys(sources).length > 0) {
        sc.innerHTML = '<div class="source-bars">' + Object.entries(sources).map(([k, v]) =>
            `<div class="source-bar-row"><span class="source-bar-label">${k}</span><div class="source-bar-track"><div class="source-bar-fill ${k === '99acres' ? 's99acres' : k}" style="width:${(v / maxVal) * 100}%">${v}</div></div></div>`
        ).join('') + '</div>';
    }
}

// ─── Leads ──────────────────────
async function loadLeads() {
    const status = $('filter-status').value;
    const source = $('filter-source').value;
    const search = $('lead-search').value;
    let url = '/api/leads?limit=100';
    if (status) url += `&status=${status}`;
    if (source) url += `&source=${source}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    const d = await api(url);
    if (!d) return;
    const tb = $('leads-tbody');
    if (d.leads.length === 0) { tb.innerHTML = '<tr><td colspan="7" class="empty-state">No leads found</td></tr>'; return; }
    tb.innerHTML = d.leads.map(l => `
        <tr>
            <td><strong>${esc(l.name)}</strong>${l.email ? '<br><span style="font-size:11px;color:var(--text-muted)">' + esc(l.email) + '</span>' : ''}</td>
            <td>${esc(l.phone || '-')}</td>
            <td><span class="source-badge">${l.source}</span></td>
            <td><span class="badge badge-${l.status}">${l.status}</span></td>
            <td>${l.budget_min || l.budget_max ? (l.budget_min || '?') + '-' + (l.budget_max || '?') + 'L' : '-'}</td>
            <td>${esc(l.preferred_location || '-')}</td>
            <td class="action-btns">
                <button class="action-btn" onclick="viewLead(${l.id})">View</button>
                <button class="action-btn delete" onclick="deleteLead(${l.id})">Del</button>
            </td>
        </tr>`).join('');
}

$('filter-status').addEventListener('change', loadLeads);
$('filter-source').addEventListener('change', loadLeads);
let searchTimer;
$('lead-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadLeads, 300); });

window.viewLead = async function (id) {
    const d = await api(`/api/leads/${id}`);
    if (!d) return;
    alert(`Lead: ${d.name}\nPhone: ${d.phone}\nEmail: ${d.email}\nStatus: ${d.status}\nBudget: ${d.budget_min}-${d.budget_max}L\nLocation: ${d.preferred_location}\nType: ${d.property_type}\nMessages: ${(d.messages || []).length}`);
};

window.deleteLead = async function (id) {
    if (!confirm('Delete this lead?')) return;
    await api(`/api/leads/${id}`, { method: 'DELETE' });
    toast('Lead deleted');
    loadLeads();
};

// ─── Add Lead Modal ──────────────────────
$('btn-add-lead').addEventListener('click', () => show($('modal-overlay')));
$('modal-close').addEventListener('click', () => hide($('modal-overlay')));
$('btn-cancel-lead').addEventListener('click', () => hide($('modal-overlay')));
$('modal-overlay').addEventListener('click', e => { if (e.target === $('modal-overlay')) hide($('modal-overlay')); });

$('btn-save-lead').addEventListener('click', async () => {
    const name = $('new-lead-name').value.trim();
    if (!name) { toast('Name is required', 'error'); return; }
    const body = {
        name, phone: $('new-lead-phone').value.trim(), email: $('new-lead-email').value.trim(),
        source: $('new-lead-source').value, budget_min: parseFloat($('new-lead-budget-min').value) || null,
        budget_max: parseFloat($('new-lead-budget-max').value) || null,
        preferred_location: $('new-lead-location').value.trim(), property_type: $('new-lead-type').value,
        notes: $('new-lead-notes').value.trim(),
    };
    const r = await api('/api/leads', { method: 'POST', body });
    if (r) { toast('Lead created!'); hide($('modal-overlay')); $('new-lead-name').value = ''; loadLeads(); loadDashboard(); }
});

// ─── Parse Email ──────────────────────
$('btn-parse-email').addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    $('nav-ai').classList.add('active');
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    $('view-ai').classList.add('active');
    $('page-title').textContent = 'AI Tools';
});

$('btn-do-parse').addEventListener('click', async () => {
    const body = { sender: $('parse-sender').value, subject: $('parse-subject').value, body: $('parse-body').value };
    const r = await api('/api/parse-email/save', { method: 'POST', body });
    const box = $('parse-result');
    show(box); box.style.display = 'block';
    box.textContent = JSON.stringify(r, null, 2);
    if (r && r.status === 'created') toast('Lead created from email!');
});

// ─── Properties ──────────────────────
$('btn-index-samples').addEventListener('click', async () => {
    toast('Indexing...', 'info');
    const r = await api('/api/properties/index-samples', { method: 'POST' });
    if (r) toast(`Indexed ${r.indexed} properties`);
});

$('btn-search-properties').addEventListener('click', searchPropertiesUI);
$('property-search').addEventListener('keydown', e => { if (e.key === 'Enter') searchPropertiesUI(); });

async function searchPropertiesUI() {
    const q = $('property-search').value.trim();
    if (!q) { toast('Enter a search query', 'error'); return; }
    const r = await api('/api/properties/search', { method: 'POST', body: { query: q, n_results: 8 } });
    const grid = $('properties-grid');
    if (!r || !r.results || r.results.length === 0) { grid.innerHTML = '<div class="empty-state">No properties found.</div>'; return; }
    grid.innerHTML = r.results.map(p => `
        <div class="property-card">
            <h4>${esc(p.title || 'Property')}</h4>
            <div style="font-size:12px;color:var(--text-secondary)">${esc(p.location || '')}</div>
            <div class="property-price">&#8377; ${p.price}L</div>
            <div class="property-meta">
                ${p.bedrooms ? `<span class="property-tag">${p.bedrooms} BHK</span>` : ''}
                ${p.property_type ? `<span class="property-tag">${p.property_type}</span>` : ''}
                ${p.area_sqft ? `<span class="property-tag">${p.area_sqft} sqft</span>` : ''}
            </div>
            <div class="property-relevance">Relevance: ${(p.relevance * 100).toFixed(0)}%</div>
        </div>`).join('');
}

// ═══════════════════════════════════════════════════
// ─── Chat Manager (WhatsApp Web style) ────────────
// ═══════════════════════════════════════════════════

async function loadChats() {
    const d = await api('/api/chats', { silent: true });
    if (!d) return;
    const list = $('wa-contact-list');

    // Update sidebar unread badge
    const totalUnread = d.chats.reduce((s, c) => s + (c.unread_count || 0), 0);
    const badge = $('nav-unread-badge');
    if (totalUnread > 0) { badge.textContent = totalUnread; badge.style.display = ''; }
    else { badge.style.display = 'none'; }

    if (d.chats.length === 0) { list.innerHTML = '<div class="empty-state small">No conversations yet.<br>Add a lead with a phone number to start.</div>'; return; }

    // Filter by search
    const search = ($('chat-search').value || '').toLowerCase();
    let chats = d.chats;
    if (search) chats = chats.filter(c => c.name.toLowerCase().includes(search) || (c.phone || '').includes(search));

    list.innerHTML = chats.map(c => `
        <div class="wa-contact-item ${currentLeadId === c.lead_id ? 'active' : ''}" onclick="selectChat(${c.lead_id})">
            <div class="wa-avatar">${esc(getInitials(c.name))}</div>
            <div class="wa-contact-info">
                <div class="wa-contact-name">${esc(c.name)}</div>
                <div class="wa-contact-preview">${c.last_message_direction === 'out' ? '&#10003; ' : ''}${esc(c.last_message || 'No messages')}</div>
            </div>
            <div class="wa-contact-meta">
                <div class="wa-contact-time">${timeAgo(c.last_message_at)}</div>
                ${c.unread_count > 0 ? `<div class="wa-unread-badge">${c.unread_count}</div>` : ''}
                ${c.auto_reply_enabled ? '<div class="wa-auto-indicator">🤖</div>' : ''}
            </div>
        </div>`).join('');
}

let chatSearchTimer;
if ($('chat-search')) {
    $('chat-search').addEventListener('input', () => { clearTimeout(chatSearchTimer); chatSearchTimer = setTimeout(loadChats, 200); });
}

window.selectChat = async function (leadId) {
    currentLeadId = leadId;

    // Mark as read
    await api(`/api/chats/${leadId}/read`, { method: 'POST' });

    // Load messages
    const d = await api(`/api/chats/${leadId}`);
    if (!d) return;

    // Update header
    $('wa-chat-name').textContent = d.name;
    $('wa-chat-phone').textContent = d.phone || '';
    $('wa-chat-avatar').textContent = getInitials(d.name);
    $('wa-chat-actions').style.display = 'flex';
    $('wa-input-bar').style.display = 'flex';

    // Auto-reply toggle
    const autoOn = d.auto_reply_enabled;
    const toggleBtn = $('btn-toggle-auto');
    const autoLabel = $('wa-auto-label');
    toggleBtn.className = `btn-icon wa-auto-reply-btn ${autoOn ? '' : 'off'}`;
    autoLabel.textContent = autoOn ? 'Auto: ON' : 'Auto: OFF';
    autoLabel.className = `wa-auto-label ${autoOn ? 'on' : 'off'}`;

    // Render messages
    const box = $('wa-messages');
    if (!d.messages || d.messages.length === 0) {
        box.innerHTML = '<div class="wa-empty-chat"><div class="wa-empty-icon">💬</div><h3>No messages</h3><p>Send a message to start the conversation</p></div>';
    } else {
        let html = '';
        let lastDate = '';
        for (const m of d.messages) {
            const msgDate = m.created_at ? new Date(m.created_at + (m.created_at.includes('Z') ? '' : 'Z')).toLocaleDateString() : '';
            if (msgDate && msgDate !== lastDate) {
                html += `<div class="wa-date-divider">${msgDate}</div>`;
                lastDate = msgDate;
            }
            html += `<div class="wa-msg-bubble ${m.direction}">
                ${esc(m.content)}
                <div class="wa-msg-time">${formatTime(m.created_at)}</div>
                ${m.direction === 'out' && m.is_auto_replied === false && m.content ? '' : ''}
            </div>`;
        }
        box.innerHTML = html;
        box.scrollTop = box.scrollHeight;
    }

    // Refresh contact list to update active state & clear unread
    loadChats();
};

// Send message
$('btn-wa-send').addEventListener('click', sendChatMessage);
$('wa-msg-input').addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMessage(); });

async function sendChatMessage() {
    if (!currentLeadId) return;
    const msg = $('wa-msg-input').value.trim();
    if (!msg) return;
    $('wa-msg-input').value = '';

    // Optimistic UI: append bubble immediately
    const box = $('wa-messages');
    const emptyChat = box.querySelector('.wa-empty-chat');
    if (emptyChat) emptyChat.remove();

    const bubble = document.createElement('div');
    bubble.className = 'wa-msg-bubble out';
    bubble.innerHTML = `${esc(msg)}<div class="wa-msg-time">just now</div>`;
    box.appendChild(bubble);
    box.scrollTop = box.scrollHeight;

    const r = await api(`/api/chats/${currentLeadId}/send`, { method: 'POST', body: { lead_id: currentLeadId, message: msg } });
    if (r) toast('Sent');
    loadChats();
}

// AI Reply
$('btn-wa-ai').addEventListener('click', async () => {
    if (!currentLeadId) return;
    toast('Generating AI reply...', 'info');
    const r = await api('/api/ai/reply', { method: 'POST', body: { lead_id: currentLeadId } });
    if (r && r.reply) { $('wa-msg-input').value = r.reply; toast('AI reply generated'); }
});

// Toggle auto-reply
$('btn-toggle-auto').addEventListener('click', async () => {
    if (!currentLeadId) return;
    const r = await api(`/api/chats/${currentLeadId}/toggle-auto-reply`, { method: 'POST' });
    if (r) {
        const autoLabel = $('wa-auto-label');
        const toggleBtn = $('btn-toggle-auto');
        toggleBtn.className = `btn-icon wa-auto-reply-btn ${r.auto_reply_enabled ? '' : 'off'}`;
        autoLabel.textContent = r.auto_reply_enabled ? 'Auto: ON' : 'Auto: OFF';
        autoLabel.className = `wa-auto-label ${r.auto_reply_enabled ? 'on' : 'off'}`;
        toast(`Auto-reply ${r.auto_reply_enabled ? 'enabled' : 'disabled'}`);
        loadChats();
    }
});

// Simulate incoming message modal
$('btn-simulate').addEventListener('click', () => show($('simulate-modal')));
$('sim-modal-close').addEventListener('click', () => hide($('simulate-modal')));
$('sim-cancel').addEventListener('click', () => hide($('simulate-modal')));
$('simulate-modal').addEventListener('click', e => { if (e.target === $('simulate-modal')) hide($('simulate-modal')); });

$('sim-send').addEventListener('click', async () => {
    const phone = $('sim-phone').value.trim();
    const message = $('sim-message').value.trim();
    if (!phone || !message) { toast('Phone and message required', 'error'); return; }
    const body = { phone, message, sender_name: $('sim-name').value.trim() || 'Test User' };
    const r = await api('/api/chats/simulate-incoming', { method: 'POST', body });
    if (r) { toast('Incoming message simulated!'); hide($('simulate-modal')); loadChats(); }
});

// Chat polling (every 3 seconds)
function startChatPolling() {
    stopChatPolling();
    chatPollTimer = setInterval(async () => {
        await loadChats();
        // If a chat is open, refresh messages
        if (currentLeadId) {
            const d = await api(`/api/chats/${currentLeadId}`, { silent: true });
            if (d && d.messages) {
                const box = $('wa-messages');
                const currentCount = box.querySelectorAll('.wa-msg-bubble').length;
                if (d.messages.length !== currentCount) {
                    selectChat(currentLeadId);
                }
            }
        }
    }, 3000);
}

function stopChatPolling() {
    if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }
}

// ─── Knowledge Base ──────────────────────
async function loadKBStatus() {
    const d = await api('/api/kb/status');
    const el = $('kb-status');
    if (!d) { el.innerHTML = '<p style="color:var(--text-muted)">Unable to load KB status</p>'; return; }
    el.innerHTML = `
        <p><strong>Files:</strong> ${d.files} (${d.file_names.join(', ') || 'none'})</p>
        <p><strong>Indexed chunks:</strong> ${d.indexed_chunks}</p>
        <p style="font-size:12px;color:var(--text-muted);margin-top:8px">Add .txt or .md files to <code>data/knowledge_base/</code></p>`;
}

$('btn-index-kb').addEventListener('click', async () => {
    toast('Indexing knowledge base...', 'info');
    const r = await api('/api/kb/index', { method: 'POST' });
    if (r) { toast(`Indexed ${r.total_chunks} chunks from ${r.files} files`); loadKBStatus(); }
});

// ─── RAG Search ──────────────────────
$('btn-rag-search').addEventListener('click', async () => {
    const q = $('rag-query').value.trim();
    if (!q) return;
    const r = await api('/api/kb/search', { method: 'POST', body: { query: q, n_results: 5 } });
    const box = $('rag-result');
    box.style.display = 'block';
    box.textContent = JSON.stringify(r, null, 2);
});

// ─── Follow-up ──────────────────────
$('btn-create-followup').addEventListener('click', async () => {
    const lid = parseInt($('fu-lead-id').value);
    if (!lid) { toast('Enter a lead ID', 'error'); return; }
    const body = { lead_id: lid, frequency_hours: parseInt($('fu-frequency').value) || 24, max_followups: parseInt($('fu-max').value) || 5 };
    const r = await api('/api/followups', { method: 'POST', body });
    const box = $('followup-result');
    box.style.display = 'block';
    box.textContent = JSON.stringify(r, null, 2);
    if (r && r.status === 'created') toast('Follow-up scheduled!');
});

// ─── AI Status ──────────────────────
async function checkAI() {
    const d = await api('/api/ai/status', { silent: true });
    const el = $('ai-status-detail');
    const dot = $('ai-dot');
    const txt = $('ai-status-text');
    if (d && d.ollama_running) {
        dot.className = 'status-dot online';
        txt.textContent = 'AI Online';
        el.innerHTML = `<p style="color:var(--green)">&#10003; Ollama is running</p><p>Models: ${d.models.join(', ') || 'None loaded'}</p>`;
    } else {
        dot.className = 'status-dot offline';
        txt.textContent = 'AI Offline';
        el.innerHTML = `<p style="color:var(--red)">&#10007; Ollama not running</p><p style="font-size:12px;color:var(--text-muted)">Start Ollama or run install.bat</p>`;
    }
}

// ─── Init ──────────────────────
loadDashboard();
checkAI();
