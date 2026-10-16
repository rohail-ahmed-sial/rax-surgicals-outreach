'use strict';
/* The setup guide: a few steps the first time (and again from Settings). Every step can be skipped and changed later. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  const STEPS = ['company', 'you', 'mailbox', 'ai', 'google', 'safety', 'done'];

  R.openWizard = async (start = 0) => {
    let i = start, s = await R.get('/api/settings');
    const w = document.createElement('div');
    w.className = 'wizard';
    w.setAttribute('role', 'dialog');
    w.setAttribute('aria-modal', 'true');
    document.body.append(w);
    document.body.style.overflow = 'hidden';
    const close = () => { w.remove(); document.body.style.overflow = ''; };

    const paint = () => {
      const F = R.fields(s);
      const step = STEPS[i];
      const nav = (next = true, skip = false) => `<div class="wizard__nav">
          ${i > 0 ? `<button class="btn" data-go="back">${R.icon('left')}${T('Back')}</button>` : ''}
          ${next ? `<button class="btn btn--primary" data-go="next">${T(i === STEPS.length - 2 ? 'Finish' : 'Next')}${R.icon('right')}</button>` : ''}
          ${skip ? `<button class="btn btn--ghost" data-go="skip">${T('Skip for now')}</button>` : ''}
          <span class="spacer"></span><button class="linkbtn" data-go="close" style="color:var(--ink-2)">${T('Close the guide')}</button></div>`;
      const body = {
        company: () => `<h1>${T(s.setup_done !== '1' ? 'wiz.welcome' : 'Your company')}</h1>${s.setup_done !== '1' ? `<p class="slogan">${T('Find buyers. Email them. Turn replies into orders.')}</p>` : ''}<p class="lead">${s.setup_done !== '1' ? T('wiz.welcome.lead') + ' ' : ''}${T('wiz.company.lead')}</p><form id="wf" onsubmit="return false">
          <div class="inline">${F.text('company_name', 'Company name')}${F.text('company_website', 'Website')}</div>
          ${F.text('company_address', 'Address', 'Shown at the bottom of every first email and follow-up (email laws ask for it).')}
          ${F.area('company_profile', 'What you make and offer', 'Products, steel, custom work, private label.', 4)}
          ${F.area('ideal_customer', 'Who is a good customer', 'And who is not.', 3)}</form>${nav()}`,
        you: () => `<h1>${T('About you')}</h1><p class="lead">${T('wiz.you.lead')}</p><form id="wf" onsubmit="return false">
          <div class="inline">${F.text('sender_name', 'Your name', '', 'autocomplete="name"')}${F.text('sender_title', 'Your job title', '', 'placeholder="Export Manager"')}</div>
          ${F.text('sender_email', 'Send from this email', 'wiz.you.email.hint', 'type="email" autocomplete="email"')}</form>${nav()}`,
        mailbox: () => `<h1>${T('Your mailbox')}</h1><p class="lead">${T('wiz.mailbox.lead')}</p><form id="wf" onsubmit="return false">
          <input type="hidden" name="sender_email" value="${esc(s.sender_email || '')}">${R.mailFields(s, F)}</form>
          <div class="row"><button class="btn" id="w-test">${R.icon('mail')}${T('Send a test to myself')}</button><button class="btn" id="w-imap">${R.icon('inbox')}${T('Test the inbox')}</button></div>
          <div id="w-out" style="margin-top:12px"></div>${nav(true, true)}`,
        ai: () => `<h1>${T('AI (Claude)')}</h1><p class="lead">${T('wiz.ai.lead')}</p>${R.steps('help.ai')}<form id="wf" onsubmit="return false">${F.secret('anthropic_api_key', 'Anthropic API key', '', 'sk-ant-…')}</form>
          <button class="btn" id="w-ai">${R.icon('spark')}${T('Test the key')}</button><div id="w-out" style="margin-top:12px"></div>${nav(true, true)}`,
        google: () => `<h1>${T('Google Maps search')}</h1><p class="lead">${T('wiz.google.lead')}</p>${R.steps('help.google_maps')}<form id="wf" onsubmit="return false">${F.secret('google_places_api_key', 'Google Places API key')}</form>
          <button class="btn" id="w-places">${R.icon('find')}${T('Test the key')}</button><div id="w-out" style="margin-top:12px"></div>${nav(true, true)}`,
        safety: () => `<h1>${T('How fast to send')}</h1><p class="lead">${T('wiz.safety.lead')}</p>
          <div class="bigchoice"><button data-warm="1" class="${s.warmup_on === '1' ? 'on' : ''}">${R.icon('sprout', 'ic--lg')}<b>${T('A new mailbox')}</b><span class="muted">${T('wiz.safety.new')}</span></button>
            <button data-warm="0" class="${s.warmup_on !== '1' ? 'on' : ''}">${R.icon('gauge', 'ic--lg')}<b>${T('A mailbox already in use')}</b><span class="muted">${T('wiz.safety.old')}</span></button></div>
          <p class="hint" style="margin-top:14px">${T('wiz.safety.hours')}</p>${nav()}`,
        done: () => {
          const st = [['smtp_host', 'Sending email'], ['imap_host', 'Reading replies'], ['anthropic_api_key', 'AI key'], ['google_places_api_key', 'Google Maps key']];
          return `<h1>${T('Ready')}</h1><p class="lead">${T('wiz.done.lead')}</p>
            <ul class="health" style="max-width:520px;margin-bottom:22px">${st.map(([k, l]) => `<li><span class="mark ${s[k] ? 'mark--ok' : 'mark--warn'}">${s[k] ? '✓' : '!'}</span><span><b>${T(l)}</b><br><span class="muted">${T(s[k] ? 'Set' : 'Not set yet: you can add it later in Settings')}</span></span></li>`).join('')}</ul>
            <div class="row"><button class="btn btn--primary" data-end="#/find">${R.icon('find')}${T('Find leads')}</button><button class="btn" data-end="#/campaigns/new">${R.icon('campaigns')}${T('Create a campaign')}</button><button class="btn btn--ghost" data-end="#/today">${T('Go to Today')}</button></div>`;
        },
      }[step]();
      w.innerHTML = `<div class="wizard__side"><a class="brand" href="#/today" tabindex="-1">${R.logo()}<div><b>RAX Surgicals Outreach</b><span>${T('Setup guide')}</span></div></a>
          <ol class="wsteps">${STEPS.map((k, n) => `<li class="${n === i ? 'on' : n < i ? 'done' : ''}">${T('wiz.step.' + k)}</li>`).join('')}</ol></div>
        <div class="wizard__main">${body}</div>`;
      R.wireSecrets(w);
      const form = $('#wf', w);
      if (step === 'mailbox') R.wireProviders(w, form);
      const out = $('#w-out', w);
      const saveForm = async () => { if (form) { const v = R.collect(form); Object.assign(s, v); await R.post('/api/settings', v); s = await R.get('/api/settings'); } };
      const tryTest = async (btn, path, okText) => {
        try { await saveForm(); const r = await R.run(btn, () => R.post(path, path.endsWith('smtp') ? { to: s.sender_email } : {})); R.testResult(out, true, okText(r)); }
        catch (e) { R.testResult(out, false, esc(R.errText(e))); }
      };
      if ($('#w-test', w)) $('#w-test', w).onclick = e => tryTest(e.currentTarget, '/api/test/smtp', r => T('Test email sent to {to}. Look in that inbox (and in spam).', { to: r.to }));
      if ($('#w-imap', w)) $('#w-imap', w).onclick = e => tryTest(e.currentTarget, '/api/test/imap', r => T('The inbox opened: {n} emails in it.', { n: r.count }));
      if ($('#w-ai', w)) $('#w-ai', w).onclick = e => tryTest(e.currentTarget, '/api/test/ai', r => T('The AI works. It said: "{said}"', { said: r.said }));
      if ($('#w-places', w)) $('#w-places', w).onclick = e => tryTest(e.currentTarget, '/api/test/places', () => T('The Google key works.'));
      $$('[data-warm]', w).forEach(b => b.onclick = () => { $$('[data-warm]', w).forEach(x => x.classList.toggle('on', x === b)); s.warmup_on = b.dataset.warm; });
      $$('[data-go]', w).forEach(b => b.onclick = async () => {
        const go = b.dataset.go;
        if (go === 'close') { close(); await R.post('/api/setup/done'); R.route(); return; }
        if (go === 'back') { i = Math.max(0, i - 1); return paint(); }
        if (go === 'next') {
          try {
            if (step === 'safety') await R.post('/api/settings', s.warmup_on === '1' ? { warmup_on: '1', warmup_start: '10', warmup_step: '5', warmup_every_days: '7', daily_limit: '40' } : { warmup_on: '0', daily_limit: '40' });
            else await R.run(b, saveForm);
          } catch (e) { return; }
          if (step === 'safety') { await R.post('/api/setup/done'); s = await R.get('/api/settings'); }
        }
        i = Math.min(STEPS.length - 1, i + 1); paint();
        $('.wizard__main', w).scrollIntoView({ block: 'start' });
      });
      $$('[data-end]', w).forEach(b => b.onclick = async () => { await R.post('/api/setup/done'); close(); R.refreshBadges(); R.go(b.dataset.end); });
      const first = $('.wizard__main input:not([type=hidden]), .wizard__main .bigchoice button.on', w);
      if (first) setTimeout(() => first.focus(), 30);
    };
    paint();
  };
})();
