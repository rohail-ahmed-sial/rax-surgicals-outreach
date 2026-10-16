'use strict';
/* RAX Surgicals Outreach dashboard: shared helpers (translation, API calls, formatting, overlays, router, sidebar).
   Plain JavaScript, no libraries, works offline. Every view lives in js/views/ and registers itself in R.views. */
(function () {
  const R = window.R = window.R || {};
  R.views = {};
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  Object.assign(R, { $, $$, esc });

  /* ---------- language ---------- */
  R.lang = 'en';
  const CODE = /^[a-z_]+(\.[a-z0-9_]+)+$/i;                    // keys such as err.offline need an entry; plain English does not
  R.has = k => k in R.I18N.en;
  R.t = (k, vars) => {
    let s = R.I18N.en[k];
    if (s === undefined) { if (window.__i18nMiss && CODE.test(k)) window.__i18nMiss.add(k); s = k; }   // the browser test reports these
    if (vars) for (const [a, b] of Object.entries(vars)) s = s.split('{' + a + '}').join(b ?? '');
    return s;
  };
  R.T = (k, vars) => esc(R.t(k, vars));                       // for HTML
  R.tn = (n, one, many, vars) => R.t(n === 1 ? one : many, Object.assign({ n: R.num(n) }, vars || {}));
  R.TN = (n, one, many, vars) => esc(R.tn(n, one, many, vars));

  /* ---------- numbers and dates ---------- */
  const nf = new Intl.NumberFormat('en-US');
  R.num = n => (n === null || n === undefined || n === '') ? '' : nf.format(n);
  R.money = (v, cur) => (v === null || v === undefined || v === '') ? '' : `${cur || 'USD'} ${new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(v)}`;
  R.pct = v => v === null || v === undefined ? '—' : `${String(v).replace(/\.0$/, '')}%`;
  const d8 = iso => { const d = iso ? new Date(iso) : null; return d && !isNaN(d) ? d : null; };
  R.fmtDate = iso => { const d = d8(iso.length === 10 ? iso + 'T00:00:00' : iso); return d ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : ''; };
  R.fmtDay = iso => { const d = d8(iso.length === 10 ? iso + 'T00:00:00' : iso); return d ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''; };
  R.fmtTime = iso => { const d = d8(iso); return d ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''; };
  R.fmtDT = iso => { const d = d8(iso); return d ? d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''; };
  R.ago = iso => {
    const d = d8(iso); if (!d) return '';
    const s = (Date.now() - d) / 1000, a = Math.abs(s);
    let v, u;
    if (a < 60) return s >= 0 ? R.t('just now') : R.t('in a moment');
    if (a < 3600) { v = Math.round(a / 60); u = 'min'; }
    else if (a < 86400) { v = Math.round(a / 3600); u = v === 1 ? 'hour' : 'hours'; }
    else { v = Math.round(a / 86400); u = v === 1 ? 'day' : 'days'; }
    return R.t(s >= 0 ? '{v} ' + u + ' ago' : 'in {v} ' + u, { v });
  };
  R.todayISO = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
  R.size = b => b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB';

  /* ---------- API ---------- */
  R.ApiError = class extends Error { constructor(m, code, data) { super(m); this.code = code; this.data = data; } };
  R.api = async (method, path, body, opts = {}) => {
    const init = { method, headers: { 'X-Requested-With': 'rax' } };
    if (body instanceof Blob || body instanceof ArrayBuffer) {
      init.body = body; init.headers['Content-Type'] = opts.type || 'application/octet-stream';
      if (opts.name) init.headers['X-File-Name'] = encodeURIComponent(opts.name);
    } else if (body !== undefined) { init.body = JSON.stringify(body); init.headers['Content-Type'] = 'application/json'; }
    let r;
    try { r = await fetch(path, init); }
    catch (e) { throw new R.ApiError(R.t('err.offline'), 'offline'); }
    if (r.status === 401 && path !== '/api/login') { R.showLogin(); throw new R.ApiError(R.t('err.login'), 'login'); }
    const ct = r.headers.get('content-type') || '';
    const data = ct.includes('json') ? await r.json() : await r.text();
    if (!r.ok) throw new R.ApiError((data && data.error) || 'Request failed', data && data.code, data && data.data);
    return data;
  };
  R.get = p => R.api('GET', p);
  R.post = (p, b = {}) => R.api('POST', p, b);
  R.patch = (p, b) => R.api('PATCH', p, b);
  R.del = (p, b) => R.api('DELETE', p, b);
  R.errText = e => (e && e.code && R.has('err.' + e.code)) ? R.t('err.' + e.code, e.data && !Array.isArray(e.data) ? e.data : undefined) : ((e && e.message) || String(e));

  /* ---------- toasts and busy buttons ---------- */
  R.toast = (msg, kind, action) => {
    const t = document.createElement('div');
    t.className = 'toast' + (kind === 'err' ? ' toast--err' : '');
    t.innerHTML = `<span>${esc(msg)}</span>` + (action ? `<button>${esc(action.label)}</button>` : '');
    if (action) $('button', t).onclick = () => { t.remove(); action.fn(); };
    $('#toasts').append(t);
    setTimeout(() => t.remove(), kind === 'err' ? 9000 : action ? 7000 : 4000);
  };
  R.fail = e => { if (!(e && e.code === 'login')) R.toast(R.errText(e), 'err'); };
  /* run an async action; while it runs the button shows a spinner; errors become a red toast */
  R.run = async (btn, fn, okMsg) => {
    if (btn && btn.classList.contains('is-busy')) return;
    if (btn) btn.classList.add('is-busy');
    try {
      const r = await fn();
      if (okMsg) R.toast(typeof okMsg === 'function' ? okMsg(r) : okMsg);
      return r;
    } catch (e) { R.fail(e); throw e; }
    finally { if (btn) btn.classList.remove('is-busy'); }
  };
  R.quiet = p => p.catch(() => {});

  /* ---------- icons and small pieces ---------- */
  R.icon = (name, cls = '') => `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  R.pill = (text, kind = '') => `<span class="pill ${kind ? 'pill--' + kind : ''}">${esc(text)}</span>`;
  R.fitPill = (fit, score) => fit ? R.pill(R.t('fit.' + fit) + (score !== null && score !== undefined ? ' ' + score : ''), fit === 'good' ? 'good' : fit === 'maybe' ? 'maybe' : 'bad')
    : R.pill(R.t('not checked'));
  R.statusPill = s => R.pill(R.t('status.' + s), { ready: 'blue', replied: 'good', in_campaign: '', rejected: 'bad', bounced: 'bad', unsubscribed: 'bad', not_interested: 'bad' }[s] || '');
  R.kindPill = k => R.pill(R.t('kind.' + k), { interested: 'good', question: 'good', not_interested: 'bad', unsubscribe: 'bad', bounce: 'bad', wrong_person: 'warn' }[k] || '');
  R.stagePill = s => s ? R.pill(R.t('stage.' + s), { won: 'good', lost: 'bad' }[s] || 'blue') : '';
  R.emailMark = st => {
    const m = { valid: ['check', 'var(--emerald-ink)', 'email.valid'], free: ['info', 'var(--ink-3)', 'email.free'], no_mx: ['alert', 'var(--danger)', 'email.no_mx'],
                invalid: ['alert', 'var(--danger)', 'email.invalid'], unknown: ['help', 'var(--ink-3)', 'email.unknown'] }[st];
    return m ? `<span class="estat" title="${R.T(m[2])}" style="color:${m[1]}">${R.icon(m[0], 'ic--sm')}</span>` : '';
  };
  R.logo = () => '<svg viewBox="0 0 40 40" aria-hidden="true"><use href="#logo-mark"/></svg>';
  // Company initials in a small circle: makes long lists of companies easier to scan.
  R.avatar = (name, cls = '') => {
    const words = String(name || '?').replace(/[^\p{L}\p{N} ]/gu, ' ').split(/\s+/).filter(w => w && !/^(the|and|of|gmbh|ltd|llc|inc|co|sa|srl|bv|ag)$/i.test(w));
    const ini = ((words[0] || '?')[0] + (words[1] ? words[1][0] : (words[0] || '').slice(1, 2))).toUpperCase();
    return `<span class="avatar ${cls}" aria-hidden="true">${esc(ini)}</span>`;
  };
  R.empty = ({ title, text, action, icon = 'instrument' }) => `<div class="empty"><span class="empty__icon">${icon === 'instrument'
      ? '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><use href="#i-instrument"/></svg>' : R.icon(icon)}</span>
    <h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ''}${action ? (action.href ? `<a class="btn btn--primary" href="${action.href}">${esc(action.label)}</a>` : `<button class="btn btn--primary" id="${action.id}">${esc(action.label)}</button>`) : ''}</div>`;
  R.lintList = lint => lint && lint.length ? `<ul class="lint">${lint.map(f => `<li class="${f.level}">${R.T('lint.' + f.code, f.data)}</li>`).join('')}</ul>` : '';
  // Website text is stored as one line per page: "[/path] Title | text". Split it back into pages for display.
  R.siteParts = s => String(s || '').split('\n').map(line => {
    const m = line.match(/^\[(\/[^\]]{0,300})\]\s*(.*)$/);
    return m ? { path: m[1], text: m[2].trim() } : { path: '', text: line.trim() };
  }).filter(p => p.text);
  R.siteText = (s, max) => {
    let left = max || 1e9;
    return R.siteParts(s).map(p => {
      if (left <= 0) return '';
      const txt = p.text.length > left ? p.text.slice(0, left).replace(/\s+\S*$/, '') + '…' : p.text;
      left -= txt.length;
      return `<div class="sitepart">${p.path ? `<small>${R.esc(p.path === '/' ? R.t('Home page') : p.path)}</small>` : ''}<p>${R.esc(txt)}</p></div>`;
    }).join('');
  };
  R.note = (html, kind = '') => `<div class="note ${kind ? 'note--' + kind : ''}">${R.icon(kind === 'good' ? 'check' : kind === 'info' ? 'info' : 'alert')}<div>${html}</div></div>`;
  R.countryName = c => c || '—';

  /* ---------- overlays: drawer, modal, confirm, prompt ---------- */
  const stack = [];
  R.overlay = (html, { kind = 'modal', wide = false, onClose } = {}) => {
    const o = document.createElement('div');
    o.className = 'overlay';
    o.innerHTML = `<div class="scrim" data-close></div><div class="${kind}${wide ? ' modal--wide' : ''}" role="dialog" aria-modal="true">
      <button class="x" data-close aria-label="${R.T('Close')}">${R.icon('x')}</button>${html}</div>`;
    $('#overlays').append(o);
    const close = () => { if (!o.isConnected) return; o.remove(); stack.splice(stack.indexOf(o), 1); onClose && onClose(); };
    o._close = close;
    o.addEventListener('click', e => { if (e.target.closest('[data-close]')) close(); });
    stack.push(o);
    setTimeout(() => { const f = $('input:not([type=hidden]):not([readonly]), textarea, select, .btn--primary', o.lastElementChild); if (f && kind === 'modal') f.focus(); }, 30);
    return o;
  };
  R.closeTop = () => { const o = stack[stack.length - 1]; if (o) o._close(); };
  R.closeAll = () => [...stack].forEach(o => o._close());
  R.drawer = (html, opts = {}) => R.overlay(html, Object.assign({ kind: 'drawer' }, opts));
  R.modal = (html, opts = {}) => R.overlay(html, Object.assign({ kind: 'modal' }, opts));
  R.confirm = (title, text, { ok = R.t('Yes'), danger = false } = {}) => new Promise(res => {
    let done = false;
    const o = R.modal(`<h2>${esc(title)}</h2>${text ? `<p class="muted">${esc(text)}</p>` : ''}
      <div class="row" style="margin-top:18px"><button class="btn ${danger ? 'btn--danger' : 'btn--primary'}" data-ok>${esc(ok)}</button><button class="btn" data-close>${R.T('Cancel')}</button></div>`,
      { onClose: () => { if (!done) res(false); } });
    $('[data-ok]', o).onclick = () => { done = true; o._close(); res(true); };
    setTimeout(() => $('[data-ok]', o).focus(), 40);
  });
  R.ask = (title, { text = '', value = '', placeholder = '', chips = [], ok = R.t('OK'), multiline = false } = {}) => new Promise(res => {
    let done = false;
    const o = R.modal(`<h2>${esc(title)}</h2>${text ? `<p class="muted">${esc(text)}</p>` : ''}
      ${chips.length ? `<div class="chips" style="margin:10px 0 12px">${chips.map(c => `<button class="chip" data-chip="${esc(c)}">${esc(c)}</button>`).join('')}</div>` : ''}
      ${multiline ? `<textarea data-in placeholder="${esc(placeholder)}">${esc(value)}</textarea>` : `<input data-in value="${esc(value)}" placeholder="${esc(placeholder)}">`}
      <div class="row" style="margin-top:16px"><button class="btn btn--primary" data-ok>${esc(ok)}</button><button class="btn" data-close>${R.T('Cancel')}</button></div>`,
      { onClose: () => { if (!done) res(null); } });
    const inp = $('[data-in]', o);
    $$('[data-chip]', o).forEach(c => c.onclick = () => { c.classList.toggle('on'); const on = $$('.chip.on', o).map(x => x.dataset.chip); inp.value = on.join(', '); });
    const ok_ = () => { done = true; o._close(); res(inp.value.trim()); };
    $('[data-ok]', o).onclick = ok_;
    if (!multiline) inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); ok_(); } });
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && stack.length) { e.preventDefault(); R.closeTop(); } });

  /* ---------- theme ---------- */
  const mq = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
  R.themeMode = () => { try { return localStorage.getItem('rax-theme') || 'system'; } catch (e) { return 'system'; } };
  R.applyTheme = () => {
    const m = R.themeMode();
    const dark = m === 'dark' || (m === 'system' && mq && mq.matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    const b = $('#theme-btn');
    if (b) { b.innerHTML = R.icon(dark ? 'sun' : 'moon'); b.title = R.t(dark ? 'Light mode' : 'Dark mode'); b.setAttribute('aria-label', b.title); }
    document.dispatchEvent(new Event('rax-theme'));
  };
  R.setTheme = m => { try { localStorage.setItem('rax-theme', m); } catch (e) {} R.applyTheme(); };
  if (mq && mq.addEventListener) mq.addEventListener('change', () => R.themeMode() === 'system' && R.applyTheme());
  R.isDark = () => document.documentElement.getAttribute('data-theme') === 'dark';

  /* ---------- router ---------- */
  R.state = { timers: [], badges: {} };
  R.every = (fn, ms) => { const id = setInterval(fn, ms); R.state.timers.push(id); return id; };
  R.parseHash = () => {
    const h = location.hash.replace(/^#\/?/, '');
    const [path, query] = h.split('?');
    const parts = path.split('/').filter(Boolean);
    return { name: parts[0] || 'today', parts, params: new URLSearchParams(query || '') };
  };
  R.go = hash => { if (location.hash === hash) R.route(); else location.hash = hash; };
  R.route = async () => {
    R.state.timers.forEach(clearInterval); R.state.timers = [];
    if (R.state.cleanup) { try { R.state.cleanup(); } catch (e) {} R.state.cleanup = null; }
    const { name, parts, params } = R.parseHash();
    const view = R.views[name] ? name : 'today';
    $$('#nav a, #tabbar a').forEach(a => a.classList.toggle('on', a.dataset.v === view));
    closeSide();
    const el = $('#view');
    el.innerHTML = '';
    el.setAttribute('data-view', view);
    window.scrollTo(0, 0);
    try {
      const c = await R.views[view].render(el, { parts, params });
      if (typeof c === 'function') R.state.cleanup = c;
    } catch (e) {
      if (e && e.code === 'login') return;
      el.innerHTML = `<div class="panel">${R.note(R.T('err.page') + '<br><small>' + esc(R.errText(e)) + '</small>', 'bad')}</div>`;
      console.error(e);
    }
    document.title = (R.state.badgeTitle || '') + R.t('nav.' + view) + ' · RAX Surgicals Outreach';
  };
  window.addEventListener('hashchange', R.route);

  /* ---------- sidebar, tab bar, badges ---------- */
  R.NAV = [
    { group: 'nav.g.work', items: [['today', 'today'], ['approve', 'approve', 'drafts'], ['inbox', 'inbox', 'inbox'], ['pipeline', 'pipeline', 'tasks']] },
    { group: 'nav.g.find', items: [['find', 'find'], ['leads', 'leads', 'ready'], ['campaigns', 'campaigns'], ['outbox', 'outbox']] },
    { group: 'nav.g.more', items: [['reports', 'reports'], ['activity', 'activity'], ['settings', 'settings'], ['help', 'help']] },
  ];
  const HOT = { drafts: true, inbox: true, tasks: true };
  R.buildNav = () => {
    $('#nav').innerHTML = R.NAV.map(g => `<div class="nav__group">${R.T(g.group)}</div>` + g.items.map(([v, ic, badge]) =>
      `<a href="#/${v}" data-v="${v}">${R.icon(ic)}<span>${R.T('nav.' + v)}</span>${badge ? `<b class="count ${HOT[badge] ? 'count--hot' : ''}" data-badge="${badge}"></b>` : ''}</a>`).join('')).join('');
    $('#tabbar').innerHTML = [['today', 'today'], ['approve', 'approve', 'drafts'], ['inbox', 'inbox', 'inbox'], ['leads', 'leads']].map(([v, ic, badge]) =>
      `<a href="#/${v}" data-v="${v}">${R.icon(ic)}<span>${R.T('nav.' + v)}</span>${badge ? `<b class="count" data-badge="${badge}"></b>` : ''}</a>`).join('')
      + `<button id="more-btn">${R.icon('menu')}<span>${R.T('More')}</span></button>`;
    $('#more-btn').onclick = openSide;
    $('#gsearch-input').placeholder = R.t('Search companies');
    $('#power-btn').title = R.t('Stop RAX Surgicals Outreach'); $('#power-btn').setAttribute('aria-label', R.t('Stop RAX Surgicals Outreach'));
    $('#logout-btn').title = R.t('Log out'); $('#logout-btn').setAttribute('aria-label', R.t('Log out'));
    $('#menu-btn').setAttribute('aria-label', R.t('Menu'));
    R.applyTheme();
    R.paintBadges();
    const { name } = R.parseHash();
    $$('#nav a, #tabbar a').forEach(a => a.classList.toggle('on', a.dataset.v === name));
  };
  R.paintBadges = () => {
    const b = R.state.badges || {};
    $$('[data-badge]').forEach(el => { const n = b[el.dataset.badge]; el.textContent = n ? (n > 99 ? '99+' : n) : ''; });
    const s = $('#sendstate');
    if (!s || b.email_ready === undefined) return;
    const cls = !b.email_ready ? 'pivot--warn' : b.paused ? (b.paused_reason === 'manual' ? 'pivot--warn' : 'pivot--bad') : 'pivot--on';
    const head = !b.email_ready ? R.t('Email not set up') : b.paused ? R.t('Sending paused') : R.t('Sending on');
    s.innerHTML = `<span class="pivot ${cls}"></span><span><b>${esc(head)}</b>${R.T('{a} of {b} sent today', { a: b.sent_today, b: b.limit })}${b.jobs_running ? '<br>' + R.T('Working in the background…') : ''}</span>`;
    const n = (b.drafts || 0) + (b.inbox || 0);
    R.state.badgeTitle = n ? `(${n}) ` : '';
    document.title = R.state.badgeTitle + document.title.replace(/^\(\d+\)\s*/, '');
  };
  R.refreshBadges = async () => {
    try {
      const b = await R.get('/api/badges');
      const prev = R.state.badges.last_reply;
      R.state.badges = b;
      R.paintBadges();
      if (prev && b.last_reply && b.last_reply.id !== prev.id) R.notifyReply(b.last_reply);
    } catch (e) { /* offline or logged out */ }
  };
  R.notifyReply = r => {
    R.toast(R.t('New reply from {who}', { who: r.from_email }), '', { label: R.t('Open'), fn: () => R.go('#/inbox/' + r.lead_id) });
    try {
      if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
        const n = new Notification(R.t('New reply from {who}', { who: r.from_email }), { body: r.summary || '', icon: '/img/icon.svg' });
        n.onclick = () => { window.focus(); R.go('#/inbox/' + r.lead_id); };
      }
    } catch (e) {}
  };
  const side = () => $('#side');
  function openSide() { side().classList.add('open'); if (!$('.side-scrim')) { const s = document.createElement('div'); s.className = 'side-scrim'; s.onclick = closeSide; document.body.append(s); } }
  function closeSide() { side() && side().classList.remove('open'); const s = $('.side-scrim'); if (s) s.remove(); }
  R.openSide = openSide; R.closeSide = closeSide;

  /* ---------- global company search ---------- */
  R.initSearch = () => {
    const inp = $('#gsearch-input'), box = $('#gsearch-results');
    let timer, items = [], on = -1;
    const paint = () => {
      box.hidden = !items.length && !inp.value.trim();
      box.innerHTML = items.length ? items.map((l, i) => `<button data-i="${i}" class="${i === on ? 'on' : ''}"><span>${esc(l.company)}</span><small class="muted">${esc([l.country, l.email].filter(Boolean).join(', '))}</small></button>`).join('')
        : `<div style="padding:10px 12px" class="muted">${R.T('No company found')}</div>`;
      $$('button', box).forEach(b => b.onmousedown = e => { e.preventDefault(); pick(+b.dataset.i); });
    };
    const pick = i => { const l = items[i]; if (!l) return; inp.value = ''; items = []; box.hidden = true; inp.blur(); closeSide(); R.openLead(l.id); };
    inp.addEventListener('input', () => {
      clearTimeout(timer);
      const q = inp.value.trim();
      if (!q) { items = []; box.hidden = true; return; }
      timer = setTimeout(async () => { try { items = (await R.get('/api/leads?per=20&sort=company&q=' + encodeURIComponent(q))).rows.slice(0, 8); on = 0; paint(); } catch (e) {} }, 180);
    });
    inp.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { on = Math.min(items.length - 1, on + 1); paint(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { on = Math.max(0, on - 1); paint(); e.preventDefault(); }
      else if (e.key === 'Enter') { pick(on); e.preventDefault(); }
      else if (e.key === 'Escape') { inp.value = ''; items = []; box.hidden = true; inp.blur(); }
    });
    inp.addEventListener('blur', () => setTimeout(() => { box.hidden = true; }, 150));
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (innerWidth <= 900) openSide(); inp.focus(); }
    });
  };

  /* ---------- typing helpers ---------- */
  R.typing = e => { const t = e.target; return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)); };
  R.debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  R.fileToB64 = f => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = rej; r.readAsDataURL(f); });
  R.copy = async text => { try { await navigator.clipboard.writeText(text); R.toast(R.t('Copied')); } catch (e) { R.toast(R.t('Could not copy'), 'err'); } };

  /* ---------- login ---------- */
  R.showLogin = () => {
    $('#shell').hidden = true; $('#tabbar').hidden = true; $('#mobilebar').hidden = true; $('#login').hidden = false;
    $('#login-title').textContent = R.t('Log in'); $('#login-lead').textContent = R.t('login.lead');
    $('#login-label').textContent = R.t('Password'); $('#login-btn').textContent = R.t('Log in');
    setTimeout(() => $('#login-form input').focus(), 50);
  };
})();
