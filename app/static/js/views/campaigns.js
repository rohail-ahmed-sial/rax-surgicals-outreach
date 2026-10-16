'use strict';
/* Campaigns: what to pitch and how many emails each company gets. List, plus an editor with a live example on the side. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;

  const DEFAULT_STEPS = () => [
    { day: 0, kind: 'ai', instructions: t('step.default.1'), subject: 'Surgical instruments for {company}',
      body: 'Hello {first_name},\n\nI am {my_name} from {my_company} in Sialkot, Pakistan. We make surgical, dental and beauty instruments in German stainless steel, including custom pieces and private label with your brand.\n\nWould it help if I sent you our catalogue?\n\nBest regards' },
    { day: 4, kind: 'ai', instructions: t('step.default.2'), subject: '',
      body: 'Hello {first_name},\n\nA short follow-up: we also make instruments under the buyer\'s own brand (private label), with small first orders.\n\nShall I send a few product photos?' },
    { day: 10, kind: 'ai', instructions: t('step.default.3'), subject: '',
      body: 'Hello {first_name},\n\nI will not take more of your time. If samples of our scissors or needle holders would be useful, just reply and I will arrange them.\n\nBest regards' },
  ];

  function chain(steps) {
    return `<div class="chain">${steps.map((s, i) => `${i ? '<i></i>' : ''}<span>${T(i === 0 ? 'Day 0: first email' : 'Day {d}: follow-up', { d: s.day })}</span>`).join('')}</div>`;
  }

  async function list(el) {
    const [rows, today] = await Promise.all([R.get('/api/campaigns'), R.get('/api/badges')]);
    el.innerHTML = `<div class="head"><div><h1>${T('nav.campaigns')}</h1><p>${T('campaigns.lead')}</p></div>
      <div class="head__actions"><a class="btn btn--primary" href="#/campaigns/new">${R.icon('plus')}${T('New campaign')}</a></div></div>
      ${rows.length ? rows.map(c => `<div class="panel">
        <div class="panel__head"><div class="row"><h2 style="font-size:17px">${esc(c.name)}</h2>${c.active ? R.pill(t('on'), 'good') : R.pill(t('paused'))}</div>
          <div class="row"><a class="btn btn--sm" href="#/campaigns/${c.id}">${R.icon('edit')}${T('Edit')}</a>
            <button class="btn btn--sm" data-dup="${c.id}">${R.icon('copy')}${T('Duplicate')}</button>
            <button class="btn btn--sm" data-toggle="${c.id}">${R.icon(c.active ? 'pause' : 'play')}${T(c.active ? 'Pause' : 'Turn on')}</button>
            <button class="btn btn--sm btn--ghost btn--danger" data-del="${c.id}" aria-label="${T('Delete')}">${R.icon('trash')}</button></div></div>
        ${c.pitch ? `<p class="muted">${esc(c.pitch)}</p>` : ''}
        ${chain(c.steps)}
        <div class="cstats">
          <div><b>${R.num(c.stats.leads)}</b><span>${T('leads in it')}</span></div>
          <div><b>${R.num(c.stats.sent)}</b><span>${T('emails sent')}</span></div>
          <div><b>${R.num(c.stats.replied)}</b><span>${T('replied')}</span></div>
          <div><b>${R.pct(c.stats.reply_rate)}</b><span>${T('reply rate')}</span></div>
          <div><b>${R.num(c.stats.interested)}</b><span>${T('interested')}</span></div>
        </div>
        <div class="row">${c.active ? `<button class="btn btn--sm btn--primary" data-ready="${c.id}" ${today.ready ? '' : 'disabled'}>${today.ready ? R.TN(today.ready, 'Add the 1 ready lead', 'Add all {n} ready leads') : T('No ready leads right now')}</button>` : ''}
          <a class="btn btn--sm" href="#/leads?view=ready">${T('Choose leads')}</a>
          ${c.stats.drafts ? `<a class="btn btn--sm" href="#/approve">${R.TN(c.stats.drafts, '1 email to approve', '{n} emails to approve')}</a>` : ''}</div>
      </div>`).join('') : `<div class="panel">${R.empty({ icon: 'campaigns', title: t('No campaigns yet'), text: t('Say what to pitch; the AI writes a personal email for each company, and you approve it.'), action: { label: t('Create the first campaign'), href: '#/campaigns/new' } })}</div>`}`;
    $$('[data-toggle]', el).forEach(b => b.onclick = async () => { const c = rows.find(x => x.id === +b.dataset.toggle); await R.run(b, () => R.patch('/api/campaigns/' + c.id, { active: !c.active }), t(c.active ? 'Campaign paused' : 'Campaign turned on')); list(el); });
    $$('[data-dup]', el).forEach(b => b.onclick = async () => { const r = await R.run(b, () => R.post(`/api/campaigns/${b.dataset.dup}/duplicate`), t('Copy made (paused)')); R.go('#/campaigns/' + r.id); });
    $$('[data-del]', el).forEach(b => b.onclick = async () => {
      if (!await R.confirm(t('Delete this campaign?'), t('delete.campaign.text'), { ok: t('Delete'), danger: true })) return;
      const r = await R.run(b, () => R.del('/api/campaigns/' + b.dataset.del));
      R.toast(r.code ? t('err.' + r.code) : t('Deleted')); list(el);
    });
    $$('[data-ready]', el).forEach(b => b.onclick = async () => { const r = await R.run(b, () => R.post(`/api/campaigns/${b.dataset.ready}/enroll`, { all_ready: true })); R.showEnrollResult(r); R.refreshBadges(); list(el); });
  }

  async function editor(el, id) {
    const c = id ? await R.get('/api/campaigns/' + id) : { name: t('Distributors, first contact'), pitch: t('campaign.default.pitch'), instructions: '', steps: DEFAULT_STEPS(), write_in_their_language: 0, auto_approve_followups: 0, active: 1 };
    const steps = JSON.parse(JSON.stringify(c.steps));
    const [settings, leads] = await Promise.all([R.get('/api/settings'), R.get('/api/leads?per=40&sort=score&view=ready')]);
    const aiOn = !!settings.anthropic_api_key;
    let pstep = 0;
    el.innerHTML = `<div class="head"><div><h1>${esc(id ? c.name : t('New campaign'))}</h1><p>${T('editor.lead')}</p></div>
      <div class="head__actions"><a class="btn" href="#/campaigns">${T('Cancel')}</a><button class="btn btn--primary" id="save">${T('Save campaign')}</button></div></div>
      ${aiOn ? '' : R.note(`${T('No AI key yet: emails will use your template text. Add the key in Settings for a personal email to every company.')} <a href="#/settings/ai">${T('Add the key')}</a>`, 'info')}
      <div class="grid g75"><form id="cf" onsubmit="return false">
        <div class="panel">
          <label>${T('Name')}<input name="name" value="${esc(c.name)}" required></label>
          <label>${T('What to pitch')}<span class="hint">${T('The main offer in one or two sentences.')}</span><textarea name="pitch" style="min-height:64px">${esc(c.pitch || '')}</textarea></label>
          <label>${T('Notes for the AI')}<span class="hint">${T('notes.hint')}</span><textarea name="instructions" style="min-height:64px">${esc(c.instructions || '')}</textarea></label>
          <label class="check"><input type="checkbox" name="lang" ${c.write_in_their_language ? 'checked' : ''}><span>${T('Write in the language of their website (otherwise English)')}</span></label>
          <label class="check" style="margin-bottom:0"><input type="checkbox" name="auto" ${c.auto_approve_followups ? 'checked' : ''}><span>${T('Send follow-ups without asking me (first emails always wait for approval)')}</span></label>
        </div>
        <h2 style="margin:18px 0 12px">${T('Emails in this campaign')}</h2>
        <ol class="steps" id="steps"></ol>
        <button type="button" class="btn btn--sm" id="addstep">${R.icon('plus')}${T('Add a follow-up')}</button>
        <p class="hint" style="margin-top:12px">${T('Template words: {first_name} {company} {country} {my_name} {my_company} {catalogue_link}')}</p>
      </form>
      <aside class="preview"><div class="panel"><div class="panel__head"><h2>${T('Example')}</h2></div>
        <label>${T('For this company')}<select id="pv-lead">${leads.rows.length ? leads.rows.map(l => `<option value="${l.id}">${esc(l.company)}${l.country ? ' (' + esc(l.country) + ')' : ''}</option>`).join('') : `<option value="">${T('the best lead you have')}</option>`}</select></label>
        <div class="tabs" id="pv-steps" style="margin-bottom:10px"></div>
        <button class="btn btn--block" id="pv-go">${R.icon('spark')}${T('Write an example')}</button>
        <div id="pv-out" style="margin-top:12px"><p class="muted" style="font-size:13px">${T(aiOn ? 'Nothing is sent from here. Each example uses one AI call.' : 'Nothing is sent from here.')}</p></div></div></aside></div>`;
    const box = $('#steps', el);
    function paintSteps() {
      box.innerHTML = steps.map((s, i) => `<li class="step" data-i="${i}"><span class="step__n">${i + 1}</span><div class="step__box">
        <div class="step__h"><b>${T(i === 0 ? 'First email' : 'Follow-up {n}', { n: i })}</b>
          ${i ? `<span class="muted">${T('on day')}</span><input type="number" min="1" max="60" data-f="day" value="${s.day}" aria-label="${T('Day')}">` : `<span class="muted">${T('as soon as you approve it')}</span>`}
          <select data-f="kind"><option value="ai" ${s.kind !== 'template' ? 'selected' : ''}>${T('AI writes it')}</option><option value="template" ${s.kind === 'template' ? 'selected' : ''}>${T('My template')}</option></select>
          <span class="spacer"></span>${i ? `<button type="button" class="linkbtn linkbtn--danger" data-rm>${T('Remove')}</button>` : ''}</div>
        ${s.kind !== 'template' ? `<label>${T('What this email should do')}<input data-f="instructions" value="${esc(s.instructions || '')}" placeholder="${T('e.g. offer the catalogue')}"></label>` : ''}
        <details ${s.kind === 'template' ? 'open' : ''}><summary class="muted" style="cursor:pointer;font-size:13px;margin-bottom:8px">${T(s.kind === 'template' ? 'Template' : 'Template (used when there is no AI key)')}</summary>
          ${i === 0 ? `<label>${T('Subject')}<input data-f="subject" value="${esc(s.subject || '')}"></label>` : ''}
          <label style="margin-bottom:0">${T('Text')}<textarea data-f="body" style="min-height:120px">${esc(s.body || '')}</textarea></label></details>
      </div></li>`).join('');
      $$('.step', box).forEach(li => {
        const i = +li.dataset.i;
        $$('[data-f]', li).forEach(inp => inp.addEventListener(inp.tagName === 'SELECT' ? 'change' : 'input', () => {
          steps[i][inp.dataset.f] = inp.type === 'number' ? +inp.value : inp.value;
          if (inp.dataset.f === 'kind') paintSteps();
          if (inp.dataset.f === 'day') paintPvSteps();
        }));
        const rm = $('[data-rm]', li); if (rm) rm.onclick = () => { steps.splice(i, 1); pstep = Math.min(pstep, steps.length - 1); paintSteps(); paintPvSteps(); };
      });
    }
    function paintPvSteps() {
      $('#pv-steps', el).innerHTML = steps.map((s, i) => `<button type="button" data-ps="${i}" class="${i === pstep ? 'on' : ''}">${T(i === 0 ? 'Email 1' : 'Email {n}', { n: i + 1 })}</button>`).join('');
      $$('[data-ps]', el).forEach(b => b.onclick = () => { pstep = +b.dataset.ps; paintPvSteps(); });
    }
    const form = $('#cf', el);
    const payload = () => ({ name: form.name.value, pitch: form.pitch.value, instructions: form.instructions.value, write_in_their_language: form.lang.checked,
                             auto_approve_followups: form.auto.checked, steps, active: c.active !== 0 });
    $('#addstep', el).onclick = () => {
      if (steps.length >= 6) return R.toast(t('Six emails is the most.'), 'err');
      steps.push({ day: (steps[steps.length - 1].day || 0) + 5, kind: 'ai', instructions: '', subject: '', body: '' });
      paintSteps(); paintPvSteps();
    };
    $('#pv-go', el).onclick = async e => {
      const r = await R.run(e.currentTarget, () => R.post(`/api/campaigns/${id || 0}/preview`, { draft: payload(), step: pstep, lead_id: +$('#pv-lead', el).value || 0 }));
      $('#pv-out', el).innerHTML = `<p style="margin-bottom:6px"><b>${esc(r.subject)}</b></p><div class="quote" style="max-height:none;background:var(--surface);border:1px solid var(--line)">${esc(r.body)}\n\n<span class="muted">${esc(r.footer)}</span></div>
        ${R.lintList(r.lint)}<p class="hint">${T(r.written_by === 'ai' ? 'Written by AI for {name}.' : 'From your template, for {name}.', { name: r.lead })}</p>`;
    };
    $('#save', el).onclick = async e => {
      if (!form.name.value.trim()) { form.name.focus(); return R.toast(t('Give the campaign a name.'), 'err'); }
      await R.run(e.currentTarget, () => id ? R.patch('/api/campaigns/' + id, payload()) : R.post('/api/campaigns', payload()), t('Campaign saved'));
      R.go('#/campaigns');
    };
    paintSteps(); paintPvSteps();
  }

  R.views.campaigns = {
    async render(el, { parts }) {
      if (parts[1] === 'new') return editor(el, null);
      if (parts[1] && /^\d+$/.test(parts[1])) return editor(el, +parts[1]);
      return list(el);
    },
  };
})();
