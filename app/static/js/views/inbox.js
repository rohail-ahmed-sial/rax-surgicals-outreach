'use strict';
/* Inbox: replies from leads, grouped by company. Answer from here (AI can write the first draft), attach the catalogue,
   forward to a colleague, and move the deal along the pipeline. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  const FILTERS = ['needs', 'interested', 'all', 'bounces'];

  R.views.inbox = {
    async render(el, { parts, params }) {
      let f = params.get('f') || 'needs', list = { rows: [], counts: {} }, leadId = +(parts[1] || 0) || null, thread = null, attach = [];
      el.innerHTML = `<div class="head"><div><h1>${T('nav.inbox')}</h1><p>${T('inbox.lead')}</p></div>
        <div class="head__actions"><button class="btn" id="check">${R.icon('refresh')}${T('Check for new replies')}</button></div></div>
        <div id="notif"></div>
        <div class="mail2"><div class="convos"><div class="tabs" id="ftabs"></div><div class="queue__list" id="clist"></div></div><div id="pane"></div></div>`;
      if ('Notification' in window && Notification.permission === 'default') {
        $('#notif', el).innerHTML = `<div class="note note--info">${R.icon('bell')}<div>${T('Get a desktop alert when a reply arrives?')} <button class="linkbtn" id="notif-on">${T('Turn on')}</button></div></div>`;
        $('#notif-on', el).onclick = async () => { try { await Notification.requestPermission(); } catch (e) {} $('#notif', el).innerHTML = ''; };
      }
      $('#check', el).onclick = async e => {
        await R.run(e.currentTarget, () => R.post('/api/inbox/check', { days: 30 }), t('Checking your inbox…'));
        setTimeout(() => R.quiet(loadList()), 5000);
      };

      const loadList = async (initial = false) => {
        list = await R.get('/api/inbox?f=' + f);
        $('#ftabs', el).innerHTML = FILTERS.map(k => `<button data-f="${k}" class="${k === f ? 'on' : ''}">${T('inbox.f.' + k)}${k === 'needs' && list.counts.needs ? ` ${R.pill(list.counts.needs, 'good')}` : ''}</button>`).join('');
        $$('[data-f]', el).forEach(b => b.onclick = () => { f = b.dataset.f; R.quiet(loadList()); });
        $('#clist', el).innerHTML = list.rows.length ? list.rows.map(c => `<button class="convo ${c.open ? 'open' : ''} ${c.lead_id === leadId ? 'on' : ''}" data-lead="${c.lead_id}">
            ${R.avatar(c.company)}<span class="convo__body"><div class="convo__top"><b class="ell">${esc(c.company)}</b><time>${esc(R.ago(c.last.received_at))}</time></div>
            <div class="row row--tight" style="margin-top:4px">${R.kindPill(c.last.kind)} ${c.stage && c.stage !== 'interested' ? R.stagePill(c.stage) : ''} <small class="muted">${esc(c.country || '')}</small></div>
            <p>${esc(c.last.summary || c.last.subject || '')}</p></span></button>`).join('')
          : `<div class="empty" style="padding:30px 16px"><p>${T(f === 'needs' ? 'No replies are waiting for an answer.' : 'Nothing here yet.')}</p></div>`;
        $$('.convo', el).forEach(b => b.onclick = async () => {
          leadId = +b.dataset.lead; history.replaceState(null, '', '#/inbox/' + leadId); markList();
          await R.quiet(loadThread());
          if (innerWidth <= 900) $('#pane', el).scrollIntoView({ block: 'start', behavior: 'smooth' });   // phones: the thread is under the list
        });
        if (!leadId && list.rows.length && innerWidth > 900) { leadId = list.rows[0].lead_id; markList(); if (!initial) R.quiet(loadThread()); }
        if (!leadId) $('#pane', el).innerHTML = `<div class="panel pane-empty">${R.empty({ icon: 'inbox', title: t('No conversation open'), text: t('Replies to your emails show up here, sorted by company.') })}</div>`;
      };
      const markList = () => $$('.convo', el).forEach(b => b.classList.toggle('on', +b.dataset.lead === leadId));

      const loadThread = async () => {
        thread = await R.get('/api/inbox/' + leadId);
        attach = [];
        paintThread();
      };

      const paintThread = () => {
        const th = thread, l = th.lead;
        const answerable = !!th.answer_to;
        const lastBounce = th.items.length && th.items[th.items.length - 1].kind === 'bounce';
        const n = th.items.length;
        $('#pane', el).innerHTML = `<div class="panel" style="margin-bottom:12px">
            <div class="panel__head" style="margin-bottom:6px"><h2 style="font-family:var(--display);font-size:21px">${esc(l.company)}</h2>
              <div class="row"><button class="btn btn--sm" id="open-lead">${R.icon('user')}${T('Lead details')}</button>
              <button class="btn btn--sm" id="fwd">${R.icon('forward')}${T('Forward')}</button>
              <button class="btn btn--sm" id="done">${R.icon('check')}${T('Mark as done')}</button></div></div>
            <div class="row"><span class="muted">${esc([l.contact_name, l.email, l.country].filter(Boolean).join(', '))}</span><span class="spacer"></span>
              <label class="row" style="margin:0;font-weight:500">${T('Stage')}<select id="stage" style="width:auto;margin:0;min-height:32px;padding:4px 8px">
                <option value="">${T('Not in the pipeline')}</option>${R.STAGES.map(s => `<option value="${s}" ${s === l.stage ? 'selected' : ''}>${T('stage.' + s)}</option>`).join('')}</select></label></div></div>
          <div class="thread">${th.items.map((it, i) => {
            const folded = i < n - 3 && it.who !== 'them' || i < n - 4;
            const who = it.who === 'us' ? (it.kind === 'reply' ? t('You answered') : t('Your email {n}', { n: (it.step || 0) + 1 })) : it.who === 'fwd' ? t('Forwarded to {to}', { to: it.to }) : (it.from || l.company);
            return `<div class="msg msg--${it.who} ${folded ? 'folded' : ''}">
              <div class="msg__head" data-fold><b>${esc(who)}</b>${it.who === 'them' ? R.kindPill(it.kind) : ''}<span class="muted ell" style="max-width:40%">${esc(it.subject || '')}</span><time>${esc(R.fmtDT(it.at))}</time></div>
              ${it.who === 'them' && it.summary ? `<div style="padding:0 16px 8px"><small class="muted">${R.icon('spark', 'ic--sm')} ${esc(it.summary)}</small></div>` : ''}
              <div class="msg__body">${esc(it.body || '')}</div>
              ${it.files && it.files.length ? `<div class="msg__files">${it.files.map(fl => `<a class="chip" href="/api/files/${fl.id}/download">${R.icon('clip', 'ic--sm')}${esc(fl.name)}</a>`).join('')}</div>` : ''}</div>`; }).join('')}</div>
          ${lastBounce ? `<div style="margin-top:12px">${R.note(T('This address bounced. Find another email for this company in Lead details.'), 'bad')}</div>` : ''}
          ${answerable && !lastBounce ? `<div class="compose" style="margin-top:12px">
            <div class="row" style="margin-bottom:8px"><h3>${T('Your answer')}</h3><span class="spacer"></span>
              <button class="btn btn--sm" id="ai">${R.icon('spark')}${T('Write with AI')}</button></div>
            <label style="margin-bottom:8px">${T('Subject')}<input id="c-subj" value="${esc(th.subject)}"></label>
            <textarea id="c-body" placeholder="${T('Write your answer, or press "Write with AI".')}">${esc(th.draft || '')}</textarea>
            <div id="c-lint"></div>
            <div class="files" id="c-files"></div>
            <p class="hint" style="white-space:pre-wrap;margin:6px 0 12px">${esc(th.footer)}</p>
            <div class="row"><button class="btn btn--go" id="send">${R.icon('outbox')}${T('Send answer')}</button>
              <button class="btn" id="attach">${R.icon('clip')}${T('Attach a file')}</button>
              <span class="spacer"></span>
              <label class="row" style="margin:0;font-weight:500;font-size:13px">${T('After sending, stage:')}<select id="c-stage" style="width:auto;margin:0;min-height:32px;padding:4px 8px">
                <option value="">${T('no change')}</option>${R.STAGES.map(s => `<option value="${s}">${T('stage.' + s)}</option>`).join('')}</select></label></div>
          </div>` : ''}`;
        $$('[data-fold]', el).forEach(h => h.onclick = () => h.parentElement.classList.toggle('folded'));
        $('#open-lead', el).onclick = () => R.openLead(l.id, () => R.quiet(loadThread()));
        $('#done', el).onclick = async e => { await R.run(e.currentTarget, () => R.post(`/api/inbox/${l.id}/done`), t('Marked as done')); R.quiet(loadList()); R.refreshBadges(); };
        $('#stage', el).onchange = async e => { await R.run(null, () => R.patch(`/api/leads/${l.id}/deal`, { stage: e.target.value }), t('Stage saved')); R.quiet(loadList()); };
        $('#fwd', el).onclick = () => forward(th);
        if (!answerable || lastBounce) return;
        const body = $('#c-body', el);
        const grow = () => { body.style.height = 'auto'; body.style.height = Math.max(200, body.scrollHeight + 4) + 'px'; };
        body.addEventListener('input', grow); grow();
        paintFiles();
        $('#ai', el).onclick = async e => {
          const note = await R.ask(t('Write the answer with AI'), { text: t('The AI reads the whole conversation and uses only the facts in Settings. Anything else to say?'),
            chips: [t('send the catalogue'), t('ask for quantities and sizes'), t('offer samples'), t('suggest a call')], placeholder: t('optional'), ok: t('Write') });
          if (note === null) return;
          const r = await R.run(e.currentTarget, () => R.post(`/api/inbox/${l.id}/draft`, { reply_id: th.answer_to, note }));
          body.value = r.body; grow();
          $('#c-lint', el).innerHTML = R.lintList(r.lint);
          if (r.by === 'template') R.toast(t('No AI key: a simple template was used.'));
        };
        $('#attach', el).onclick = () => pickFiles();
        $('#send', el).onclick = async e => {
          const payload = { subject: $('#c-subj', el).value, body: body.value, reply_id: th.answer_to, file_ids: attach.map(a => a.id), stage: $('#c-stage', el).value };
          if (!payload.body.trim()) return R.toast(t('Write the answer first.'), 'err');
          try {
            await R.run(e.currentTarget, () => R.post(`/api/inbox/${l.id}/send`, payload), t('Answer sent'));
          } catch (err) { if (err.code === 'blocked') $('#c-lint', el).innerHTML = R.lintList(err.data); return; }
          R.refreshBadges(); R.quiet(loadList()); R.quiet(loadThread());
        };
      };
      const paintFiles = () => {
        const box = $('#c-files', el); if (!box) return;
        box.innerHTML = attach.map(a => `<span class="chip">${R.icon('clip', 'ic--sm')}${esc(a.name)} <button class="linkbtn" data-rm="${a.id}" aria-label="${T('Remove')}">${R.icon('x', 'ic--sm')}</button></span>`).join('');
        $$('[data-rm]', box).forEach(b => b.onclick = () => { attach = attach.filter(a => a.id !== +b.dataset.rm); paintFiles(); });
      };
      const pickFiles = async () => {
        const files = await R.get('/api/files');
        const o = R.modal(`<h2>${T('Attach a file')}</h2><p class="muted">${T('Files you upload here stay in your library for next time (catalogue, price list, certificates).')}</p>
          <div id="flist">${files.length ? files.map(fl => `<label class="check" style="margin-bottom:8px"><input type="checkbox" value="${fl.id}" data-name="${esc(fl.name)}" ${attach.some(a => a.id === fl.id) ? 'checked' : ''}><span>${esc(fl.name)} <small class="muted">${R.size(fl.size)}</small></span></label>`).join('') : `<p class="muted">${T('No files yet.')}</p>`}</div>
          <div class="row" style="margin-top:12px"><button class="btn btn--primary" id="f-ok">${T('Attach')}</button>
          <label class="btn" style="margin:0">${R.icon('upload')}${T('Upload a new file')}<input type="file" id="f-up" hidden></label><button class="btn" data-close>${T('Cancel')}</button></div>`);
        $('#f-up', o).onchange = async e => {
          const file = e.target.files[0]; if (!file) return;
          if (file.size > 15e6) return R.toast(t('err.too_large'), 'err');
          const r = await R.run(null, () => R.api('POST', '/api/files', file, { type: file.type || 'application/octet-stream', name: file.name }), t('Uploaded'));
          attach.push({ id: r.id, name: file.name }); paintFiles(); o._close();
        };
        $('#f-ok', o).onclick = () => { attach = $$('#flist input:checked', o).map(i => ({ id: +i.value, name: i.dataset.name })); paintFiles(); o._close(); };
      };
      const forward = th => {
        const last = [...th.items].reverse().find(i => i.who === 'them');
        if (!last) return R.toast(t('There is no reply to forward.'), 'err');
        const o = R.modal(`<h2>${T('Forward this reply')}</h2><p class="muted">${T('Sends their email, with the company and a short summary, to another address.')}</p>
          <label>${T('To')}<input id="fw-to" type="email" placeholder="name@company.com"></label>
          <label>${T('A note (optional)')}<input id="fw-note"></label>
          <div class="row"><button class="btn btn--primary" id="fw-go">${T('Forward')}</button><button class="btn" data-close>${T('Cancel')}</button></div>`);
        R.quiet(R.get('/api/settings').then(s => { if (s.forward_to && !$('#fw-to', o).value) $('#fw-to', o).value = s.forward_to; }));
        $('#fw-go', o).onclick = async e => {
          await R.run(e.currentTarget, () => R.post(`/api/replies/${last.id}/forward`, { to: $('#fw-to', o).value, note: $('#fw-note', o).value }), r => t('Forwarded to {to}', { to: r.to }));
          o._close(); R.quiet(loadThread());
        };
      };

      await loadList(true);
      if (leadId) await loadThread();
      R.every(() => R.quiet(loadList()), 30000);
    },
  };
})();
