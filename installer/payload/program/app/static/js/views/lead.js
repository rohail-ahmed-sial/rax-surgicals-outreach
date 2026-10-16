'use strict';
/* The lead drawer: everything about one company. Opened from Leads, Inbox, Pipeline, Today and the search box. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  R.STAGES = ['interested', 'quote', 'sample', 'negotiation', 'won', 'lost'];
  const STATUSES = ['new', 'ready', 'in_campaign', 'replied', 'no_reply', 'not_interested', 'unsubscribed', 'bounced', 'rejected'];
  const CURRENCIES = ['USD', 'EUR', 'GBP', 'AED', 'SAR', 'PKR', 'AUD', 'CAD'];

  R.openLead = async (id, onChange, tab = 'details') => {
    let l;
    try { l = await R.get('/api/leads/' + id); } catch (e) { return R.fail(e); }
    const changed = () => { onChange && onChange(); };
    const hasConvo = l.replies.some(r => r.kind !== 'bounce');
    const o = R.drawer(`<div class="drawer__head">
        <div class="drawer__title">${R.avatar(l.company, 'avatar--lg')}<h2>${esc(l.company)}</h2></div>
        <div class="row" style="margin-top:8px">${R.fitPill(l.fit, l.score)} ${R.statusPill(l.status)} ${R.stagePill(l.stage)} ${l.category ? R.pill(t('cat.' + l.category)) : ''}</div>
        ${l.ai_reason ? `<p class="muted" style="margin:10px 0 0">${esc(l.ai_reason)}</p>` : ''}
        <div class="row" style="margin-top:12px">
          ${l.website ? `<a class="btn btn--sm" href="${esc(l.website)}" target="_blank" rel="noopener">${R.icon('external')}${T('Website')}</a>` : ''}
          ${hasConvo ? `<a class="btn btn--sm" href="#/inbox/${l.id}">${R.icon('inbox')}${T('Conversation')}</a>` : ''}
          <button class="btn btn--sm" data-act="campaign">${R.icon('campaigns')}${T('Add to campaign')}</button>
          ${!l.stage ? `<button class="btn btn--sm" data-act="pipeline">${R.icon('pipeline')}${T('Add to pipeline')}</button>` : ''}
        </div>
        <div class="tabs" style="margin:14px 0 -15px">
          ${['details', 'deal', 'timeline', 'site'].map(k => `<button data-tab="${k}" class="${k === tab ? 'on' : ''}">${T('tab.' + k)}</button>`).join('')}
        </div>
      </div><div class="drawer__body" id="lead-body"></div>`);
    const body = $('#lead-body', o);
    const show = k => { tab = k; $$('[data-tab]', o).forEach(b => b.classList.toggle('on', b.dataset.tab === k)); paint[k](); };
    $$('[data-tab]', o).forEach(b => b.onclick = () => show(b.dataset.tab));

    const paint = {
      details() {
        body.innerHTML = `<form id="lf">
          <label>${T('Email to use')}${l.email_status ? ' ' + R.emailMark(l.email_status) : ''}
            ${l.emails.length > 1 ? `<span class="hint">${T('Found on their website:')} ${l.emails.map(e => `<button type="button" class="linkbtn" data-e="${esc(e)}">${esc(e)}</button>`).join(', ')}</span>` : ''}
            <input name="email" type="email" value="${esc(l.email || '')}" autocomplete="off">
            ${l.email_status && l.email_status !== 'valid' ? `<span class="hint">${T('email.' + l.email_status)}</span>` : ''}
            ${l.suppressed ? `<span class="field-err">${T('This address is on the do-not-email list.')}</span>` : ''}</label>
          <div class="inline"><label>${T('Contact person')}<input name="contact_name" value="${esc(l.contact_name || '')}"></label>
            <label>${T('Phone')}<input name="phone" value="${esc(l.phone || '')}"></label></div>
          <div class="inline"><label>${T('Country')}<input name="country" value="${esc(l.country || '')}"></label>
            <label>${T('City')}<input name="city" value="${esc(l.city || '')}"></label></div>
          <label>${T('Website')}<input name="website" value="${esc(l.website || '')}"></label>
          <div class="inline"><label>${T('Status')}<select name="status">${STATUSES.map(s => `<option value="${s}" ${s === l.status ? 'selected' : ''}>${T('status.' + s)}</option>`).join('')}</select></label>
            <label>${T('Fit')}<select name="fit"><option value="">${T('not checked')}</option>${['good', 'maybe', 'no'].map(k => `<option value="${k}" ${k === l.fit ? 'selected' : ''}>${T('fit.' + k)}</option>`).join('')}</select></label></div>
          <div class="row"><button class="btn btn--primary">${T('Save')}</button>
            <button type="button" class="btn" data-act="recheck">${R.icon('refresh')}${T('Read website again')}</button>
            <span class="spacer"></span><button type="button" class="btn btn--ghost btn--danger" data-act="delete">${R.icon('trash')}${T('Delete')}</button></div>
        </form>
        <dl class="kv" style="margin-top:22px">
          <dt>${T('Found through')}</dt><dd>${T('source.' + (l.source || 'manual'))}${l.search_query ? ': ' + esc(l.search_query) : ''}</dd>
          <dt>${T('Address')}</dt><dd>${esc(l.address || '—')}</dd>
          ${l.notes ? `<dt>${T('From your list')}</dt><dd style="white-space:pre-wrap">${esc(l.notes)}</dd>` : ''}
          <dt>${T('Website read')}</dt><dd>${esc(l.crawl_note || t('crawl.' + (l.crawl_status || 'pending')))}</dd>
          <dt>${T('Added')}</dt><dd>${esc(R.fmtDate(l.created_at))}</dd>
          ${l.campaigns.length ? `<dt>${T('Campaigns')}</dt><dd>${l.campaigns.map(c => `${esc(c.name)} ${R.pill(t('enr.' + c.status))}${c.status === 'active' && c.next_due ? ' <small class="muted">' + T('next email {when}', { when: R.ago(c.next_due) }) + '</small>' : ''}`).join('<br>')}</dd>` : ''}
        </dl>`;
        $$('[data-e]', body).forEach(b => b.onclick = () => { $('#lf').email.value = b.dataset.e; });
        $('#lf', body).onsubmit = async e => {
          e.preventDefault();
          const fd = Object.fromEntries(new FormData(e.target));
          await R.run(e.submitter, () => R.patch('/api/leads/' + id, fd), t('Saved'));
          changed(); o._close(); R.openLead(id, onChange, 'details');
        };
        $('[data-act=recheck]', body).onclick = ev => R.run(ev.currentTarget, () => R.post('/api/leads/check', { ids: [id] }), t('Checking the website in the background'));
        $('[data-act=delete]', body).onclick = async () => {
          if (!await R.confirm(t('Delete {name}?', { name: l.company }), t('delete.lead.text'), { ok: t('Delete'), danger: true })) return;
          await R.run(null, () => R.post('/api/leads/delete', { ids: [id] }), t('Deleted'));
          o._close(); changed();
        };
      },
      deal() {
        body.innerHTML = `<form id="df">
          <div class="inline"><label>${T('Stage')}<select name="stage"><option value="">${T('Not in the pipeline')}</option>${R.STAGES.map(s => `<option value="${s}" ${s === l.stage ? 'selected' : ''}>${T('stage.' + s)}</option>`).join('')}</select></label>
            <label>${T('Order value')}<input name="deal_value" inputmode="decimal" value="${l.deal_value ?? ''}" placeholder="2500"></label>
            <label class="w-s">${T('Currency')}<select name="deal_currency">${CURRENCIES.map(c => `<option ${c === (l.deal_currency || 'USD') ? 'selected' : ''}>${c}</option>`).join('')}</select></label></div>
          <div class="inline"><label>${T('Next step')}<input name="next_action" value="${esc(l.next_action || '')}" placeholder="${T('e.g. send samples')}"></label>
            <label class="w-s" style="flex-basis:170px">${T('By date')}<input name="next_action_date" type="date" value="${esc(l.next_action_date || '')}"></label></div>
          <button class="btn btn--primary">${T('Save')}</button>
        </form>
        <hr class="sep"><h3>${T('Notes')}</h3>
        <form id="nf" class="row" style="margin:8px 0 12px"><input name="text" placeholder="${T('e.g. called, wants 200 needle holders')}" style="flex:1;margin:0"><button class="btn">${T('Add note')}</button></form>
        <div>${noteRows()}</div>`;
        $('#df', body).onsubmit = async e => {
          e.preventDefault();
          await R.run(e.submitter, () => R.patch(`/api/leads/${id}/deal`, Object.fromEntries(new FormData(e.target))), t('Saved'));
          changed(); o._close(); R.openLead(id, onChange, 'deal');
        };
        $('#nf', body).onsubmit = async e => {
          e.preventDefault();
          const text = e.target.text.value.trim(); if (!text) return;
          await R.run(e.submitter, () => R.post(`/api/leads/${id}/notes`, { text }));
          o._close(); R.openLead(id, onChange, 'deal');
        };
        $$('[data-delnote]', body).forEach(b => b.onclick = async () => { await R.del('/api/notes/' + b.dataset.delnote); o._close(); R.openLead(id, onChange, 'deal'); });
      },
      timeline() {
        body.innerHTML = l.timeline.length ? `<div class="log">${l.timeline.map(ev => `<div><time title="${esc(R.fmtDT(ev.at))}">${esc(R.fmtDay(ev.at))}</time><span>${eventText(ev)}</span></div>`).join('')}</div>` : `<p class="muted">${T('Nothing yet.')}</p>`;
      },
      site() {
        body.innerHTML = `${l.emails.length ? `<h3>${T('Emails found')}</h3><p>${l.emails.map(e => esc(e)).join('<br>')}</p>` : ''}
          ${l.site_text ? `<h3 style="margin-top:14px">${T('What their website says')}</h3><div class="quote" style="max-height:none">${R.siteText(l.site_text, 5000)}</div>` : `<p class="muted">${T('The website has not been read.')}</p>`}`;
      },
    };
    function noteRows() {
      const notes = l.note_list || [];
      return notes.length ? `<div class="log">${notes.slice().reverse().map(n => `<div><time>${esc(R.fmtDay(n.at))}</time><span>${esc(n.text)} <button class="linkbtn linkbtn--danger" data-delnote="${n.id}" style="font-size:12px;margin-left:6px">${T('remove')}</button></span></div>`).join('')}</div>` : `<p class="muted">${T('No notes yet.')}</p>`;
    }
    function eventText(ev) {
      const d = ev.data || {};
      switch (ev.type) {
        case 'found': return T('Found through {how}', { how: t('source.' + (d.source || 'manual')) }) + (d.query ? `: <span class="muted">${esc(d.query)}</span>` : '');
        case 'sent': return T('Email {n} sent', { n: (d.step || 0) + 1 }) + `: <span class="muted">${esc(d.subject || '')}</span>`;
        case 'answered': return T('You answered') + `: <span class="muted">${esc(d.subject || '')}</span>`;
        case 'forwarded': return T('Reply forwarded to {to}', { to: d.to || '' });
        case 'reply': return R.kindPill(d.kind) + ' ' + esc(d.summary || '');
        case 'stage': { const [a, b] = String(d.text || '').split('>'); return T('Stage changed') + ': ' + (a ? R.stagePill(a) : T('none')) + ' → ' + (b ? R.stagePill(b) : T('none')); }
        default: return R.icon('note', 'ic--sm') + ' ' + esc(d.text || '');
      }
    }
    o.addEventListener('click', async e => {
      const b = e.target.closest('[data-act]'); if (!b) return;
      if (b.dataset.act === 'campaign') R.pickCampaign([id], changed);
      if (b.dataset.act === 'pipeline') { await R.run(b, () => R.patch(`/api/leads/${id}/deal`, { stage: 'interested' }), t('Added to the pipeline')); changed(); o._close(); R.openLead(id, onChange, 'deal'); }
    });
    show(tab);
    return o;
  };

  /* choose a campaign for some leads, then add them */
  R.pickCampaign = async (ids, done) => {
    let camps;
    try { camps = (await R.get('/api/campaigns')).filter(c => c.active); } catch (e) { return R.fail(e); }
    if (!camps.length) {
      const o = R.modal(`<h2>${T('No campaign yet')}</h2><p class="muted">${T('Create a campaign first: what to pitch and how many follow-ups.')}</p>
        <a class="btn btn--primary" href="#/campaigns/new" data-close>${T('Create a campaign')}</a>`);
      return o;
    }
    const o = R.modal(`<h2>${T('Add to campaign')}</h2><p class="muted">${R.TN(ids.length, '1 lead selected', '{n} leads selected')}</p>
      <label>${T('Campaign')}<select id="pc">${camps.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label>
      <div class="row"><button class="btn btn--primary" id="pc-go">${T('Add')}</button><button class="btn" data-close>${T('Cancel')}</button></div>`);
    $('#pc-go', o).onclick = async e => {
      const r = await R.run(e.currentTarget, () => R.post(`/api/campaigns/${$('#pc', o).value}/enroll`, { ids }));
      o._close();
      R.showEnrollResult(r);
      done && done();
    };
  };
  R.showEnrollResult = r => {
    R.toast(R.tn(r.added, '1 lead added. Its first email will appear in Approve shortly.', '{n} leads added. Their first emails will appear in Approve shortly.'));
    if (r.skipped && r.skipped.length) {
      R.modal(`<h2>${R.TN(r.skipped.length, '1 lead was not added', '{n} leads were not added')}</h2>
        <div class="tablewrap" style="max-height:50vh"><table><tbody>${r.skipped.map(s => `<tr><td class="co">${esc(s.company)}</td><td class="muted">${T('skip.' + s.why)}</td></tr>`).join('')}</tbody></table></div>`);
    }
  };
})();
