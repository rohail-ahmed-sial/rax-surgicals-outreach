'use strict';
/* Activity: everything the software did, newest first, and the work running in the background. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  R.views.activity = {
    async render(el) {
      let only = 'all';
      el.innerHTML = `<div class="head"><div><h1>${T('nav.activity')}</h1><p>${T('activity.lead')}</p></div></div>
        <div class="panel"><div class="panel__head"><h2>${T('Working in the background')}</h2></div><div id="jobs"></div></div>
        <div class="chips" id="only" style="margin-bottom:12px"></div><div class="panel"><div class="log" id="log"></div></div>`;
      const draw = async () => {
        const [rows, jobs] = await Promise.all([R.get('/api/log?n=400'), R.get('/api/jobs')]);
        $('#jobs', el).innerHTML = R.jobsHtml(jobs);
        $('#only', el).innerHTML = [['all', 'Everything'], ['problems', 'Only problems']].map(([k, l]) => `<button class="chip ${k === only ? 'on' : ''}" data-o="${k}">${T(l)}</button>`).join('');
        $$('[data-o]', el).forEach(b => b.onclick = () => { only = b.dataset.o; R.quiet(draw()); });
        const list = only === 'problems' ? rows.filter(r => r.level !== 'info') : rows;
        $('#log', el).innerHTML = list.length ? list.map(r => `<div><time title="${esc(R.fmtDT(r.at))}">${esc(R.fmtDT(r.at))}</time><span class="${esc(r.level)}">${esc(r.text)}</span></div>`).join('') : `<p class="muted">${T('Nothing yet.')}</p>`;
      };
      await draw();
      R.every(() => R.quiet(draw()), 10000);
    },
  };
})();
