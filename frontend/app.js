/* ─── LeadPilot Frontend App ─────────────────────── */
const API = '';
let currentLeadId = null;

// ─── Utility ──────────────────────
function $(id) { return document.getElementById(id); }
function show(el) { el.style.display = ''; }
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
        toast('API Error: ' + e.message, 'error');
        return null;
    }
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
        if (view === 'messages') loadMsgLeads();
        if (view === 'ai') checkAI();
    });
});

$('menu-toggle').addEventListener('click', () => {
    $('sidebar').classList.toggle('open');
});

// ─── Dashboard ──────────────────────
async function loadDashboard() {
    const d = await api('/api/dashboard/stats');
    if (!d) return;
    $('stat-total').textContent = d.total_leads;
    $('stat-new').textContent = d.new_leads;
    $('stat-contacted').textContent = d.contacted;
    $('stat-converted').textContent = d.converted;
    $('stat-messages').textContent = d.total_messages;
    $('stat-followups').textContent = d.active_followups;

    // Recent leads
    const rl = $('recent-leads-list');
    if (d.recent_leads && d.recent_leads.length > 0) {
        rl.innerHTML = d.recent_leads.map(l => `
            <div class="recent-lead-item">
                <div><div class="recent-lead-name">${esc(l.name)}</div><div class="recent-lead-meta">${l.source} &middot; ${timeAgo(l.created_at)}</div></div>
                <span class="badge badge-${l.status}">${l.status}</span>
            </div>`).join('');
    } else {
        rl.innerHTML = '<div class="empty-state">No leads yet</div>';
    }

    // Source chart
    const sc = $('source-chart');
    const sources = d.leads_by_source || {};
    const maxVal = Math.max(...Object.values(sources), 1);
    if (Object.keys(sources).length > 0) {
        sc.innerHTML = '<div class="source-bars">' + Object.entries(sources).map(([k, v]) =>
            `<div class="source-bar-row">
                <span class="source-bar-label">${k}</span>
                <div class="source-bar-track"><div class="source-bar-fill ${k === '99acres' ? 's99acres' : k}" style="width:${(v/maxVal)*100}%">${v}</div></div>
            </div>`
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
    if (d.leads.length === 0) {
        tb.innerHTML = '<tr><td colspan="7" class="empty-state">No leads found</td></tr>';
        return;
    }
    tb.innerHTML = d.leads.map(l => `
        <tr>
            <td><strong>${esc(l.name)}</strong>${l.email ? '<br><span style="font-size:11px;color:var(--text-muted)">' + esc(l.email) + '</span>' : ''}</td>
            <td>${esc(l.phone || '-')}</td>
            <td><span class="source-badge">${l.source}</span></td>
            <td><span class="badge badge-${l.status}">${l.status}</span></td>
            <td>${l.budget_min || l.budget_max ? (l.budget_min||'?') + '-' + (l.budget_max||'?') + 'L' : '-'}</td>
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

async function viewLead(id) {
    const d = await api(`/api/leads/${id}`);
    if (!d) return;
    alert(`Lead: ${d.name}\nPhone: ${d.phone}\nEmail: ${d.email}\nStatus: ${d.status}\nBudget: ${d.budget_min}-${d.budget_max}L\nLocation: ${d.preferred_location}\nType: ${d.property_type}\nMessages: ${(d.messages||[]).length}\nFollow-ups: ${(d.followups||[]).length}`);
}

async function deleteLead(id) {
    if (!confirm('Delete this lead?')) return;
    await api(`/api/leads/${id}`, { method: 'DELETE' });
    toast('Lead deleted');
    loadLeads();
    loadDashboard();
}

// ─── Add Lead Modal ──────────────────────
$('btn-add-lead').addEventListener('click', () => show($('modal-overlay')));
$('modal-close').addEventListener('click', () => hide($('modal-overlay')));
$('btn-cancel-lead').addEventListener('click', () => hide($('modal-overlay')));
$('modal-overlay').addEventListener('click', e => { if (e.target === $('modal-overlay')) hide($('modal-overlay')); });

$('btn-save-lead').addEventListener('click', async () => {
    const name = $('new-lead-name').value.trim();
    if (!name) { toast('Name is required', 'error'); return; }
    const body = {
        name,
        phone: $('new-lead-phone').value.trim(),
        email: $('new-lead-email').value.trim(),
        source: $('new-lead-source').value,
        budget_min: parseFloat($('new-lead-budget-min').value) || null,
        budget_max: parseFloat($('new-lead-budget-max').value) || null,
        preferred_location: $('new-lead-location').value.trim(),
        property_type: $('new-lead-type').value,
        notes: $('new-lead-notes').value.trim(),
    };
    const r = await api('/api/leads', { method: 'POST', body });
    if (r) {
        toast('Lead created!');
        hide($('modal-overlay'));
        $('new-lead-name').value = '';
        loadLeads();
        loadDashboard();
    }
});

// ─── Parse Email (header button goes to AI view) ──────────────────────
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
    show(box);
    box.textContent = JSON.stringify(r, null, 2);
    if (r && r.status === 'created') toast('Lead created from email!');
});

// ─── Properties ──────────────────────
$('btn-index-samples').addEventListener('click', async () => {
    toast('Indexing sample properties...', 'info');
    const r = await api('/api/properties/index-samples', { method: 'POST' });
    if (r) toast(`Indexed ${r.indexed} properties`);
});

$('btn-search-properties').addEventListener('click', searchProperties);
$('property-search').addEventListener('keydown', e => { if (e.key === 'Enter') searchProperties(); });

async function searchProperties() {
    const q = $('property-search').value.trim();
    if (!q) { toast('Enter a search query', 'error'); return; }
    const r = await api('/api/properties/search', { method: 'POST', body: { query: q, n_results: 8 } });
    const grid = $('properties-grid');
    if (!r || !r.results || r.results.length === 0) {
        grid.innerHTML = '<div class="empty-state">No properties found. Try indexing samples first.</div>';
        return;
    }
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

// ─── Messages ──────────────────────
async function loadMsgLeads() {
    const d = await api('/api/leads?limit=50');
    if (!d) return;
    const list = $('msg-leads-list');
    if (d.leads.length === 0) {
        list.innerHTML = '<div class="empty-state small">No leads</div>';
        return;
    }
    list.innerHTML = d.leads.map(l => `
        <div class="lead-msg-item ${currentLeadId === l.id ? 'active' : ''}" onclick="selectMsgLead(${l.id}, '${esc(l.name)}', '${esc(l.phone||'')}')">
            <div class="name">${esc(l.name)}</div>
            <div class="phone">${esc(l.phone || 'No phone')}</div>
        </div>`).join('');
}

window.selectMsgLead = async function(id, name, phone) {
    currentLeadId = id;
    $('chat-header').textContent = `${name} (${phone})`;
    show($('chat-input-area'));
    loadMsgLeads();
    const d = await api(`/api/messages/${id}`);
    const box = $('chat-messages');
    if (!d || d.messages.length === 0) {
        box.innerHTML = '<div class="empty-state">No messages yet</div>';
        return;
    }
    box.innerHTML = d.messages.map(m => `
        <div class="msg-bubble msg-${m.direction}">
            ${esc(m.content)}
            <div class="msg-time">${m.direction === 'out' ? 'Sent' : 'Received'} &middot; ${timeAgo(m.created_at)}</div>
        </div>`).join('');
    box.scrollTop = box.scrollHeight;
};

$('btn-send-msg').addEventListener('click', sendMessage);
$('chat-input').addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });

async function sendMessage() {
    if (!currentLeadId) return;
    const msg = $('chat-input').value.trim();
    if (!msg) return;
    $('chat-input').value = '';
    const r = await api('/api/messages/send', { method: 'POST', body: { lead_id: currentLeadId, message: msg } });
    if (r) toast('Message sent');
    selectMsgLead(currentLeadId, $('chat-header').textContent.split('(')[0].trim(), '');
}

$('btn-ai-reply').addEventListener('click', async () => {
    if (!currentLeadId) return;
    toast('Generating AI reply...', 'info');
    const r = await api('/api/ai/reply', { method: 'POST', body: { lead_id: currentLeadId } });
    if (r && r.reply) {
        $('chat-input').value = r.reply;
        toast('AI reply generated');
    }
});

// ─── RAG Search ──────────────────────
$('btn-rag-search').addEventListener('click', async () => {
    const q = $('rag-query').value.trim();
    if (!q) return;
    const r = await api('/api/properties/search', { method: 'POST', body: { query: q, n_results: 5 } });
    const box = $('rag-result');
    show(box);
    box.textContent = JSON.stringify(r, null, 2);
});

// ─── Follow-up ──────────────────────
$('btn-create-followup').addEventListener('click', async () => {
    const lid = parseInt($('fu-lead-id').value);
    if (!lid) { toast('Enter a lead ID', 'error'); return; }
    const body = {
        lead_id: lid,
        frequency_hours: parseInt($('fu-frequency').value) || 24,
        max_followups: parseInt($('fu-max').value) || 5,
        message_template: $('fu-template') ? $('fu-template').value.trim() || null : null,
    };
    const r = await api('/api/followups', { method: 'POST', body });
    const box = $('followup-result');
    show(box);
    box.textContent = JSON.stringify(r, null, 2);
    if (r && r.status === 'created') toast('Follow-up scheduled!');
});

// ─── AI Status ──────────────────────
async function checkAI() {
    const d = await api('/api/ai/status');
    const el = $('ai-status-detail');
    const dot = document.querySelector('.status-dot');
    const txt = document.querySelector('.status-text');
    if (d && d.ollama_running) {
        dot.className = 'status-dot online';
        txt.textContent = 'AI Online';
        el.innerHTML = `<p style="color:var(--green)">&#10003; Ollama is running</p><p>Models: ${d.models.join(', ') || 'None loaded'}</p><p style="font-size:12px;color:var(--text-muted);margin-top:8px">Run <code>ollama pull phi3:mini</code> if no model loaded</p>`;
    } else {
        dot.className = 'status-dot offline';
        txt.textContent = 'AI Offline';
        el.innerHTML = `<p style="color:var(--red)">&#10007; Ollama not running</p><p style="font-size:12px;color:var(--text-muted)">Start Ollama or run install.bat</p>`;
    }
}

// ─── Helpers ──────────────────────
function esc(s) { const d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; }

function timeAgo(iso) {
    if (!iso) return '';
    const d = new Date(iso + (iso.includes('Z') ? '' : 'Z'));
    const s = Math.floor((Date.now() - d) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s/60) + 'm ago';
    if (s < 86400) return Math.floor(s/3600) + 'h ago';
    return Math.floor(s/86400) + 'd ago';
}

// ─── Init ──────────────────────
loadDashboard();
checkAI();
