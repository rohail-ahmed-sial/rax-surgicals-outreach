'use strict';
/* Reports: what happened over 7, 30 or 90 days, per day, per country and per campaign, and what the AI cost. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;

  R.views.reports = {
    async render(el, { params }) {
      let days = [7, 30, 90].includes(+params.get('days')) ? +params.get('days') : 30;
      el.innerHTML = `<div class="head"><div><h1>${T('nav.reports')}</h1><p>${T('reports.lead')}</p></div></div>
        <div class="chips" id="range" style="margin-bottom:16px"></div><div id="rep"></div>`;
      const draw = async () => {
        $('#range', el).innerHTML = [7, 30, 90].map(d => `<button class="chip ${d === days ? 'on' : ''}" data-d="${d}">${T('Last {n} days', { n: d })}</button>`).join('');
        $$('[data-d]', el).forEach(b => b.onclick = () => { days = +b.dataset.d; history.replaceState(null, '', '#/reports?days=' + days); R.quiet(draw()); });
        const box = $('#rep', el);
        box.style.opacity = box.innerHTML ? .55 : 1;            // keep the old numbers while the new ones load
        const d = await R.get('/api/reports?days=' + days);
        box.style.opacity = 1;
        const fn = d.funnel, rt = d.rates, u = d.usage;
        box.innerHTML = `<div class="panel"><div class="figs" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
            <div class="fig" style="border:0;padding-top:0"><b>${R.num(fn.contacted)}</b><span>${R.icon('outbox', 'ic--sm')}${T('companies emailed')}</span></div>
            <div class="fig" style="border:0;padding-top:0"><b>${R.pct(rt.reply)}</b><span>${R.icon('reply', 'ic--sm')}${T('replied')}</span></div>
            <div class="fig" style="border:0;padding-top:0"><b>${R.pct(rt.interested)}</b><span>${R.icon('star', 'ic--sm')}${T('interested')}</span></div>
            <div class="fig" style="border:0;padding-top:0"><b>${R.pct(rt.bounce)}</b><span>${R.icon('alert', 'ic--sm')}${T('bounced')}</span></div>
            <div class="fig" style="border:0;padding-top:0"><b>${esc(R.money(d.won_value))}</b><span>${R.icon('trophy', 'ic--sm')}${T('orders won (all time)')}</span></div>
          </div></div>
          <div class="grid g2"><div class="panel"><div id="c1"></div></div><div class="panel"><div id="c2"></div></div></div>
          <div class="panel"><details><summary style="cursor:pointer;font-weight:600">${T('Show the numbers per day')}</summary>
            <div class="tablewrap" style="max-height:340px;margin-top:10px"><table><thead><tr><th>${T('Day')}</th><th class="r">${T('Emails sent')}</th><th class="r">${T('Replies')}</th><th class="r">${T('Interested')}</th><th class="r">${T('Bounced')}</th></tr></thead>
            <tbody>${d.series.slice().reverse().map(x => `<tr><td>${esc(R.fmtDate(x.day))}</td><td class="r num">${x.sent}</td><td class="r num">${x.replies}</td><td class="r num">${x.interested}</td><td class="r num">${x.bounces}</td></tr>`).join('')}</tbody></table></div></details></div>
          <div class="grid g2">
            <div class="panel"><div class="panel__head"><h2>${T('From lead to order')}</h2></div>
              ${R.barRows([['found', 'Leads found'], ['good', 'Good fit'], ['contacted', 'Emailed'], ['replied', 'Replied'], ['interested', 'Interested'], ['won', 'Order won']].map(([k, label]) => ({ label: t(label), value: fn[k] })))}
              <p class="hint" style="margin-top:10px">${T('Leads found and good fit: added in this period. The rest: companies first emailed in this period.')}</p></div>
            <div class="panel panel--flush"><div class="panel__head"><h2>${T('By country')}</h2></div><div class="tablewrap">
              ${d.by_country.length ? `<table><thead><tr><th>${T('Country')}</th><th class="r">${T('Emailed')}</th><th class="r">${T('Replied')}</th><th class="r">${T('Rate')}</th><th class="r">${T('Interested')}</th></tr></thead>
                <tbody>${d.by_country.map(c => `<tr><td>${esc(c.country)}</td><td class="r num">${c.contacted}</td><td class="r num">${c.replied}</td><td class="r num">${R.pct(c.rate)}</td><td class="r num">${c.interested}</td></tr>`).join('')}</tbody></table>`
                : `<p class="muted" style="padding:0 18px 16px">${T('No emails in this period.')}</p>`}</div></div>
          </div>
          <div class="panel panel--flush"><div class="panel__head"><h2>${T('Campaigns')}</h2></div><div class="tablewrap">
            ${d.campaigns.length ? `<table><thead><tr><th>${T('Campaign')}</th><th class="r">${T('Leads')}</th><th class="r">${T('Emails sent')}</th><th class="r">${T('Replied')}</th><th class="r">${T('Rate')}</th><th class="r">${T('Interested')}</th><th class="r">${T('Bounced')}</th></tr></thead>
              <tbody>${d.campaigns.map(c => `<tr class="click" data-c="${c.id}"><td class="co">${esc(c.name)} ${c.active ? '' : R.pill(t('paused'))}</td><td class="r num">${c.leads}</td><td class="r num">${c.sent}</td><td class="r num">${c.replied}</td><td class="r num">${R.pct(c.reply_rate)}</td><td class="r num">${c.interested}</td><td class="r num">${c.bounced}</td></tr>`).join('')}</tbody></table>`
              : `<p class="muted" style="padding:0 18px 16px">${T('No campaigns yet.')}</p>`}</div><p class="hint" style="padding:0 18px 14px;margin:0">${T('Campaign numbers are for all time.')}</p></div>
          <div class="panel"><div class="panel__head"><h2>${T('AI and Google use')}</h2></div>
            <p>${T('{calls} AI calls in this period, about {cost}. {places} Google Maps requests.', { calls: R.num(u.ai_calls), cost: '$' + u.ai_cost.toFixed(2), places: R.num(u.places_requests) })}</p>
            <p class="hint">${T('An estimate from the prices in Settings. Your Anthropic and Google bills show the exact amounts.')}</p></div>`;
        const chart = (id, key, title) => {
          const host = $(id, box);
          host.innerHTML = `<h3 class="charttitle">${T(title)} <span class="muted" style="font-weight:500">${T('{n} in total', { n: R.num(d.series.reduce((a, x) => a + x[key], 0)) })}</span></h3><div class="chart"></div>`;
          R.columns(host.lastElementChild, d.series.map(x => ({ label: R.fmtDay(x.day), title: R.fmtDate(x.day), value: x[key] })), { unit: t(title) });
        };
        chart('#c1', 'sent', 'Emails sent per day');
        chart('#c2', 'replies', 'Replies per day');
        $$('[data-c]', box).forEach(tr => tr.onclick = () => R.go('#/campaigns/' + tr.dataset.c));
      };
      await draw();
      const onTheme = () => R.quiet(draw());
      document.addEventListener('rax-theme', onTheme);
      return () => document.removeEventListener('rax-theme', onTheme);
    },
  };
})();
