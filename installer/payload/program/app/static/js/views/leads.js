'use strict';
/* Leads: every company found. Quick views, filters, a table, and actions for many at once. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  const VIEWS = ['all', 'ready', 'needs_email', 'unchecked', 'in_campaign', 'replied', 'no_reply', 'bad_email', 'rejected'];
  const SOURCES = ['google_maps', 'import', 'csv', 'pasted', 'manual'];

  R.views.leads = {
    async render(el, { params }) {
      const f = { view: params.get('view') || 'all', q: params.get('q') || '', fit: params.get('fit') || '', country: '', source: '', sort: params.get('sort') || 'new', page: 1 };
      const sel = new Set();
      let data = null;
      el.innerHTML = `<div class="head"><div><h1>${T('nav.leads')}</h1><p>${T('leads.lead')}</p></div>
        <div class="head__actions"><a class="btn" href="/api/leads/export.csv">${R.icon('download')}${T('Export to Excel')}</a><a class="btn btn--primary" href="#/find">${R.icon('find')}${T('Find more')}</a></div></div>
        <div class="chips" id="views" style="margin-bottom:14px"></div>
        <div class="panel panel--flush"><form class="bar" id="bar" onsubmit="return false">
          <input type="search" name="q" placeholder="${T('Search name, email, city')}" value="${esc(f.q)}">
          <select name="fit"><option value="">${T('Any fit')}</option>${['good', 'maybe', 'no'].map(k => `<option value="${k}" ${f.fit === k ? 'selected' : ''}>${T('fit.' + k)}</option>`).join('')}</select>
          <select name="country"><option value="">${T('Any country')}</option></select>
          <select name="source"><option value="">${T('Any source')}</option>${SOURCES.map(k => `<option value="${k}">${T('source.' + k)}</option>`).join('')}</select>
          <span class="spacer"></span>
          <select name="sort" aria-label="${T('Sort')}">${[['new', 'Newest first'], ['score', 'Best fit first'], ['company', 'Name A to Z'], ['country', 'Country'], ['contact', 'Last contact']].map(([k, v]) => `<option value="${k}" ${f.sort === k ? 'selected' : ''}>${T(v)}</option>`).join('')}</select>
        </form><div id="selbar"></div><div class="tablewrap" id="tbl"><div style="padding:20px" class="muted">${T('Loading…')}</div></div><div id="pager"></div></div>`;
      const bar = $('#bar', el);
      const onFilter = R.debounce(() => { f.page = 1; R.quiet(load()); }, 250);
      bar.addEventListener('input', e => { f[e.target.name] = e.target.value; if (e.target.type === 'search') onFilter(); else { f.page = 1; R.quiet(load()); } });

      async function load() {
        const qs = new URLSearchParams(Object.entries(f).filter(([k, v]) => v && !(k === 'view' && v === 'all'))).toString();
        data = await R.get('/api/leads?' + qs);
        const cs = bar.country;
        if (cs.options.length <= 1) data.countries.forEach(c => cs.add(new Option(c, c)));
        $('#views', el).innerHTML = VIEWS.map(v => `<button class="chip ${f.view === v ? 'on' : ''}" data-view="${v}">${T('view.' + v)} <b>${R.num(data.counts[v] || 0)}</b></button>`).join('');
        $$('[data-view]', el).forEach(b => b.onclick = () => { f.view = b.dataset.view; f.page = 1; sel.clear(); R.quiet(load()); });
        const rows = data.rows;
        $('#tbl', el).innerHTML = rows.length ? `<table><thead><tr><th style="width:34px"><input type="checkbox" id="all" aria-label="${T('Select all')}"></th><th>${T('Company')}</th><th class="col-opt">${T('Place')}</th><th class="col-opt">${T('Email')}</th><th>${T('Fit')}</th><th>${T('Status')}</th><th class="col-opt">${T('Last contact')}</th></tr></thead><tbody>
          ${rows.map(l => `<tr class="click ${sel.has(l.id) ? 'sel' : ''}" data-id="${l.id}"><td><input type="checkbox" data-sel="${l.id}" ${sel.has(l.id) ? 'checked' : ''} aria-label="${T('Select')}"></td>
            <td class="co"><div class="co-av">${R.avatar(l.company, 'avatar--sm')}<div style="min-width:0">${esc(l.company)}<small class="muted ell" style="max-width:260px">${esc(l.domain || '')}</small><small class="muted show-sm">${esc([l.city, l.country].filter(Boolean).join(', '))}</small></div></div></td>
            <td class="col-opt">${esc(l.country || '—')}${l.city ? `<small class="muted" style="display:block">${esc(l.city)}</small>` : ''}</td>
            <td class="ell col-opt" style="max-width:260px">${l.email ? esc(l.email) + R.emailMark(l.email_status) : `<span class="faint">${T(l.crawl_status === 'pending' ? 'not read yet' : l.crawl_status === 'failed' ? 'website did not open' : 'none found')}</span>`}</td>
            <td>${R.fitPill(l.fit, l.score)}</td><td>${R.statusPill(l.status)} ${R.stagePill(l.stage)}</td>
            <td class="muted nowrap col-opt">${esc(l.last_contact_at ? R.ago(l.last_contact_at) : '')}</td></tr>`).join('')}</tbody></table>`
          : R.empty({ icon: f.view === 'all' && !f.q ? 'find' : 'leads', title: t(f.view === 'all' && !f.q ? 'No leads yet' : 'No leads match'), text: t(f.view === 'all' && !f.q ? 'Search Google Maps, paste a list of websites, or import a file.' : 'Try another view or clear the search.'),
                      action: f.view === 'all' && !f.q ? { label: t('Find leads'), href: '#/find' } : null });
        const pages = Math.ceil(data.total / data.per);
        $('#pager', el).innerHTML = `<div class="pager"><span class="muted">${R.TN(data.total, '1 lead', '{n} leads')}</span>${pages > 1 ? `<button class="btn btn--sm" data-p="-1" ${f.page <= 1 ? 'disabled' : ''}>${R.icon('left')}</button><span>${f.page} / ${pages}</span><button class="btn btn--sm" data-p="1" ${f.page >= pages ? 'disabled' : ''}>${R.icon('right')}</button>` : ''}</div>`;
        $$('[data-p]', el).forEach(b => b.onclick = () => { f.page += +b.dataset.p; R.quiet(load()); });
        $$('[data-sel]', el).forEach(c => c.onclick = e => { e.stopPropagation(); const id = +c.dataset.sel; c.checked ? sel.add(id) : sel.delete(id); c.closest('tr').classList.toggle('sel', c.checked); drawSel(); });
        const all = $('#all', el);
        if (all) all.onclick = () => { $$('[data-sel]', el).forEach(c => { c.checked = all.checked; const id = +c.dataset.sel; all.checked ? sel.add(id) : sel.delete(id); c.closest('tr').classList.toggle('sel', all.checked); }); drawSel(); };
        $$('tr.click', el).forEach(tr => tr.onclick = e => { if (!e.target.closest('input')) R.openLead(+tr.dataset.id, () => R.quiet(load())); });
        drawSel();
      }
      function drawSel() {
        const box = $('#selbar', el);
        if (!sel.size) { box.innerHTML = ''; return; }
        box.innerHTML = `<div class="selbar"><b>${R.TN(sel.size, '1 selected', '{n} selected')}</b>
          <button class="btn btn--sm btn--primary" data-b="campaign">${R.icon('campaigns')}${T('Add to campaign')}</button>
          <button class="btn btn--sm" data-b="check">${T('Read websites again')}</button>
          <button class="btn btn--sm" data-b="verify">${T('Check emails')}</button>
          <button class="btn btn--sm" data-b="nofit">${T('Mark as not a fit')}</button>
          <span class="spacer"></span><button class="btn btn--sm btn--danger" data-b="delete">${R.icon('trash')}${T('Delete')}</button>
          <button class="linkbtn" data-b="clear">${T('Clear')}</button></div>`;
        $$('[data-b]', box).forEach(b => b.onclick = () => bulk(b.dataset.b, b));
      }
      async function bulk(what, btn) {
        const ids = [...sel];
        if (what === 'clear') { sel.clear(); return R.quiet(load()); }
        if (what === 'campaign') return R.pickCampaign(ids, () => { sel.clear(); R.quiet(load()); });
        if (what === 'check') return R.run(btn, () => R.post('/api/leads/check', { ids }), r => R.tn(r.count, 'Checking 1 lead in the background', 'Checking {n} leads in the background'));
        if (what === 'verify') return R.run(btn, () => R.post('/api/leads/verify', { ids }), t('Checking the email addresses in the background'));
        if (what === 'nofit') {
          await R.run(btn, () => Promise.all(ids.map(id => R.patch('/api/leads/' + id, { fit: 'no', status: 'rejected' }))), t('Saved'));
          sel.clear(); return R.quiet(load());
        }
        if (what === 'delete') {
          if (!await R.confirm(R.tn(ids.length, 'Delete 1 lead?', 'Delete {n} leads?'), t('delete.leads.text'), { ok: t('Delete'), danger: true })) return;
          await R.run(btn, () => R.post('/api/leads/delete', { ids }), t('Deleted'));
          sel.clear(); R.quiet(load());
        }
      }
      await load();
      R.every(() => { if (!sel.size && !document.querySelector('.overlay')) R.quiet(load()); }, 20000);
    },
  };
})();
