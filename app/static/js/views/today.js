'use strict';
/* Today: what needs you now, how the week went, and when emails will go out. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;

  function greeting(name) {
    const h = new Date().getHours();
    const g = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
    return name ? t(g + ', {name}', { name }) : t(g);
  }

  function pausedText(s) {
    if (!s.email_ready) return t('Sending is not set up yet.');
    if (s.paused) return t('pause.' + (s.reason || 'manual'));
    return '';
  }

  function todoRows(d) {
    const c = d.counts, s = d.sending, rows = [];
    if (s.paused && s.email_ready) rows.push({ n: '!', ic: 'pause', cls: 'bad', title: t('Sending is paused'), sub: pausedText(s), btn: `<button class="btn btn--sm btn--go" data-act="resume">${R.icon('play')}${T('Resume sending')}</button>` });
    if (c.drafts) rows.push({ n: c.drafts, ic: 'approve', cls: 'hot', title: R.tn(c.drafts, '1 email to approve', '{n} emails to approve'), sub: t('Nothing goes out before you approve it.'), btn: `<a class="btn btn--sm btn--primary" href="#/approve">${T('Approve')}</a>` });
    if (c.inbox) rows.push({ n: c.inbox, ic: 'reply', cls: 'hot', title: R.tn(c.inbox, '1 reply to answer', '{n} replies to answer'), sub: t('Their follow-ups have already stopped.'), btn: `<a class="btn btn--sm btn--primary" href="#/inbox">${T('Open inbox')}</a>` });
    if (c.tasks_due) rows.push({ n: c.tasks_due, ic: 'flag', cls: 'hot', title: R.tn(c.tasks_due, '1 deal step due', '{n} deal steps due'), sub: t('From your pipeline: samples, quotes, calls.'), btn: `<a class="btn btn--sm" href="#/pipeline">${T('Open pipeline')}</a>` });
    if (c.failed) rows.push({ n: c.failed, ic: 'alert', cls: 'bad', title: R.tn(c.failed, '1 email could not be sent', '{n} emails could not be sent'), sub: t('See why, then try again or skip.'), btn: `<a class="btn btn--sm" href="#/outbox?t=failed">${T('See outbox')}</a>` });
    if (c.unchecked) rows.push({ n: c.unchecked, ic: 'find', title: R.tn(c.unchecked, '1 lead not checked yet', '{n} leads not checked yet'), sub: t('Read their websites, find emails and judge the fit.'), btn: `<button class="btn btn--sm" data-act="check">${T('Check now')}</button>` });
    if (c.ready) rows.push({ n: c.ready, ic: 'users', title: R.tn(c.ready, '1 lead ready for a campaign', '{n} leads ready for a campaign'), sub: t('Good fit with an email address.'), btn: `<a class="btn btn--sm" href="#/leads?view=ready">${T('Choose')}</a>` });
    return rows;
  }

  function setupPanel(st) {
    const items = [['company', 'Company and sender', 'settings/company'], ['email', 'Sending email', 'settings/mailbox'], ['inbox', 'Reading replies', 'settings/mailbox'],
                   ['ai', 'AI key', 'settings/ai'], ['places', 'Google Maps key', 'settings/google'], ['facts', 'Facts for the AI', 'settings/company'], ['campaign', 'First campaign', 'campaigns/new']];
    const done = items.filter(i => st[i[0]]).length;
    if (done === items.length) return '';
    return `<div class="panel"><div class="panel__head"><h2>${T('Setup: {a} of {b} done', { a: done, b: items.length })}</h2>
      <button class="btn btn--sm" data-act="wizard">${T('Open setup guide')}</button></div>
      <div class="chips">${items.map(([k, label, href]) => `<a class="chip ${st[k] ? '' : ''}" href="#/${href}" style="text-decoration:none">${st[k] ? R.icon('check', 'ic--sm') : R.icon('plus', 'ic--sm')}${T(label)}</a>`).join('')}</div></div>`;
  }

  function nextSendText(s) {
    if (!s.email_ready || s.paused) return pausedText(s) || t('Sending is paused');
    const f = s.forecast || {};
    if (!f.countries || !f.countries.length) return t('No approved emails are waiting.');
    if (s.sent_today >= s.limit) return t("Today's limit is reached. The next email goes out tomorrow.");
    if (!f.next_send) return t('The waiting emails go out when their office hours start.');
    const when = new Date(f.next_send);
    return when - Date.now() < 90000 ? t('The next email goes out within a few minutes.') : t('Next email around {time}.', { time: R.fmtTime(f.next_send) });
  }

  R.views.today = {
    async render(el) {
      el.innerHTML = '<div class="hello"><h1>&nbsp;</h1></div>';
      const draw = async () => {
        const d = await R.get('/api/today');
        const s = d.sending, rows = todoRows(d);
        const ser = d.series;
        const wk = d.week;
        const pipe = R.STAGES.map(k => ({ label: t('stage.' + k), value: d.pipeline[k].n, note: d.pipeline[k].value ? R.money(d.pipeline[k].value) : '', cls: 'st-' + k }));
        const openValue = R.STAGES.slice(0, 4).reduce((a, k) => a + (d.pipeline[k].value || 0), 0);
        el.innerHTML = `
          <div class="hello"><h1>${esc(greeting((d.sender_name || '').split(' ')[0]))}</h1>
            <p><span>${esc(new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }))}</span>
            <span class="pill ${!s.email_ready || s.paused ? 'pill--warn' : 'pill--good'}"><span class="dot"></span>${!s.email_ready ? T('Email not set up') : s.paused ? T('Sending paused') : T('Sending on')}</span>
            <span class="muted">${T('{a} of {b} sent today', { a: s.sent_today, b: s.limit })}</span></p></div>
          ${setupPanel(d.setup)}
          <div class="grid g75">
            <div class="panel"><div class="panel__head"><h2>${T('Needs you')}</h2></div>
              ${rows.length ? `<ul class="todo">${rows.map(r => `<li class="${r.cls || ''}"><span class="todo__ic">${R.icon(r.ic)}</span><span class="todo__t"><b>${esc(r.title)}</b><small class="muted">${esc(r.sub)}</small></span>${r.btn}</li>`).join('')}</ul>`
                : `<div class="allclear"><svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><use href="#i-instrument"/></svg><div><b>${T('Nothing is waiting for you.')}</b><br><span class="muted">${T('A good moment to find new leads.')}</span><div style="margin-top:8px"><a class="btn btn--sm btn--primary" href="#/find">${T('Find leads')}</a></div></div></div>`}
            </div>
            <div class="panel"><div class="panel__head"><h2>${T('Last 7 days')}</h2></div>
              <div class="figs">
                <div class="fig"><b>${R.num(wk.sent)}</b><span>${R.icon('outbox', 'ic--sm')}${T('emails sent')}</span></div>
                <div class="fig"><b>${R.num(wk.replies)}</b><span>${R.icon('reply', 'ic--sm')}${T('replies')}</span></div>
                <div class="fig"><b>${R.num(wk.interested)}</b><span>${R.icon('star', 'ic--sm')}${T('interested')}</span></div>
                <div class="fig"><b>${wk.reply_rate === null ? '—' : R.pct(wk.reply_rate)}</b><span>${R.icon('percent', 'ic--sm')}${T('reply rate, 30 days')}</span></div>
              </div>
              ${s.warmup ? `<p class="muted" style="margin:12px 0 0;font-size:13px">${T('Warm-up week {w}: {n} emails a day for now, {full} when it ends.', { w: s.week, n: s.limit, full: s.full })}</p>` : ''}
            </div>
          </div>
          <div class="panel"><div class="panel__head"><h2>${T('When emails go out')}</h2><span class="muted">${esc(nextSendText(s))}</span></div>
            ${s.markets.length ? `<div class="window" id="band"></div>
              <p class="muted" style="font-size:12.5px;margin:8px 0 0">${T('Bars show office hours ({a}:00 to {b}:00 their time{wd}) on your own clock. Green: open now.', { a: s.hours[0], b: s.hours[1], wd: s.weekdays_only ? t(', weekdays') : '' })}</p>`
              : `<p class="muted">${T('Add leads with a country to see their office hours here.')}</p>`}
          </div>
          <div class="grid g2">
            <div class="panel"><div id="ch-sent"></div></div>
            <div class="panel"><div id="ch-rep"></div></div>
          </div>
          <div class="grid g2">
            <div class="panel"><div class="panel__head"><h2>${T('Pipeline')}</h2><a href="#/pipeline">${T('Open pipeline')}</a></div>
              ${R.barRows(pipe)}
              ${openValue ? `<p class="muted" style="margin:10px 0 0">${T('Open deals worth {v}', { v: R.money(openValue) })}</p>` : ''}
              ${d.tasks.length ? `<hr class="sep"><h3 style="margin-bottom:6px">${T('Next steps')}</h3>${d.tasks.map(tk => {
                const over = tk.next_action_date < R.todayISO(), today = tk.next_action_date === R.todayISO();
                return `<div class="taskrow"><span class="due ${over ? 'due--over' : today ? 'due--today' : ''}">${over ? T('overdue') : today ? T('today') : esc(R.fmtDay(tk.next_action_date))}</span>
                  <span class="spacer ell"><button class="linkbtn" data-lead="${tk.id}">${esc(tk.company)}</button> <span class="muted">${esc(tk.next_action || '')}</span></span></div>`; }).join('')}` : ''}
            </div>
            <div class="panel"><div class="panel__head"><h2>${T('Recent activity')}</h2><a href="#/activity">${T('All activity')}</a></div>
              <div class="log">${d.log.length ? d.log.map(r => `<div><time title="${esc(R.fmtDT(r.at))}">${esc(R.ago(r.at))}</time><span class="${esc(r.level)}">${esc(r.text)}</span></div>`).join('') : `<p class="muted">${T('Nothing yet.')}</p>`}</div>
              <hr class="sep">
              <p class="muted" style="margin:0;font-size:13px">${T('This month: {calls} AI calls (about {cost}), {places} Google searches.', { calls: R.num(d.usage.ai_calls), cost: '$' + d.usage.ai_cost.toFixed(2), places: R.num(d.usage.places_requests) })}</p>
            </div>
          </div>`;
        const band = $('#band', el);
        if (band) R.windowBand(band, s.markets, { hours: s.hours, weekdaysOnly: s.weekdays_only });
        const chart = (id, key, title) => {
          const host = $(id, el);
          const total = ser.reduce((a, x) => a + x[key], 0);
          host.innerHTML = `<h3 class="charttitle">${T(title)} <span class="muted" style="font-weight:500">${T('{n} in 14 days', { n: R.num(total) })}</span></h3><div class="chart"></div>`;
          R.columns(host.lastElementChild, ser.map(x => ({ label: R.fmtDay(x.day), title: R.fmtDate(x.day), value: x[key] })), { unit: t(title) });
        };
        chart('#ch-sent', 'sent', 'Emails sent per day');
        chart('#ch-rep', 'replies', 'Replies per day');
        $$('[data-lead]', el).forEach(b => b.onclick = () => R.openLead(+b.dataset.lead, draw));
        el.onclick = async e => {
          const b = e.target.closest('[data-act]'); if (!b) return;
          if (b.dataset.act === 'resume') { await R.run(b, () => R.post('/api/sending', { paused: false }), t('Sending resumed')); R.refreshBadges(); draw(); }
          if (b.dataset.act === 'check') { await R.run(b, () => R.post('/api/leads/check', {}), r => R.tn(r.count, 'Checking 1 lead in the background', 'Checking {n} leads in the background')); }
          if (b.dataset.act === 'wizard') R.openWizard();
        };
      };
      await draw();
      R.every(() => R.quiet(draw()), 30000);
      const onTheme = () => R.quiet(draw());
      document.addEventListener('rax-theme', onTheme);
      return () => document.removeEventListener('rax-theme', onTheme);
    },
  };
})();
