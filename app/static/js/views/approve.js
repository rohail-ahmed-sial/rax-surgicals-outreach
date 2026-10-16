'use strict';
/* Approve: a review desk. The queue on the left, the email as a letter in the middle, the company on the right.
   Keys: J/K or arrows move, A approves, S skips, R rewrites, T sends a test to you, E edits, Ctrl+Enter approves while typing. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  const words = s => (String(s || '').match(/[\w'’-]+/g) || []).length;
  const worst = lint => (lint || []).some(f => f.level === 'block') ? 'block' : (lint || []).some(f => f.level === 'warn') ? 'warn' : '';

  R.views.approve = {
    async render(el) {
      let rows = [], footer = '', cur = 0, dirty = false;
      const sel = new Set();
      const load = async () => { const r = await R.get('/api/messages?status=draft'); rows = r.rows; footer = r.footer; };
      await load();

      const paint = () => {
        R.refreshBadges();
        if (!rows.length) {
          el.innerHTML = `<div class="head"><div><h1>${T('nav.approve')}</h1></div></div><div class="panel">${R.empty({ icon: 'approve', title: t('Nothing to approve'), text: t('When leads are in a campaign, their emails appear here for you to read first.'), action: { label: t('Open campaigns'), href: '#/campaigns' } })}</div>`;
          return;
        }
        cur = Math.max(0, Math.min(cur, rows.length - 1));
        const clean = rows.filter(m => !worst(m.lint)).length;
        el.innerHTML = `<div class="head"><div><h1>${T('nav.approve')}</h1><p>${T('approve.lead')}</p></div>
          <div class="head__actions"><button class="btn btn--ghost" id="keys">${R.icon('help')}${T('Keyboard')}</button>
          ${clean ? `<button class="btn" id="approve-clean">${R.icon('check')}${R.TN(clean, 'Approve the 1 email without warnings', 'Approve all {n} without warnings')}</button>` : ''}</div></div>
          <div class="desk">
            <div class="queue"><div class="queue__head"><b>${R.TN(rows.length, '1 waiting', '{n} waiting')}</b><span class="spacer"></span>
              <button class="btn btn--sm" id="sel-approve" ${sel.size ? '' : 'hidden'}>${T('Approve selected')}</button></div>
              <div class="queue__list">${rows.map((m, i) => {
                const w = worst(m.lint);
                return `<div class="qitem ${i === cur ? 'on' : ''}" data-i="${i}" role="button" tabindex="-1"><input type="checkbox" data-sel="${m.id}" ${sel.has(m.id) ? 'checked' : ''} aria-label="${T('Select')}">
                  <span style="flex:1;min-width:0"><b class="ell">${esc(m.company)}</b><small class="muted ell">${esc(m.country || '')}${m.country ? ', ' : ''}${T('email {a} of {b}', { a: m.step + 1, b: m.steps_total || 1 })}</small></span>
                  ${w ? `<span class="qflag" style="background:${w === 'block' ? 'var(--danger)' : 'var(--amber)'}" title="${T(w === 'block' ? 'Must be fixed' : 'Worth a look')}"></span>` : ''}</div>`; }).join('')}</div></div>
            <div id="letter"></div>
            <aside class="ctx" id="ctx"></aside>
          </div>`;
        $$('.qitem', el).forEach(q => q.onclick = async e => {
          if (e.target.matches('input')) return;
          await saveIfDirty(); cur = +q.dataset.i; paintLetter(); markQueue();
        });
        $$('[data-sel]', el).forEach(c => c.onchange = () => { c.checked ? sel.add(+c.dataset.sel) : sel.delete(+c.dataset.sel); $('#sel-approve', el).hidden = !sel.size; });
        $('#sel-approve', el).onclick = e => approveMany([...sel], e.currentTarget);
        const ac = $('#approve-clean', el);
        if (ac) ac.onclick = e => approveMany(rows.filter(m => !worst(m.lint)).map(m => m.id), e.currentTarget);
        $('#keys', el).onclick = keysHelp;
        paintLetter();
      };
      const markQueue = () => $$('.qitem', el).forEach(q => q.classList.toggle('on', +q.dataset.i === cur));

      const paintLetter = () => {
        const m = rows[cur]; if (!m) return;
        dirty = false;
        $('#letter', el).innerHTML = `<div class="letter">
          <div class="letter__top"><dl class="letter__meta"><dt>${T('To')}</dt><dd>${esc(m.to_email)} ${R.emailMark(m.email_status)}${m.contact_name ? ` <span class="muted">(${esc(m.contact_name)})</span>` : ''}</dd>
            <dt>${T('Campaign')}</dt><dd>${esc(m.campaign || '')} <span class="muted">${T('email {a} of {b}', { a: m.step + 1, b: m.steps_total || 1 })}${m.written_by === 'template' ? ', ' + T('from your template') : ''}</span></dd></dl>
            <div class="letter__nav"><button class="btn btn--sm btn--ghost" id="tst" title="${T('Send me a test')} (T)">${R.icon('mail')}<span class="hide-sm">${T('Test')}</span></button>
              <button class="btn btn--sm btn--ghost" id="prev" aria-label="${T('Previous')}" title="${T('Previous')} (K)" ${cur ? '' : 'disabled'}>${R.icon('left')}</button>
              <button class="btn btn--sm btn--ghost" id="next" aria-label="${T('Next')}" title="${T('Next')} (J)" ${cur < rows.length - 1 ? '' : 'disabled'}>${R.icon('right')}</button></div></div>
          <div class="letter__body"><input id="subj" value="${esc(m.subject)}" aria-label="${T('Subject')}" ${m.step > 0 ? 'readonly title="' + T('Follow-ups keep the subject of the first email, so they stay in one thread.') + '"' : ''}>
            <textarea id="body" aria-label="${T('Email text')}">${esc(m.body)}</textarea></div>
          <div class="letter__foot">${esc(footer)}</div>
          <div style="padding:0 20px"><div class="row"><span class="wc" id="wc"></span></div><div id="lint">${R.lintList(m.lint)}</div></div>
          <div class="letter__actions">
            <button class="btn btn--go" id="ok">${R.icon('check')}${T('Approve')} <kbd>A</kbd></button>
            <button class="btn" id="rw">${R.icon('spark')}${T('Rewrite')} <kbd>R</kbd></button>
            <span class="spacer"></span>
            <button class="btn btn--ghost btn--danger" id="skip">${T('Skip this company')} <kbd>S</kbd></button>
          </div></div>`;
        const body = $('#body', el), subj = $('#subj', el);
        const wc = () => { const n = words(body.value), max = m.step === 0 ? 150 : 100; $('#wc', el).innerHTML = T('{n} words', { n }) + (n > max ? ` <span style="color:var(--amber)">${T('(aim for under {max})', { max })}</span>` : ''); };
        wc();
        const grow = () => { body.style.height = 'auto'; body.style.height = Math.max(260, body.scrollHeight + 4) + 'px'; };
        grow();
        [body, subj].forEach(i => i.addEventListener('input', () => { dirty = true; wc(); grow(); }));
        body.addEventListener('blur', () => R.quiet(saveIfDirty()));
        subj.addEventListener('blur', () => R.quiet(saveIfDirty()));
        $('#ok', el).onclick = e => approveOne(e.currentTarget);
        $('#skip', el).onclick = () => skip();
        $('#rw', el).onclick = e => rewrite(e.currentTarget);
        $('#tst', el).onclick = e => test(e.currentTarget);
        $('#prev', el).onclick = () => move(-1);
        $('#next', el).onclick = () => move(1);
        paintCtx(m);
      };

      const paintCtx = m => {
        $('#ctx', el).innerHTML = `<div class="panel"><h3><button class="linkbtn" id="open-lead">${esc(m.company)}</button></h3>
            <div class="row" style="margin-bottom:8px">${R.fitPill(m.fit, m.score)} ${m.category ? R.pill(t('cat.' + m.category)) : ''}</div>
            ${m.ai_reason ? `<p class="muted" style="font-size:13.5px">${esc(m.ai_reason)}</p>` : ''}
            <dl class="kv" style="grid-template-columns:76px 1fr;margin-bottom:0">
              <dt>${T('Country')}</dt><dd>${esc([m.city, m.country].filter(Boolean).join(', ') || '—')}</dd>
              ${m.website ? `<dt>${T('Website')}</dt><dd><a href="${esc(m.website)}" target="_blank" rel="noopener">${esc(m.website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, ''))}</a></dd>` : ''}
            </dl></div>
          ${m.site_text ? `<div class="panel"><h3>${T('From their website')}</h3><div class="quote" style="max-height:240px;font-size:12.5px">${R.siteText(m.site_text, 900)}</div></div>` : ''}`;
        $('#open-lead', el).onclick = () => R.openLead(m.lead_id);
      };

      const saveIfDirty = async () => {
        const m = rows[cur];
        if (!dirty || !m) return;
        dirty = false;
        const r = await R.patch('/api/messages/' + m.id, { subject: $('#subj', el).value, body: $('#body', el).value });
        m.subject = $('#subj', el).value; m.body = $('#body', el).value; m.lint = r.lint;
        $('#lint', el).innerHTML = R.lintList(m.lint);
        const q = $(`.qitem[data-i="${cur}"]`, el);
        if (q) { const w = worst(m.lint); const f = $('.qflag', q); if (f) f.remove(); if (w) q.insertAdjacentHTML('beforeend', `<span class="qflag" style="background:${w === 'block' ? 'var(--danger)' : 'var(--amber)'}"></span>`); }
      };
      const removeCurrent = () => { const m = rows[cur]; sel.delete(m.id); rows.splice(cur, 1); paint(); };
      const approveOne = async btn => {
        await saveIfDirty();
        const m = rows[cur];
        const r = await R.run(btn, () => R.post('/api/messages/approve', { ids: [m.id] }));
        if (r.blocked.length) return R.toast(t('Fix the red points first.'), 'err');
        R.toast(t('Approved: {name}', { name: m.company }));
        removeCurrent();
      };
      const approveMany = async (ids, btn) => {
        if (!ids.length) return;
        await saveIfDirty();
        const r = await R.run(btn, () => R.post('/api/messages/approve', { ids }));
        R.toast(R.tn(r.approved, '1 email approved', '{n} emails approved') + (r.blocked.length ? ' ' + R.tn(r.blocked.length, '(1 needs fixing first)', '({n} need fixing first)') : ''));
        const done = new Set(ids.filter(i => !r.blocked.includes(i)));
        rows = rows.filter(m => !done.has(m.id)); done.forEach(i => sel.delete(i)); paint();
      };
      const skip = async () => {
        const m = rows[cur];
        await R.run(null, () => R.post('/api/messages/reject', { ids: [m.id] }));
        R.toast(t('{name} skipped', { name: m.company }), '', null);
        removeCurrent();
      };
      const rewrite = async btn => {
        await saveIfDirty();
        const note = await R.ask(t('Rewrite this email'), {
          text: t('The AI writes a new version. Say what should change, or leave it empty.'),
          chips: [t('shorter'), t('more formal'), t('simpler English'), t('mention private label'), t('mention custom instruments'), t('ask for a short call')],
          placeholder: t('e.g. mention our dental range'), ok: t('Rewrite') });
        if (note === null) return;
        const m = rows[cur];
        const nm = await R.run(btn, () => R.post(`/api/messages/${m.id}/rewrite`, { note }), t('New version written'));
        rows[cur] = Object.assign({}, m, nm, { lint: nm.lint });
        paintLetter();
      };
      const test = async btn => {
        await saveIfDirty();
        await R.run(btn, () => R.post(`/api/messages/${rows[cur].id}/test`, {}), r => t('Test sent to {to}', { to: r.to }));
      };
      const move = async d => { await saveIfDirty(); cur = Math.max(0, Math.min(rows.length - 1, cur + d)); paintLetter(); markQueue(); const q = $('.qitem.on', el); if (q) q.scrollIntoView({ block: 'nearest' }); };
      const keysHelp = () => R.modal(`<h2>${T('Keyboard')}</h2><div class="keys">
          <kbd>J</kbd><span>${T('next email')}</span><kbd>K</kbd><span>${T('previous email')}</span>
          <kbd>A</kbd><span>${T('approve')}</span><kbd>S</kbd><span>${T('skip this company')}</span>
          <kbd>R</kbd><span>${T('rewrite with AI')}</span><kbd>T</kbd><span>${T('send me a test')}</span>
          <kbd>E</kbd><span>${T('edit the text')}</span><kbd>Ctrl + Enter</kbd><span>${T('approve while editing')}</span></div>`);

      const onKey = e => {
        if (!rows.length || document.querySelector('.overlay')) return;
        if (R.typing(e)) {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); approveOne($('#ok', el)); }
          return;
        }
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        const k = e.key.toLowerCase();
        if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); move(1); }
        else if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
        else if (k === 'a') { e.preventDefault(); approveOne($('#ok', el)); }
        else if (k === 's') { e.preventDefault(); skip(); }
        else if (k === 'r') { e.preventDefault(); rewrite($('#rw', el)); }
        else if (k === 't') { e.preventDefault(); test($('#tst', el)); }
        else if (k === 'e') { e.preventDefault(); $('#body', el).focus(); }
        else if (e.key === '?') { e.preventDefault(); keysHelp(); }
      };
      document.addEventListener('keydown', onKey);
      paint();
      return () => { document.removeEventListener('keydown', onKey); R.quiet(saveIfDirty()); };
    },
  };
})();
