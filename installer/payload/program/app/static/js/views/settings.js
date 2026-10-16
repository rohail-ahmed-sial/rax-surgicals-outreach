'use strict';
/* Settings, in sections. Each section saves on its own. Mailbox has presets for common providers, test buttons that
   explain errors in plain words, and a check of the sending domain (SPF, DKIM, DMARC). */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;

  R.PROVIDERS = {
    google: { name: 'Google Workspace / Gmail', smtp_host: 'smtp.gmail.com', smtp_port: '587', smtp_security: 'starttls', imap_host: 'imap.gmail.com', imap_port: '993' },
    zoho: { name: 'Zoho Mail', smtp_host: 'smtp.zoho.com', smtp_port: '465', smtp_security: 'ssl', imap_host: 'imap.zoho.com', imap_port: '993' },
    microsoft: { name: 'Microsoft 365 / Outlook', smtp_host: 'smtp.office365.com', smtp_port: '587', smtp_security: 'starttls', imap_host: 'outlook.office365.com', imap_port: '993' },
    hostinger: { name: 'Hostinger', smtp_host: 'smtp.hostinger.com', smtp_port: '465', smtp_security: 'ssl', imap_host: 'imap.hostinger.com', imap_port: '993' },
    cpanel: { name: 'cPanel', smtp_host: 'mail.{domain}', smtp_port: '465', smtp_security: 'ssl', imap_host: 'mail.{domain}', imap_port: '993' },
    other: { name: 'Other' },
  };
  /* steps as a numbered list, from a translated text with one step per line */
  R.steps = key => `<ol class="guide">${t(key).split('\n').filter(Boolean).map(l => `<li>${R.linkify(esc(l))}</li>`).join('')}</ol>`;
  R.linkify = s => s.replace(/(https?:\/\/[^\s<]+[^\s<.,)])/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');

  /* form field helpers bound to a settings object */
  R.fields = s => ({
    text: (k, label, hint = '', attrs = '') => `<label>${T(label)}${hint ? `<span class="hint">${T(hint)}</span>` : ''}<input name="${k}" value="${esc(s[k] ?? '')}" ${attrs}></label>`,
    area: (k, label, hint = '', rows = 4) => `<label>${T(label)}${hint ? `<span class="hint">${T(hint)}</span>` : ''}<textarea name="${k}" rows="${rows}">${esc(s[k] ?? '')}</textarea></label>`,
    num: (k, label, hint = '', cls = 'w-s') => `<label class="${cls}">${T(label)}${hint ? `<span class="hint">${T(hint)}</span>` : ''}<input name="${k}" type="number" inputmode="numeric" value="${esc(s[k] ?? '')}"></label>`,
    secret: (k, label, hint = '', ph = '') => `<label class="secret">${T(label)}${hint ? `<span class="hint">${T(hint)}</span>` : ''}<input name="${k}" type="password" value="${esc(s[k] ?? '')}" autocomplete="new-password" placeholder="${esc(ph)}" spellcheck="false"><button type="button" class="linkbtn" data-show>${T('show')}</button></label>`,
    check: (k, label, hint = '') => `<label class="check"><input type="checkbox" name="${k}" ${s[k] === '1' ? 'checked' : ''}><span>${T(label)}${hint ? `<span class="hint">${T(hint)}</span>` : ''}</span></label>`,
    select: (k, label, opts, hint = '') => `<label>${T(label)}${hint ? `<span class="hint">${T(hint)}</span>` : ''}<select name="${k}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${String(s[k]) === String(v) ? 'selected' : ''}>${T(l)}</option>`).join('')}</select></label>`,
  });
  R.collect = form => {
    const out = {};
    $$('[name]', form).forEach(i => { if (i.type === 'checkbox') out[i.name] = i.checked ? '1' : '0'; else if (i.type !== 'radio' || i.checked) out[i.name] = i.value; });
    return out;
  };
  R.wireSecrets = root => $$('[data-show]', root).forEach(b => b.onclick = () => { const i = b.previousElementSibling; i.type = i.type === 'password' ? 'text' : 'password'; b.textContent = t(i.type === 'password' ? 'show' : 'hide'); });
  R.testResult = (box, ok, html) => { box.innerHTML = R.note(html, ok ? 'good' : 'bad'); };
  R.applyProvider = (form, key) => {
    const p = R.PROVIDERS[key]; if (!p || !p.smtp_host) return;
    const dom = ((form.sender_email && form.sender_email.value) || '').split('@')[1] || 'yourdomain.com';
    ['smtp_host', 'smtp_port', 'smtp_security', 'imap_host', 'imap_port'].forEach(k => { if (form[k]) form[k].value = p[k].replace('{domain}', dom); });
    if (form.smtp_user && !form.smtp_user.value && form.sender_email) form.smtp_user.value = form.sender_email.value;
  };
  R.mailFields = (s, F) => `
    <div class="providers">${Object.entries(R.PROVIDERS).map(([k, p]) => `<button type="button" class="provider ${s.email_provider === k ? 'on' : ''}" data-prov="${k}">${R.icon(['hostinger', 'cpanel', 'other'].includes(k) ? 'server' : 'mail')}<b>${esc(k === 'other' ? t('Other') : k === 'cpanel' ? t('cPanel hosting') : p.name)}</b><small class="muted">${T('prov.' + k)}</small></button>`).join('')}</div>
    <input type="hidden" name="email_provider" value="${esc(s.email_provider || '')}">
    <div id="prov-help">${s.email_provider ? R.steps('help.' + s.email_provider) : ''}</div>
    <div class="inline">${F.text('smtp_host', 'Outgoing server (SMTP)', '', 'placeholder="smtp.gmail.com"')}${F.num('smtp_port', 'Port')}
      ${F.select('smtp_security', 'Security', [['starttls', 'STARTTLS (587)'], ['ssl', 'SSL (465)'], ['none', 'None']])}</div>
    <div class="inline">${F.text('smtp_user', 'Username', 'Usually your full email address.', 'autocomplete="off"')}${F.secret('smtp_password', 'Password', 'For Google and Zoho: an app password, not your normal one.')}</div>
    <div class="inline">${F.text('imap_host', 'Incoming server (IMAP)', 'For reading replies.')}${F.num('imap_port', 'Port')}${F.text('imap_folder', 'Folder')}</div>
    <p class="hint" style="margin-top:-6px">${T('IMAP uses the same username and password unless you fill these in:')}</p>
    <div class="inline">${F.text('imap_user', 'IMAP username (optional)', '', 'autocomplete="off"')}${F.secret('imap_password', 'IMAP password (optional)')}</div>`;
  R.wireProviders = (root, form) => $$('[data-prov]', root).forEach(b => b.onclick = () => {
    $$('[data-prov]', root).forEach(x => x.classList.toggle('on', x === b));
    form.email_provider.value = b.dataset.prov;
    R.applyProvider(form, b.dataset.prov);
    $('#prov-help', root).innerHTML = b.dataset.prov === 'other' ? R.steps('help.other') : R.steps('help.' + b.dataset.prov);
  });

  const SECTIONS = ['company', 'mailbox', 'sending', 'ai', 'google', 'forwarding', 'files', 'donotemail', 'backup', 'access'];
  const SEC_ICONS = { company: 'building', mailbox: 'mail', sending: 'gauge', ai: 'spark', google: 'pin', forwarding: 'forward',
                      files: 'clip', donotemail: 'block', backup: 'database', access: 'key' };

  R.views.settings = {
    async render(el, { parts }) {
      let sec = SECTIONS.includes(parts[1]) ? parts[1] : 'company';
      el.innerHTML = `<div class="head"><div><h1>${T('nav.settings')}</h1><p>${T('settings.lead')}</p></div>
        <div class="head__actions"><button class="btn" id="wiz">${R.icon('help')}${T('Open setup guide')}</button></div></div>
        <div class="settings"><nav class="subnav" id="subnav"></nav><div id="sec"></div></div>`;
      $('#wiz', el).onclick = () => R.openWizard();
      const nav = () => {
        $('#subnav', el).innerHTML = SECTIONS.map(k => `<button data-s="${k}" class="${k === sec ? 'on' : ''}">${R.icon(SEC_ICONS[k])}${T('set.' + k)}</button>`).join('');
        $$('[data-s]', el).forEach(b => b.onclick = () => { sec = b.dataset.s; history.replaceState(null, '', '#/settings/' + sec); nav(); paint(); });
      };
      const paint = async () => {
        const s = await R.get('/api/settings');
        let auto = null;
        if (sec === 'sending') { try { auto = await R.get('/api/autostart'); } catch (e) { auto = null; } }
        const F = R.fields(s);
        const box = $('#sec', el);
        const formWrap = (inner, extra = '') => `<form class="panel" id="sf" onsubmit="return false">${inner}</form>${extra}<div class="savebar"><button class="btn btn--primary" id="save">${T('Save')}</button></div>`;
        const html = {
          company: () => formWrap(`<h2>${T('Your company')}</h2><p class="hint" style="margin:4px 0 14px">${T('The AI uses this to judge leads and write emails. Write only what is true.')}</p>
              <div class="inline">${F.text('company_name', 'Company name')}${F.text('company_website', 'Website')}</div>
              ${F.text('company_address', 'Address', 'Shown at the bottom of every first email and follow-up (email laws ask for it).')}
              ${F.area('company_profile', 'What you make and offer', 'Products, steel, custom work, private label.', 4)}
              ${F.area('ideal_customer', 'Who is a good customer', 'And who is not.', 3)}
              <hr class="sep"><h2>${T('Facts for the AI')}</h2><p class="hint" style="margin:4px 0 14px">${T('facts.hint')}</p>
              <div class="inline">${F.text('fact_moq', 'Minimum order', '', 'placeholder="50 pieces per item"')}${F.text('fact_lead_time', 'Production and delivery time', '', 'placeholder="4 to 6 weeks"')}</div>
              <div class="inline">${F.text('fact_payment_terms', 'Payment terms', '', 'placeholder="50% advance, 50% before shipping"')}${F.text('fact_samples', 'Samples', '', 'placeholder="Free samples, buyer pays courier"')}</div>
              <div class="inline">${F.text('fact_certifications', 'Certificates you really have', '', 'placeholder="ISO 13485, CE"')}${F.text('fact_shipping', 'Shipping', '', 'placeholder="DHL, FedEx, sea freight"')}</div>
              ${F.text('fact_catalogue_link', 'Catalogue link', 'A web address of your catalogue. Leave empty to attach the PDF by hand.', 'placeholder="https://raxsurgicals.com/catalogue.pdf"')}
              ${F.area('fact_other', 'Other facts', '', 2)}
              <hr class="sep"><h2>${T('Sender')}</h2>
              <div class="inline">${F.text('sender_name', 'Your name')}${F.text('sender_title', 'Your job title')}</div>
              <div class="inline">${F.text('sender_email', 'Send from this email', '', 'type="email"')}${F.text('reply_to', 'Replies go to (optional)', 'Leave empty to use the same email.', 'type="email"')}</div>
              ${F.area('signature', 'Signature (optional)', 'Leave empty to build one from your name, title, company and website.', 3)}`),
          mailbox: () => formWrap(`<h2>${T('Your mailbox')}</h2><p class="hint" style="margin:4px 0 14px">${T('Choose your email provider: the servers fill in by themselves.')}</p>
              ${R.mailFields(s, F)}
              ${F.select('save_sent_copy', 'Keep a copy of sent emails in the Sent folder', [['auto', 'Automatic (Google and Microsoft do it themselves)'], ['on', 'Always'], ['off', 'Never']])}
              <div class="row"><input id="testto" type="email" placeholder="${T('send the test to…')}" value="${esc(s.sender_email || '')}" style="width:260px;margin:0">
                <button type="button" class="btn" id="t-smtp">${R.icon('mail')}${T('Save and send a test')}</button>
                <button type="button" class="btn" id="t-imap">${R.icon('inbox')}${T('Save and test the inbox')}</button></div>
              <div id="t-out" style="margin-top:12px"></div>`,
              `<div class="panel"><div class="panel__head"><h2>${T('Is your domain ready for sending?')}</h2><button class="btn btn--sm" id="dns">${R.icon('refresh')}${T('Check')}</button></div>
                <p class="hint">${T('dns.hint')}</p><div id="dns-out"></div></div>`),
          sending: () => formWrap(`<h2>${T('Daily limit and warm-up')}</h2><p class="hint" style="margin:4px 0 14px">${T('warmup.hint')}</p>
              ${F.num('daily_limit', 'Emails per day when fully warmed up', 'At most 200. 30 to 50 per mailbox is a safe goal.', '')}
              ${F.check('warmup_on', 'Warm up: start low and go up every week', 'Recommended for a new mailbox or a new domain.')}
              <div class="inline">${F.num('warmup_start', 'Start with (per day)')}${F.num('warmup_step', 'Add each step')}${F.num('warmup_every_days', 'Step every (days)')}</div>
              <hr class="sep"><h2>${T('When to send')}</h2>
              <div class="inline">${F.num('send_hour_start', 'From (their local hour)')}${F.num('send_hour_end', 'Until')}${F.num('gap_min_minutes', 'Gap between emails, minutes, from')}${F.num('gap_max_minutes', 'to')}</div>
              ${F.check('send_weekdays_only', 'Weekdays only (in their country)')}
              ${F.select('my_timezone', 'Your own time zone', [['Asia/Karachi', 'Pakistan'], ['Asia/Dubai', 'UAE'], ['Europe/London', 'United Kingdom'], ['Asia/Riyadh', 'Saudi Arabia'], ['Asia/Kolkata', 'India'], ['America/New_York', 'USA (East)'], ['Europe/Berlin', 'Central Europe']], 'Used for "today" and the charts.')}
              <hr class="sep"><h2>${T('Protection')}</h2>
              ${F.check('bounce_guard_on', 'Pause sending when too many emails bounce')}
              ${F.num('bounce_guard_pct', 'Pause above this bounce rate (%)', 'Checked over the last 50 emails.', '')}
              ${F.check('mx_check_on', 'Check that a company\'s domain takes email before the first email')}`,
              auto && auto.supported ? `<div class="panel"><h2 class="h-ic">${R.icon('power')}${T('Start with Windows')}</h2>
                <p class="hint" style="margin:4px 0 12px">${T('autostart.hint')}</p>
                <label class="check"><input type="checkbox" id="autostart" ${auto.on ? 'checked' : ''}><span>${T('Start RAX Surgicals Outreach when Windows starts')}</span></label></div>` : ''),
          ai: () => formWrap(`<h2>${T('AI (Claude)')}</h2>${R.steps('help.ai')}
              ${F.secret('anthropic_api_key', 'Anthropic API key', '', 'sk-ant-…')}
              <div class="row"><button type="button" class="btn" id="t-ai">${R.icon('spark')}${T('Save and test')}</button><span class="muted">${T('{n} AI calls today', { n: s.ai_calls_today })}</span></div>
              <div id="t-out" style="margin-top:12px"></div>
              <hr class="sep">${F.num('ai_daily_call_limit', 'Most AI calls per day', 'A cap on cost. About 400 calls cost a few dollars.', '')}
              <details><summary class="muted" style="cursor:pointer;margin-bottom:10px">${T('Models and prices (advanced)')}</summary>
                <div class="inline">${F.text('ai_model_fast', 'Model for checking leads and replies')}${F.text('ai_model_writer', 'Model for writing emails')}</div>
                <p class="hint">${T('Prices in US dollars per million tokens, only for the cost estimate.')}</p>
                <div class="inline">${F.text('price_fast_in', 'Fast model, input')}${F.text('price_fast_out', 'Fast model, output')}${F.text('price_writer_in', 'Writer model, input')}${F.text('price_writer_out', 'Writer model, output')}</div></details>`),
          google: () => formWrap(`<h2>${T('Google Maps search')}</h2>${R.steps('help.google_maps')}
              ${F.secret('google_places_api_key', 'Google Places API key')}
              <div class="row"><button type="button" class="btn" id="t-places">${R.icon('find')}${T('Save and test')}</button><span class="hint">${T('The test makes one small search.')}</span></div>
              <div id="t-out" style="margin-top:12px"></div>`),
          forwarding: () => formWrap(`<h2>${T('Forward replies')}</h2><p class="hint" style="margin:4px 0 14px">${T('forward.hint')}</p>
              ${F.check('forward_on', 'Forward replies by themselves')}
              ${F.text('forward_to', 'Forward to', '', 'type="email" placeholder="partner@raxsurgicals.com"')}
              <input type="hidden" name="forward_kinds" value="${esc(s.forward_kinds || '')}">
              <p style="font-weight:600;font-size:13px;margin-bottom:8px">${T('Which replies')}</p>
              ${['interested', 'question', 'not_interested', 'wrong_person', 'other'].map(k => `<label class="check"><input type="checkbox" data-kind="${k}" ${(s.forward_kinds || '').split(',').includes(k) ? 'checked' : ''}><span>${T('kind.' + k)}</span></label>`).join('')}`),
          files: () => `<div class="panel"><h2>${T('Files for attachments')}</h2><p class="hint" style="margin:4px 0 14px">${T('files.hint')}</p>
              <label class="btn" style="margin-bottom:14px">${R.icon('upload')}${T('Upload a file')}<input type="file" id="up" hidden></label><div id="flist"></div></div>`,
          donotemail: () => `<div class="panel"><h2>${T('Do not email')}</h2><p class="hint" style="margin:4px 0 14px">${T('dne.hint')}</p>
              <form class="row" id="dnef" style="margin-bottom:12px"><input name="emails" placeholder="name@company.com, @competitor.com" style="flex:1;margin:0"><button class="btn">${T('Add')}</button></form><div id="dnelist"></div></div>`,
          backup: () => `<div class="panel"><h2>${T('Backup')}</h2><p class="hint" style="margin:4px 0 14px">${T('backup.hint')}</p>
              <div class="row"><a class="btn btn--primary" href="/api/backup">${R.icon('download')}${T('Download a backup now')}</a>
              <label class="btn" style="margin:0">${R.icon('upload')}${T('Restore from a backup file')}<input type="file" id="restore" accept=".db" hidden></label></div>
              <div id="blist" style="margin-top:16px"></div></div>`,
          access: () => `<form class="panel" id="pwf"><h2>${T('Password')}</h2><p class="hint" style="margin:4px 0 14px">${T(s.password_set ? 'A password is set. It is asked when the dashboard is opened.' : 'pw.hint')}</p>
              ${s.password_set ? `<label>${T('Current password')}<input type="password" name="current" autocomplete="current-password"></label>` : ''}
              <label>${T('New password')}<input type="password" name="password" minlength="8" autocomplete="new-password" required></label>
              <button class="btn btn--primary">${T('Set password')}</button></form>
              <div class="panel"><h2>${T('Desktop alerts')}</h2><p class="hint" style="margin:4px 0 14px">${T('Get a desktop alert when a reply arrives (while the dashboard is open in your browser).')}</p>
              <div class="row"><button class="btn" id="notif">${R.icon('bell')}${T('Turn on alerts')}</button><span class="hint" id="notif-st" style="margin:0"></span></div></div>`,
        }[sec]();
        box.innerHTML = html;
        R.wireSecrets(box);
        const form = $('#sf', box);
        const save = async btn => {
          const vals = R.collect(form);
          if (sec === 'forwarding') vals.forward_kinds = $$('[data-kind]', box).filter(c => c.checked).map(c => c.dataset.kind).join(',');
          await R.run(btn, () => R.post('/api/settings', vals), btn && btn.id === 'save' ? t('Saved') : null);
        };
        const sv = $('#save', box);
        if (sv) sv.onclick = () => save(sv);
        const as = $('#autostart', box);
        if (as) as.onchange = async () => {
          try { const r = await R.post('/api/autostart', { on: as.checked }); as.checked = r.on; R.toast(t(r.on ? 'RAX Surgicals Outreach now starts with Windows' : 'RAX Surgicals Outreach no longer starts with Windows')); }
          catch (e) { as.checked = !as.checked; R.fail(e); }
        };
        if (sec === 'mailbox') {
          R.wireProviders(box, form);
          const out = $('#t-out', box);
          $('#t-smtp', box).onclick = async e => {
            await save(null);
            try { const r = await R.run(e.currentTarget, () => R.post('/api/test/smtp', { to: $('#testto', box).value })); R.testResult(out, true, T('Test email sent to {to}. Look in that inbox (and in spam).', { to: r.to })); }
            catch (err) { R.testResult(out, false, esc(R.errText(err)) + `<br><small class="muted">${esc(err.message)}</small>`); }
            R.refreshBadges();
          };
          $('#t-imap', box).onclick = async e => {
            await save(null);
            try { const r = await R.run(e.currentTarget, () => R.post('/api/test/imap')); R.testResult(out, true, T('The inbox opened: {n} emails in it.', { n: r.count })); }
            catch (err) { R.testResult(out, false, esc(R.errText(err)) + `<br><small class="muted">${esc(err.message)}</small>`); }
          };
          const dns = async btn => {
            const o = $('#dns-out', box);
            try {
              const r = await R.run(btn, () => R.get('/api/check/domain'));
              o.innerHTML = r.items && r.items.length ? `<p style="margin:10px 0 6px"><b>${esc(r.domain)}</b></p><ul class="health">${r.items.map(i => `<li><span class="mark mark--${i.status}">${i.status === 'ok' ? '✓' : i.status === 'unknown' ? '?' : '!'}</span>
                <span><b>${T('dnsk.' + i.key)}</b><br><span class="muted">${T('dns.' + i.code, Object.assign({ domain: r.domain, selector: (i.data || {}).selector || '', policy: (i.data || {}).policy || '' }))}</span></span></li>`).join('')}</ul>`
                : R.note(T('Set the sender email in Your company first.'), 'info');
            } catch (e) { /* toast shown */ }
          };
          $('#dns', box).onclick = e => dns(e.currentTarget);
          if (s.sender_email) dns($('#dns', box));
        }
        if (sec === 'ai') $('#t-ai', box).onclick = async e => {
          await save(null);
          try { const r = await R.run(e.currentTarget, () => R.post('/api/test/ai')); R.testResult($('#t-out', box), true, T('The AI works. It said: "{said}"', { said: r.said })); }
          catch (err) { R.testResult($('#t-out', box), false, esc(R.errText(err))); }
        };
        if (sec === 'google') $('#t-places', box).onclick = async e => {
          await save(null);
          try { await R.run(e.currentTarget, () => R.post('/api/test/places')); R.testResult($('#t-out', box), true, T('The Google key works.')); }
          catch (err) { R.testResult($('#t-out', box), false, esc(R.errText(err))); }
        };
        if (sec === 'files') {
          const list = async () => {
            const files = await R.get('/api/files');
            $('#flist', box).innerHTML = files.length ? `<table><tbody>${files.map(f => `<tr><td>${R.icon('file', 'ic--sm')} <a href="/api/files/${f.id}/download">${esc(f.name)}</a></td><td class="muted">${R.size(f.size)}</td><td class="muted">${esc(R.fmtDate(f.created_at))}</td><td class="r"><button class="linkbtn linkbtn--danger" data-del="${f.id}">${T('Delete')}</button></td></tr>`).join('')}</tbody></table>`
              : `<p class="muted">${T('No files yet.')}</p>`;
            $$('[data-del]', box).forEach(b => b.onclick = async () => { if (await R.confirm(t('Delete this file?'), '', { ok: t('Delete'), danger: true })) { await R.del('/api/files/' + b.dataset.del); list(); } });
          };
          $('#up', box).onchange = async e => {
            const f = e.target.files[0]; if (!f) return;
            if (f.size > 15e6) return R.toast(t('err.too_large'), 'err');
            await R.run(null, () => R.api('POST', '/api/files', f, { type: f.type || 'application/octet-stream', name: f.name }), t('Uploaded'));
            e.target.value = ''; list();
          };
          list();
        }
        if (sec === 'donotemail') {
          const list = async () => {
            const rows = await R.get('/api/suppression');
            $('#dnelist', box).innerHTML = rows.length ? `<div class="tablewrap" style="max-height:420px"><table><thead><tr><th>${T('Email or domain')}</th><th>${T('Why')}</th><th>${T('Since')}</th><th></th></tr></thead><tbody>${rows.map(x => `<tr><td>${esc(x.email)}</td><td class="muted">${T('why.' + (x.reason || 'added by you').replace(/ /g, '_'))}</td><td class="muted">${esc(R.fmtDate(x.created_at))}</td><td class="r"><button class="linkbtn" data-un="${esc(x.email)}">${T('remove')}</button></td></tr>`).join('')}</tbody></table></div>`
              : `<p class="muted">${T('The list is empty.')}</p>`;
            $$('[data-un]', box).forEach(b => b.onclick = async () => { await R.post('/api/suppression/remove', { email: b.dataset.un }); list(); });
          };
          $('#dnef', box).onsubmit = async e => { e.preventDefault(); const r = await R.run(e.submitter, () => R.post('/api/suppression', { emails: e.target.emails.value }), r => R.tn(r.added, '1 added', '{n} added')); e.target.reset(); list(); return r; };
          list();
        }
        if (sec === 'backup') {
          const b = await R.get('/api/backups');
          $('#blist', box).innerHTML = `<p class="hint">${T('Automatic copies (one a day) are kept in: {folder}', { folder: b.folder })}</p>` +
            (b.files.length ? `<table><tbody>${b.files.slice(0, 20).map(f => `<tr><td>${esc(f.name)}</td><td class="muted">${R.size(f.size)}</td><td class="muted">${esc(R.fmtDT(f.at))}</td></tr>`).join('')}</tbody></table>` : `<p class="muted">${T('No copies yet. The first one is made today.')}</p>`);
          $('#restore', box).onchange = async e => {
            const f = e.target.files[0]; if (!f) return;
            if (!await R.confirm(t('Restore this backup?'), t('restore.text'), { ok: t('Restore'), danger: true })) { e.target.value = ''; return; }
            await R.run(null, () => R.api('POST', '/api/restore', f, { type: 'application/octet-stream' }), t('Restored. The page reloads now.'));
            setTimeout(() => location.reload(), 1200);
          };
        }
        if (sec === 'access') {
          $('#pwf', box).onsubmit = async e => { e.preventDefault(); await R.run(e.submitter, () => R.post('/api/settings/password', Object.fromEntries(new FormData(e.target))), t('Password set')); paint(); };
          const st = () => { $('#notif-st', box).textContent = !('Notification' in window) ? t('This browser cannot show alerts.') : Notification.permission === 'granted' ? t('Alerts are on.') : Notification.permission === 'denied' ? t('Alerts are blocked in the browser settings.') : ''; };
          $('#notif', box).onclick = async () => { try { await Notification.requestPermission(); } catch (e) {} st(); };
          st();
        }
      };
      nav(); await paint();
    },
  };
})();
