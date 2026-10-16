'use strict';
/* Outbox: approved emails waiting to go out, what was sent, what failed (with the reason) and what was cancelled. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  const TABS = ['approved', 'sent', 'failed', 'cancelled'];

  function forecastText(f) {
    if (!f.email_ready) return t('Sending is not set up yet.');
    if (f.paused) return t('pause.' + (f.reason || 'manual'));
    if (!f.countries.length) return t('No approved emails are waiting.');
    if (f.sent_today >= f.limit) return t("Today's limit is reached. The next email goes out tomorrow.");
    const parts = f.countries.map(c => `${c.country || '?'} ${c.queued}`).join(', ');
    const when = f.next_send ? (new Date(f.next_send) - Date.now() < 90000 ? t('within a few minutes') : R.fmtTime(f.next_send)) : t('when office hours start');
    return t('Next email: {when}. Waiting: {list}.', { when, list: parts });
  }

  R.views.outbox = {
    async render(el, { params }) {
      let tab = TABS.includes(params.get('t')) ? params.get('t') : 'approved';
      el.innerHTML = `<div class="head"><div><h1>${T('nav.outbox')}</h1><p>${T('outbox.lead')}</p></div><div class="head__actions" id="acts"></div></div>
        <div id="fc"></div><div class="tabs" id="tabs"></div>
        <div class="row" id="filter" hidden style="margin-bottom:12px"><input type="search" id="q" placeholder="${T('Company, email or subject')}" aria-label="${T('Search')}" style="max-width:340px"><span class="muted" id="qn"></span></div>
        <div id="list"></div>`;
      let rows = [], footer = '', shown = 100, query = '';
      const PAGE = 100;
      $('#q', el).addEventListener('input', R.debounce(e => { query = e.target.value.trim().toLowerCase(); shown = PAGE; paintList(); }, 200));
      const draw = async () => {
        const [f, r] = await Promise.all([R.get('/api/forecast'), R.get('/api/messages?status=' + tab)]);
        $('#acts', el).innerHTML = (f.email_ready ? `<button class="btn" id="pause">${R.icon(f.paused ? 'play' : 'pause')}${T(f.paused ? 'Resume sending' : 'Pause sending')}</button>` : `<a class="btn btn--primary" href="#/settings/mailbox">${T('Set up email')}</a>`)
          + (tab === 'approved' && r.rows.length && f.email_ready && !f.paused ? `<button class="btn btn--primary" id="sendnow">${R.icon('outbox')}${T('Send one now')}</button>` : '');
        $('#fc', el).innerHTML = R.note(`${esc(forecastText(f))} <span class="muted">${T('{a} of {b} sent today', { a: f.sent_today, b: f.limit })}${f.warmup ? ', ' + T('warm-up week {w}', { w: f.week }) : ''}.</span>`, f.paused || !f.email_ready ? '' : 'info');
        $('#tabs', el).innerHTML = TABS.map(k => `<button data-t="${k}" class="${k === tab ? 'on' : ''}">${T('outbox.' + k)}</button>`).join('');
        $$('[data-t]', el).forEach(b => b.onclick = () => { tab = b.dataset.t; shown = PAGE; query = ''; $('#q', el).value = ''; history.replaceState(null, '', '#/outbox?t=' + tab); R.quiet(draw()); });
        const p = $('#pause', el);
        if (p) p.onclick = async () => { await R.run(p, () => R.post('/api/sending', { paused: !f.paused }), t(f.paused ? 'Sending resumed' : 'Sending paused')); R.refreshBadges(); R.quiet(draw()); };
        const sn = $('#sendnow', el);
        if (sn) sn.onclick = async () => {
          const res = await R.run(sn, () => R.post('/api/send-now'));
          R.toast(t('send.' + res.result.replace(/ /g, '_')), res.result === 'failed' ? 'err' : '');
          R.refreshBadges(); R.quiet(draw());
        };
        rows = r.rows; footer = r.footer;
        paintList();
      };
      const paintList = () => {
        const list = query ? rows.filter(m => [m.company, m.to_email, m.subject, m.country].some(v => String(v || '').toLowerCase().includes(query))) : rows;
        $('#filter', el).hidden = rows.length <= 15;
        $('#qn', el).textContent = query ? R.tn(list.length, '1 email', '{n} emails') : '';
        const view = list.slice(0, shown);
        $('#list', el).innerHTML = rows.length ? (list.length ? `<div class="panel panel--flush"><div class="tablewrap"><table><thead><tr><th>${T('Company')}</th><th class="col-opt">${T('To')}</th><th>${T('Subject')}</th>
          <th>${T(tab === 'sent' ? 'Sent' : tab === 'failed' ? 'Problem' : tab === 'cancelled' ? 'Reason' : 'Email')}</th><th></th></tr></thead><tbody>
          ${view.map(m => `<tr class="click" data-m="${m.id}"><td class="co">${esc(m.company)}<small class="muted">${esc(m.country || '')}</small></td><td class="ell col-opt" style="max-width:220px">${esc(m.to_email)}</td>
            <td class="ell" style="max-width:300px">${esc(m.subject)}</td>
            <td class="muted" style="max-width:280px">${tab === 'sent' ? esc(R.fmtDT(m.sent_at)) : tab === 'failed' || tab === 'cancelled' ? esc(errText(m.error)) : T('email {a} of {b}', { a: m.step + 1, b: m.steps_total || 1 })}</td>
            <td class="nowrap">${tab === 'failed' ? `<button class="btn btn--sm" data-retry="${m.id}">${T('Try again')}</button>` : tab === 'approved' ? `<button class="btn btn--sm btn--ghost" data-hold="${m.id}">${T('Do not send')}</button>` : ''}</td></tr>`).join('')}</tbody></table></div>
          ${list.length > shown ? `<div class="row" style="padding:12px 18px"><button class="btn btn--sm" id="more">${T('Show {n} more', { n: Math.min(PAGE, list.length - shown) })}</button><span class="muted">${T('{a} of {b} shown', { a: shown, b: list.length })}</span></div>` : ''}</div>`
            : `<div class="panel"><p class="muted" style="margin:0">${T('No email matches this search.')}</p></div>`)
          : `<div class="panel">${R.empty({ icon: { approved: 'outbox', sent: 'outbox', failed: 'check', cancelled: 'check' }[tab], title: t('outbox.empty.' + tab), text: tab === 'approved' ? t('Approve emails and they wait here for their turn.') : '' , action: tab === 'approved' ? { label: t('Open approve'), href: '#/approve' } : null })}</div>`;
        const more = $('#more', el);
        if (more) more.onclick = () => { shown += PAGE; paintList(); };
        $$('[data-retry]', el).forEach(b => b.onclick = async e => { e.stopPropagation(); await R.run(b, () => R.post('/api/messages/retry', { ids: [+b.dataset.retry] }), t('Will try again')); R.quiet(draw()); });
        $$('[data-hold]', el).forEach(b => b.onclick = async e => {
          e.stopPropagation();
          if (!await R.confirm(t('Do not send this email?'), t('The company leaves the campaign. You can add it again later.'), { ok: t('Do not send') })) return;
          await R.run(b, () => R.post('/api/messages/reject', { ids: [+b.dataset.hold] }), t('Cancelled')); R.quiet(draw());
        });
        $$('[data-m]', el).forEach(tr => tr.onclick = () => {
          const m = rows.find(x => x.id === +tr.dataset.m);
          R.modal(`<h2>${esc(m.subject)}</h2><p class="muted">${T('To {to}', { to: m.to_email })} (${esc(m.company)})${m.sent_at ? ', ' + esc(R.fmtDT(m.sent_at)) : ''}</p>
            <div class="quote" style="max-height:none">${esc(m.body)}\n\n<span class="muted">${esc(footer)}</span></div>
            <div class="row" style="margin-top:12px"><button class="btn btn--sm" data-close data-open="${m.lead_id}">${T('Lead details')}</button></div>`);
          setTimeout(() => { const b = document.querySelector('[data-open]'); if (b) b.addEventListener('click', () => R.openLead(m.lead_id)); }, 0);
        });
      };
      const errText = e => {
        if (!e) return '';
        if (e.startsWith('no_mail_server')) return t('The domain of this address does not accept email.');
        if (e.startsWith('Address does not exist')) return t('Their server says this address does not exist.');
        if (e === 'skipped by you') return t('Skipped by you');
        if (e.startsWith('stopped:')) return t('Stopped: ' + e.slice(8).trim());
        if (e === 'lead stopped') return t('The company replied, bounced or unsubscribed.');
        return e;
      };
      await draw();
      R.every(() => R.quiet(draw()), 20000);
    },
  };
})();
