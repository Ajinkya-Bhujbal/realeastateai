/* ─── LeadPilot Frontend App ─────────────────────── */
const API = '';
let currentLeadId = null;
let chatPollTimer = null;
let _lastSeenMsgId = null;

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

/** Render message content with media (images, videos, links) */
function renderMsgContent(content) {
    if (!content) return '';

    // [IMAGE:filename] → render as thumbnail
    const imgMatch = content.match(/^\[IMAGE:(.+?)\]$/);
    if (imgMatch) {
        const fname = imgMatch[1];
        // Determine subfolder: amenity or flat
        const isAmenity = fname.toLowerCase().includes('amenity') || fname.toLowerCase().includes('pool')
            || fname.toLowerCase().includes('gym') || fname.toLowerCase().includes('lounge')
            || fname.toLowerCase().includes('ground') || fname.toLowerCase().includes('kids')
            || fname.toLowerCase().includes('indoor') || fname.toLowerCase().includes('yoga')
            || fname.toLowerCase().includes('reading') || fname.toLowerCase().includes('work');
        const folder = isAmenity ? 'amenities' : 'flats';
        const src = fname.startsWith('incoming/') ? `/media/${fname}` : `/media/${folder}/${fname}`;
        return `<div class="wa-media-img" onclick='openMediaViewer(["[IMAGE:${fname}]"], 0)'>
            <img src="${src}" alt="${esc(fname)}" loading="lazy" />
        </div>`;
    }

    // [VIDEO:filename] → render as video player
    const vidMatch = content.match(/^\[VIDEO:(.+?)\]$/);
    if (vidMatch) {
        const fname = vidMatch[1];
        const src = fname.startsWith('incoming/') ? `/media/${fname}` : `/media/flats/${fname}`;
        return `<div class="wa-media-vid" onclick='openMediaViewer(["[VIDEO:${fname}]"], 0)'>
            <video src="${src}" preload="metadata" style="max-width:100%;border-radius:8px;"></video>
            <div class="wa-media-label">🎬 ${esc(fname)} (Click to play big)</div>
        </div>`;
    }

    // Regular text: escape, linkify URLs, and preserve newlines
    let safe = esc(content);
    // Linkify URLs
    safe = safe.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:#53bdeb;word-break:break-all;">$1</a>');
    // Bold: *text*
    safe = safe.replace(/\*([^*]+?)\*/g, '<strong>$1</strong>');
    // Preserve newlines
    safe = safe.replace(/\n/g, '<br>');
    return safe;
}

function timeAgo(iso) {
    if (!iso) return '';
    // Ensure we treat the timestamp as UTC
    let dateStr = iso;
    if (!dateStr.includes('Z') && !dateStr.includes('+')) dateStr += 'Z';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '';
    const s = Math.floor((Date.now() - d) / 1000);
    if (s < 0) return 'just now';
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    if (s < 2592000) return Math.floor(s / 86400) + 'd ago';  // up to 30 days
    if (s < 31536000) return Math.floor(s / 2592000) + 'mo ago';  // up to 12 months
    return Math.floor(s / 31536000) + 'y ago';
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
        if (view === 'quarantine') loadQuarantine();
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
                <div>
                    <div class="recent-lead-name">${esc(l.name)}</div>
                    <div class="recent-lead-meta">${l.source} &middot; ${timeAgo(l.created_at)}</div>
                    <div class="recent-lead-meta" style="color:var(--text-primary); margin-top:4px;">
                        ${l.price ? `<strong>${esc(l.price)}</strong> &middot; ` : ''}${esc(l.preferred_location || l.property_type || '')}
                    </div>
                </div>
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

// ─── WhatsApp Live Mode Toggle ──────────
async function loadWaGuard() {
    const d = await api('/api/wa/live-mode', { silent: true });
    if (!d) return;
    updateWaGuardUI(d.live_mode, d.whitelist);
}

function updateWaGuardUI(liveMode, whitelist) {
    const card = $('wa-guard-card');
    const toggle = $('wa-live-toggle');
    const desc = $('wa-guard-desc');
    const wlDiv = $('wa-guard-whitelist');

    toggle.checked = liveMode;
    if (liveMode) {
        card.classList.add('live');
        desc.innerHTML = '🟢 <strong>LIVE</strong> — Messages will be sent to <strong>ALL</strong> leads';
        desc.style.color = '#4ade80';
    } else {
        card.classList.remove('live');
        desc.innerHTML = '🔒 <strong>TEST MODE</strong> — Messages only sent to whitelisted numbers';
        desc.style.color = '#f87171';
    }

    if (whitelist && whitelist.length > 0) {
        wlDiv.innerHTML = '✅ Always-allowed numbers: ' +
            whitelist.map(p => `<span class="wl-phone">${p}</span>`).join('');
    } else {
        wlDiv.innerHTML = '⚠️ No whitelisted numbers. Add WA_WHITELIST_PHONES in .env file.';
    }
}

window.toggleLiveMode = async function(enabled) {
    if (enabled) {
        const confirmed = confirm(
            '⚠️ WARNING: Turning Live Mode ON will send WhatsApp messages to ALL leads!\n\n' +
            'Are you sure you want to enable this? Only do this when you are ready for production.'
        );
        if (!confirmed) {
            $('wa-live-toggle').checked = false;
            return;
        }
    }
    const d = await api('/api/wa/live-mode', {
        method: 'POST',
        body: { enabled: enabled }
    });
    if (d) {
        updateWaGuardUI(d.live_mode, d.whitelist);
        toast(d.message, enabled ? 'warning' : 'success');
    }
};

// Load WA guard status on dashboard load
const _origLoadDashboard = loadDashboard;
loadDashboard = async function() {
    await _origLoadDashboard();
    await loadWaGuard();
};

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
    if (d.leads.length === 0) { tb.innerHTML = '<tr><td colspan="10" class="empty-state">No leads found</td></tr>'; return; }
    tb.innerHTML = d.leads.map(l => {
        // Determine the "arrived" time — use updated_at (reflects latest email arrival) or created_at
        const arrivedAt = l.updated_at || l.created_at;
        // Build tag display — show DEALER/BROKER/OWNER as special badges
        const tagUpper = (l.tag || 'NEW').toUpperCase();
        const isSpecialTag = ['DEALER', 'BROKER', 'OWNER', 'DUPLICATE'].includes(tagUpper);
        const tagBadge = isSpecialTag
            ? `<span class="badge badge-role badge-${tagUpper.toLowerCase()}">${tagUpper}</span>`
            : '';
        // Email count badge (clickable to show details)
        const emailBadge = l.email_count > 1
            ? `<span class="email-count-badge" title="Click to see all ${l.email_count} emails" onclick="event.stopPropagation(); showEmailDetails(${l.id}, this)" style="cursor:pointer">📧${l.email_count}</span>`
            : (l.email_count === 1 ? `<span class="email-count-badge" title="Click to see email details" onclick="event.stopPropagation(); showEmailDetails(${l.id}, this)" style="cursor:pointer">📧1</span>` : '');
        return `
        <tr>
            <td><strong>${esc(l.name)}</strong>${tagBadge}${emailBadge}${l.email ? '<br><span style="font-size:11px;color:var(--text-muted)">' + esc(l.email) + '</span>' : ''}</td>
            <td>${esc(l.phone || '-')}</td>
            <td><span class="source-badge">${l.source}</span></td>
            <td>${esc(l.configuration || l.property_type || '-')}</td>
            <td>${esc(l.price || (l.budget_min || l.budget_max ? (l.budget_min || '?') + '-' + (l.budget_max || '?') + 'L' : '-'))}</td>
            <td>${esc(l.preferred_location || '-')}</td>
            <td class="time-ago-cell" data-created="${arrivedAt || ''}" style="font-size:12px;color:var(--text-secondary)">${timeAgo(arrivedAt)}</td>
            <td style="text-align:center">
                <input type="checkbox" class="welcome-cb" ${l.welcome_sent ? 'checked' : ''}
                    onclick="toggleWelcome(${l.id}, ${l.welcome_sent ? 'true' : 'false'}, '${esc(l.phone || '')}')"
                    title="${l.welcome_sent ? 'Welcome sent ✓' : 'Click to send welcome sequence'}"
                    style="cursor:pointer;width:18px;height:18px;accent-color:#22c55e;" />
            </td>
            <td>
                <select class="input tag-select" onchange="updateTag(${l.id}, this)">
                    <option value="NEW" ${l.tag === 'NEW' ? 'selected' : ''}>NEW</option>
                    <option value="DUPLICATE" ${l.tag === 'DUPLICATE' ? 'selected' : ''}>DUPLICATE</option>
                    <option value="DEALER" ${l.tag === 'DEALER' ? 'selected' : ''}>DEALER</option>
                    <option value="BROKER" ${l.tag === 'BROKER' ? 'selected' : ''}>BROKER</option>
                    <option value="OWNER" ${l.tag === 'OWNER' ? 'selected' : ''}>OWNER</option>
                    <option value="visited" ${l.tag === 'visited' ? 'selected' : ''}>Visited</option>
                    <option value="interested" ${l.tag === 'interested' ? 'selected' : ''}>Interested</option>
                    <option value="not interested" ${l.tag === 'not interested' ? 'selected' : ''}>Not Interested</option>
                    ${!['NEW', 'DUPLICATE', 'DEALER', 'BROKER', 'OWNER', 'visited', 'interested', 'not interested'].includes(l.tag || 'NEW') ? `<option value="${esc(l.tag)}" selected>${esc(l.tag)}</option>` : ''}
                    <option value="_custom">+ Custom Tag...</option>
                </select>
            </td>
            <td class="action-btns">
                <button class="action-btn" onclick="viewLead(${l.id})">View</button>
                ${l.welcome_sent ? `<button class="action-btn reengage" onclick="reEngageLead(${l.id}, '${esc(l.name)}')" title="Send template message to re-open conversation">📩</button>` : ''}
                <button class="action-btn delete" onclick="deleteLead(${l.id})">Del</button>
            </td>
        </tr>`;
    }).join('');
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

// Show all email inquiries for a lead in a floating dropdown
window.showEmailDetails = async function (leadId, badgeEl) {
    // Close any existing dropdown
    const existing = document.querySelector('.email-details-dropdown');
    if (existing) existing.remove();

    const d = await api(`/api/leads/${leadId}/emails`);
    if (!d || !d.emails || d.emails.length === 0) {
        toast('No email details found', 'info');
        return;
    }

    const dropdown = document.createElement('div');
    dropdown.className = 'email-details-dropdown';

    const header = `<div class="edd-header">
        <span>📧 ${d.emails.length} Email${d.emails.length > 1 ? 's' : ''} Received</span>
        <button class="edd-close" onclick="this.closest('.email-details-dropdown').remove()">✕</button>
    </div>`;

    const rows = d.emails.map((em, idx) => {
        const tagLabel = em.tag ? `<span class="badge badge-role badge-${em.tag.toLowerCase()}">${em.tag}</span>` : '';
        return `<div class="edd-item ${idx === 0 ? 'edd-latest' : ''}">
            ${idx === 0 ? '<span class="edd-latest-label">Latest</span>' : `<span class="edd-idx">#${idx + 1}</span>`}
            <div class="edd-row"><span class="edd-label">Subject:</span> <span class="edd-val">${esc((em.subject || '').substring(0, 80))}${(em.subject || '').length > 80 ? '…' : ''}</span></div>
            <div class="edd-row"><span class="edd-label">Source:</span> <span class="source-badge">${esc(em.source || '-')}</span> ${tagLabel}</div>
            <div class="edd-row"><span class="edd-label">Config:</span> ${esc(em.configuration || '-')} &nbsp;|&nbsp; <span class="edd-label">Price:</span> ${esc(em.price || '-')}</div>
            <div class="edd-row"><span class="edd-label">Location:</span> ${esc(em.preferred_location || '-')}</div>
            <div class="edd-row"><span class="edd-label">Arrived:</span> <span style="color:var(--cyan)">${timeAgo(em.received_at)}</span></div>
            ${em.notes ? `<div class="edd-row edd-notes"><span class="edd-label">Notes:</span> ${esc(em.notes.substring(0, 120))}${em.notes.length > 120 ? '…' : ''}</div>` : ''}
        </div>`;
    }).join('');

    dropdown.innerHTML = header + '<div class="edd-body">' + rows + '</div>';
    document.body.appendChild(dropdown);

    // Position near the badge
    const rect = badgeEl.getBoundingClientRect();
    const dropW = 380;
    const dropH = Math.min(d.emails.length * 170 + 50, 400);
    let left = rect.left + rect.width / 2 - dropW / 2;
    let top = rect.bottom + 8;
    // Keep within viewport
    if (left < 8) left = 8;
    if (left + dropW > window.innerWidth - 8) left = window.innerWidth - dropW - 8;
    if (top + dropH > window.innerHeight - 8) top = rect.top - dropH - 8;
    dropdown.style.left = left + 'px';
    dropdown.style.top = top + 'px';

    // Close on outside click
    setTimeout(() => {
        const closeHandler = (e) => {
            if (!dropdown.contains(e.target) && e.target !== badgeEl) {
                dropdown.remove();
                document.removeEventListener('click', closeHandler);
            }
        };
        document.addEventListener('click', closeHandler);
    }, 100);
};
window.deleteLead = async function (id) {
    if (!confirm('Delete this lead?')) return;
    await api(`/api/leads/${id}`, { method: 'DELETE' });
    toast('Lead deleted');
    loadLeads();
};

window.reEngageLead = async function (id, name) {
    if (!confirm(`Send re-engagement template to "${name}"?\n\nThis sends the WhatsApp template message to re-open the conversation window.`)) return;
    const r = await api(`/api/leads/${id}/force-welcome`, {
        method: 'POST',
        body: { re_engage: true }
    });
    if (r && r.status === 'ok') {
        toast('📩 Re-engagement template sent!');
    } else {
        toast(r?.error || 'Failed to send', 'error');
    }
};

window.updateTag = async function (id, selectEl) {
    let tagValue = selectEl.value;
    if (tagValue === '_custom') {
        const customTag = prompt('Enter custom tag name:');
        if (!customTag || !customTag.trim()) {
            selectEl.value = 'NEW'; // reset
            return;
        }
        tagValue = customTag.trim();
        // Add new option and select it
        const opt = document.createElement('option');
        opt.value = tagValue;
        opt.text = tagValue;
        selectEl.add(opt, selectEl.options[selectEl.options.length - 1]);
        selectEl.value = tagValue;
    }
    
    await api(`/api/leads/${id}`, {
        method: 'PUT',
        body: { tag: tagValue }
    });
    toast('Tag updated');
};

window.toggleWelcome = async function (leadId, alreadySent, phone) {
    if (!phone || phone === '-') {
        toast('No phone number for this lead', 'error');
        return;
    }
    if (alreadySent) {
        // Already sent — offer to re-engage
        if (!confirm('Welcome already sent. Send a re-engagement message?\n(WhatsApp requires 24hr gap between template messages)')) {
            loadLeads(); // reset checkbox
            return;
        }
        const r = await api(`/api/leads/${leadId}/force-welcome`, { method: 'POST', body: { re_engage: true } });
        if (r && r.status === 'ok') {
            toast('Re-engagement message queued!');
        } else {
            toast(r?.error || 'Failed to send', 'error');
        }
    } else {
        // Not sent — send welcome sequence
        if (!confirm('Send welcome sequence with photos & videos to this lead?')) {
            loadLeads(); // reset checkbox
            return;
        }
        const r = await api(`/api/leads/${leadId}/force-welcome`, { method: 'POST', body: { re_engage: false } });
        if (r && r.status === 'ok') {
            toast('Welcome sequence started! Photos & videos sending...');
        } else {
            toast(r?.error || 'Failed to send', 'error');
        }
    }
    setTimeout(loadLeads, 2000);
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
    if (currentLeadId !== leadId) _lastSeenMsgId = null; // reset on chat switch
    currentLeadId = leadId;

    // Mark as read
    await api(`/api/chats/${leadId}/read`, { method: 'POST' });

    // Load messages
    console.log("Fetching messages for lead:", leadId);
    const d = await api(`/api/chats/${leadId}`);
    if (!d) {
        console.error("Failed to fetch messages for lead:", leadId);
        return;
    }
    console.log(`Loaded ${d.messages ? d.messages.length : 0} messages`);

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

    // Welcome re-send button status
    const welcomeBtn = $('btn-resend-welcome');
    if (d.media_sent) {
        welcomeBtn.style.opacity = '0.5';
        welcomeBtn.title = 'Welcome sequence already sent. Click to queue re-send.';
    } else {
        welcomeBtn.style.opacity = '1';
        welcomeBtn.title = 'Welcome sequence queued — will send on next reply';
    }

    // Render messages with media gallery clustering
    const box = $('wa-messages');
    if (!d.messages || d.messages.length === 0) {
        box.innerHTML = '<div class="wa-empty-chat"><div class="wa-empty-icon">💬</div><h3>No messages</h3><p>Send a message to start the conversation</p></div>';
    } else {
        let html = '';
        let lastDate = '';
        const msgs = d.messages;
        let i = 0;
        while (i < msgs.length) {
            const m = msgs[i];
            const msgDate = m.created_at ? new Date(m.created_at + (m.created_at.includes('Z') ? '' : 'Z')).toLocaleDateString() : '';
            if (msgDate && msgDate !== lastDate) {
                html += `<div class="wa-date-divider">${msgDate}</div>`;
                lastDate = msgDate;
            }

            // Check if this is a media message
            const isMedia = m.content && (m.content.match(/^\[IMAGE:.+\]$/) || m.content.match(/^\[VIDEO:.+\]$/));

            if (isMedia) {
                // Collect consecutive media messages with same direction
                const mediaGroup = [];
                while (i < msgs.length) {
                    const mc = msgs[i];
                    if (mc.content && (mc.content.match(/^\[IMAGE:.+\]$/) || mc.content.match(/^\[VIDEO:.+\]$/)) && mc.direction === m.direction) {
                        mediaGroup.push(mc);
                        i++;
                    } else break;
                }
                // Render as gallery (Show ALL items, with data attribute for lightbox)
                const groupKey = encodeURIComponent(JSON.stringify(mediaGroup.map(x => x.content)));
                html += `<div class="wa-msg-bubble ${m.direction} wa-media-gallery-bubble">`;
                html += `<div class="wa-media-gallery" data-media-group="${groupKey}">`;
                mediaGroup.forEach((mc, idx) => {
                    const imgMatch = mc.content.match(/^\[IMAGE:(.+?)\]$/);
                    const vidMatch = mc.content.match(/^\[VIDEO:(.+?)\]$/);
                    if (imgMatch) {
                        const fname = imgMatch[1];
                        const fl = fname.toLowerCase();
                        const isAmenity = fl.includes('amenity') || fl.includes('pool') || fl.includes('gym')
                            || fl.includes('lounge') || fl.includes('ground') || fl.includes('kids')
                            || fl.includes('indoor') || fl.includes('yoga') || fl.includes('reading') || fl.includes('work')
                            || fl.includes('multipurpose');
                        const folder = isAmenity ? 'amenities' : 'flats';
                        const src = fname.startsWith('incoming/') ? `/media/${fname}` : `/media/${folder}/${fname}`;
                        html += `<div class="wa-gallery-item" data-idx="${idx}">
                            <img src="${src}" alt="${esc(fname)}" loading="lazy" />
                        </div>`;
                    } else if (vidMatch) {
                        const fname = vidMatch[1];
                        const src = fname.startsWith('incoming/') ? `/media/${fname}` : `/media/flats/${fname}`;
                        html += `<div class="wa-gallery-item" data-idx="${idx}">
                            <video src="${src}" preload="metadata"></video>
                            <div class="wa-gallery-play">▶</div>
                        </div>`;
                    }
                });
                html += `</div>`;
                html += `<div class="wa-msg-time">${formatTime(m.created_at)}</div></div>`;
            } else {
                // Normal text message
                html += `<div class="wa-msg-bubble ${m.direction}">
                    ${renderMsgContent(m.content)}
                    <div class="wa-msg-time">${formatTime(m.created_at)}</div>
                </div>`;
                i++;
            }
        }
        box.innerHTML = html;
        box.scrollTop = box.scrollHeight;
        // Defer scroll to after images/videos load (they change scrollHeight)
        setTimeout(() => { box.scrollTop = box.scrollHeight; }, 100);
        setTimeout(() => { box.scrollTop = box.scrollHeight; }, 500);
        box.querySelectorAll('img, video').forEach(el => {
            el.addEventListener('load', () => { box.scrollTop = box.scrollHeight; }, { once: true });
            el.addEventListener('loadedmetadata', () => { box.scrollTop = box.scrollHeight; }, { once: true });
        });

        // Track the last seen message ID so the poller knows when something is new
        if (msgs.length > 0) _lastSeenMsgId = msgs[msgs.length - 1].id;
    }

    // Refresh sidebar contact list (does NOT re-render the chat, no flash)
    loadChats();
};

// Send message
$('btn-wa-send').addEventListener('click', sendChatMessage);
$('wa-msg-input').addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMessage(); });

// ─── Gallery Lightbox: Event Delegation ───────────────────────────────────
// Handles clicks on gallery items AND standalone media in wa-messages
$('wa-messages').addEventListener('click', e => {
    // 1. Gallery item click
    const item = e.target.closest('.wa-gallery-item');
    if (item) {
        const gallery = item.closest('.wa-media-gallery');
        if (gallery) {
            const groupKey = gallery.getAttribute('data-media-group');
            if (groupKey) {
                const idx = parseInt(item.getAttribute('data-idx') || '0', 10);
                try {
                    const contents = JSON.parse(decodeURIComponent(groupKey));
                    openMediaViewer(contents, idx);
                } catch (err) {
                    console.error('Gallery open error:', err);
                }
                return;
            }
        }
    }

    // 2. Standalone image click (from renderMsgContent)
    const imgEl = e.target.closest('.wa-media-img');
    if (imgEl) {
        const img = imgEl.querySelector('img');
        if (img) {
            const src = img.getAttribute('src') || '';
            // Extract filename from src like /media/amenities/fname.jpg
            const fname = src.split('/').pop();
            const isAmenity = src.includes('/amenities/');
            const token = `[IMAGE:${fname}]`;
            openMediaViewer([token], 0);
            return;
        }
    }

    // 3. Standalone video click (from renderMsgContent)
    const vidEl = e.target.closest('.wa-media-vid');
    if (vidEl) {
        const vid = vidEl.querySelector('video');
        if (vid) {
            const src = vid.getAttribute('src') || '';
            const fname = src.split('/').pop();
            const token = `[VIDEO:${fname}]`;
            openMediaViewer([token], 0);
            return;
        }
    }
});

let currentFile = null;
if ($('btn-wa-attach')) {
    $('btn-wa-attach').addEventListener('click', () => $('wa-file-input').click());
    $('wa-file-input').addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            currentFile = e.target.files[0];
            $('wa-file-preview').textContent = currentFile.name;
            $('wa-file-preview').style.display = 'block';
        } else {
            currentFile = null;
            $('wa-file-preview').style.display = 'none';
        }
    });
}

async function sendChatMessage() {
    if (!currentLeadId) return;
    const msg = $('wa-msg-input').value.trim();
    if (!msg && !currentFile) return;
    $('wa-msg-input').value = '';

    // Optimistic UI: append bubble immediately
    const box = $('wa-messages');
    const emptyChat = box.querySelector('.wa-empty-chat');
    if (emptyChat) emptyChat.remove();

    const bubble = document.createElement('div');
    bubble.className = 'wa-msg-bubble out';
    let displayMsg = msg;
    if (currentFile) displayMsg = `📎 ${currentFile.name}<br>` + msg;
    bubble.innerHTML = `${esc(displayMsg)}<div class="wa-msg-time">just now</div>`;
    box.appendChild(bubble);
    box.scrollTop = box.scrollHeight;

    if (currentFile) {
        const formData = new FormData();
        formData.append('file', currentFile);
        formData.append('message', msg);
        
        try {
            const res = await fetch(`/api/chats/${currentLeadId}/send-media`, {
                method: 'POST',
                body: formData
            });
            if (res.ok) toast('Media sent');
            else toast('Failed to send media', 'error');
        } catch (e) {
            toast('Failed to send media', 'error');
        }
        
        currentFile = null;
        $('wa-file-input').value = '';
        $('wa-file-preview').style.display = 'none';
    } else {
        const r = await api(`/api/chats/${currentLeadId}/send`, { method: 'POST', body: { lead_id: currentLeadId, message: msg } });
        if (r) toast('Sent');
    }
    
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

// Re-send welcome sequence
$('btn-resend-welcome').addEventListener('click', async () => {
    if (!currentLeadId) return;
    if (!confirm('Re-send the full welcome media sequence (photos + videos) on the next reply from this lead?')) return;
    const r = await api(`/api/chats/${currentLeadId}/reset-welcome`, { method: 'POST' });
    if (r) {
        $('btn-resend-welcome').style.opacity = '1';
        $('btn-resend-welcome').title = 'Welcome sequence queued — will send on next reply';
        toast('Welcome media sequence reset. It will re-send on the next reply from this lead.');
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
    if (r) {
        toast('Incoming message simulated!');
        hide($('simulate-modal'));
        $('sim-phone').value = '';
        $('sim-message').value = '';

        // Open / refresh the chat for the lead that received the message
        await selectChat(r.lead_id);

        // Refresh again after 8s to catch any AI auto-reply that was generated
        setTimeout(async () => {
            if (currentLeadId === r.lead_id) await selectChat(r.lead_id);
        }, 8000);
    }
});

// Chat polling (every 45 seconds)
function startChatPolling() {
    stopChatPolling();
    chatPollTimer = setInterval(async () => {
        await loadChats();
        // If a chat is open, check for NEW messages by comparing last message ID
        if (currentLeadId) {
            const d = await api(`/api/chats/${currentLeadId}`, { silent: true });
            if (d && d.messages && d.messages.length > 0) {
                const latestId = d.messages[d.messages.length - 1].id;
                if (latestId !== _lastSeenMsgId) {
                    _lastSeenMsgId = latestId;
                    selectChat(currentLeadId);
                }
            }
        }
    }, 45000);  // 45 seconds
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

// ─── Quarantine ──────────────────────
async function loadQuarantine() {
    const d = await api('/api/quarantine');
    const stats = await api('/api/quarantine/stats', { silent: true });
    const tb = $('quarantine-tbody');
    const statsEl = $('quarantine-stats');

    // Update badge
    const badge = $('nav-quarantine-badge');
    const qCount = d ? d.total : 0;
    if (qCount > 0) { badge.textContent = qCount; badge.style.display = ''; }
    else { badge.style.display = 'none'; }

    // Stats header
    if (stats) {
        const byStatus = stats.by_status || {};
        statsEl.innerHTML = `
            <div class="quarantine-stat-row">
                <span class="quarantine-stat"><strong>${stats.total_raw_emails}</strong> total emails</span>
                <span class="quarantine-stat parsed"><strong>${byStatus.parsed || 0}</strong> parsed</span>
                <span class="quarantine-stat pending"><strong>${byStatus.pending || 0}</strong> pending</span>
                <span class="quarantine-stat warning"><strong>${byStatus.quarantined || 0}</strong> quarantined</span>
                <span class="quarantine-stat error"><strong>${byStatus.error || 0}</strong> errors</span>
            </div>`;
    }

    if (!d || d.total === 0) {
        tb.innerHTML = '<tr><td colspan="7" class="empty-state">No quarantined emails. All leads captured!</td></tr>';
        return;
    }

    tb.innerHTML = d.emails.map(e => {
        const p = e.parsed_data || {};
        const reasonBadge = e.status === 'error'
            ? '<span class="badge badge-error">ERROR</span>'
            : '<span class="badge badge-warning">NO PHONE</span>';
        return `
        <tr>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(e.subject || '')}">${esc(e.subject || '(no subject)')}</td>
            <td style="font-size:11px">${esc(e.sender || '-')}</td>
            <td>${esc(p.name || '-')}</td>
            <td>${esc(p.phone || '-')}</td>
            <td>${reasonBadge}<br><span style="font-size:11px;color:var(--text-muted)">${esc(e.quarantine_reason || '')}</span></td>
            <td style="font-size:12px">${timeAgo(e.received_at)}</td>
            <td class="action-btns">
                <button class="action-btn" onclick="reparseEmail(${e.id})">Re-parse</button>
            </td>
        </tr>`;
    }).join('');
}

window.reparseEmail = async function (rawId) {
    toast('Re-parsing...', 'info');
    const r = await api(`/api/quarantine/${rawId}/reparse`, { method: 'POST' });
    if (r && r.status === 'created') {
        toast(`Lead created: ${r.name} (${r.phone})`);
    } else if (r && r.status === 'still_quarantined') {
        toast('Still no phone found after re-parse', 'error');
    } else {
        toast('Re-parse failed', 'error');
    }
    loadQuarantine();
};

$('btn-reparse-all').addEventListener('click', async () => {
    if (!confirm('Re-parse ALL quarantined emails through the updated parser?')) return;
    toast('Re-parsing all...', 'info');
    const r = await api('/api/quarantine/reparse-all', { method: 'POST' });
    if (r) toast(`Re-processed ${r.reset_count} emails`);
    loadQuarantine();
    loadLeads();
    loadDashboard();
});

// Update quarantine badge on dashboard load
async function updateQuarantineBadge() {
    const d = await api('/api/quarantine/stats', { silent: true });
    if (!d) return;
    const qCount = (d.by_status?.quarantined || 0) + (d.by_status?.error || 0);
    const badge = $('nav-quarantine-badge');
    if (qCount > 0) { badge.textContent = qCount; badge.style.display = ''; }
    else { badge.style.display = 'none'; }
}

// ─── Init ──────────────────────
loadDashboard();
checkAI();
updateQuarantineBadge();

// ─── Background Polling ──────────────────
// Refresh dashboard and leads automatically every 15 seconds
setInterval(() => {
    if ($('view-dashboard').classList.contains('active')) {
        loadDashboard();
    }
    if ($('view-leads').classList.contains('active')) {
        loadLeads();
    }
}, 15000);

// ─── Live Time-Ago Updater ──────────────────────
// Updates all time-ago cells every 5 seconds so they stay current
setInterval(() => {
    document.querySelectorAll('.time-ago-cell[data-created]').forEach(cell => {
        const created = cell.getAttribute('data-created');
        if (created) cell.textContent = timeAgo(created);
    });
    // Also update dashboard recent leads
    document.querySelectorAll('.recent-lead-meta').forEach(meta => {
        const text = meta.textContent;
        // These get refreshed on dashboard reload, no action needed here
    });
}, 5000);

// ─── Media Viewer (Lightbox) ────────────────────
function _getMediaSrc(content) {
    const imgMatch = content.match(/^\[IMAGE:(.+?)\]$/);
    if (imgMatch) {
        const fname = imgMatch[1];
        const fl = fname.toLowerCase();
        const isAmenity = fl.includes('amenity') || fl.includes('pool') || fl.includes('gym')
            || fl.includes('lounge') || fl.includes('ground') || fl.includes('kids')
            || fl.includes('indoor') || fl.includes('yoga') || fl.includes('reading')
            || fl.includes('work') || fl.includes('multipurpose');
        return { type: 'image', src: `/media/${isAmenity ? 'amenities' : 'flats'}/${fname}`, name: fname };
    }
    const vidMatch = content.match(/^\[VIDEO:(.+?)\]$/);
    if (vidMatch) {
        return { type: 'video', src: `/media/flats/${vidMatch[1]}`, name: vidMatch[1] };
    }
    return null;
}

function openMediaViewer(mediaContents, startIdx) {
    // Remove existing viewer
    const existing = document.getElementById('media-viewer');
    if (existing) existing.remove();

    let currentIdx = startIdx || 0;
    const viewer = document.createElement('div');
    viewer.id = 'media-viewer';
    viewer.innerHTML = `
        <div class="mv-backdrop" onclick="document.getElementById('media-viewer').remove()"></div>
        <div class="mv-content">
            <button class="mv-close" onclick="document.getElementById('media-viewer').remove()">&times;</button>
            <button class="mv-prev" onclick="mvNav(-1)">‹</button>
            <div class="mv-display" id="mv-display"></div>
            <button class="mv-next" onclick="mvNav(1)">›</button>
            <div class="mv-counter" id="mv-counter"></div>
        </div>`;
    document.body.appendChild(viewer);

    function renderMedia() {
        const info = _getMediaSrc(mediaContents[currentIdx]);
        const display = document.getElementById('mv-display');
        if (info.type === 'image') {
            display.innerHTML = `<img src="${info.src}" alt="${info.name}" />`;
        } else {
            display.innerHTML = `<video src="${info.src}" controls autoplay></video>`;
        }
        document.getElementById('mv-counter').textContent = `${currentIdx + 1} / ${mediaContents.length}`;
    }

    window.mvNav = (dir) => {
        currentIdx = (currentIdx + dir + mediaContents.length) % mediaContents.length;
        renderMedia();
    };

    renderMedia();

    // Close on Escape
    const escHandler = (e) => {
        if (e.key === 'Escape') { viewer.remove(); document.removeEventListener('keydown', escHandler); }
        if (e.key === 'ArrowLeft') window.mvNav(-1);
        if (e.key === 'ArrowRight') window.mvNav(1);
    };
    document.addEventListener('keydown', escHandler);
}
