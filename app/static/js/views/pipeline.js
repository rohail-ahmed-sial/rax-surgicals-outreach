'use strict';
/* Pipeline: deals from first interest to a won (or lost) order. Drag a card to another column, or change the stage
   in the company's details. Interested replies arrive here by themselves. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  const STAGE_ICONS = { interested: 'star', quote: 'receipt', sample: 'box', negotiation: 'chat', won: 'trophy', lost: 'xcircle' };

  R.views.pipeline = {
    async render(el) {
      const draw = async () => {
        const d = await R.get('/api/pipeline');
        const open = d.stages.slice(0, 4).reduce((a, c) => a + c.value, 0);
        const won = d.stages.find(c => c.stage === 'won');
        const any = d.stages.some(c => c.leads.length);
        el.innerHTML = `<div class="head"><div><h1>${T('nav.pipeline')}</h1><p>${T('pipeline.lead')}</p></div>
          <div class="head__actions"><span class="muted">${T('Open: {v}', { v: R.money(open) })}</span><span class="pill pill--good">${T('Won: {v}', { v: R.money(won.value) })}</span></div></div>
          ${any ? '' : `<div class="panel">${R.empty({ icon: 'pipeline', title: t('No deals yet'), text: t('When a lead replies with interest it appears here. You can also add any lead from its details.'), action: { label: t('Open inbox'), href: '#/inbox' } })}</div>`}
          <div class="board" ${any ? '' : 'hidden'}>${d.stages.map(c => `<section class="col" data-stage="${c.stage}" aria-label="${T('stage.' + c.stage)}">
            <div class="col__head">${R.icon(STAGE_ICONS[c.stage])}<b>${T('stage.' + c.stage)}</b> ${R.pill(c.leads.length)}</div><div class="col__val">${c.value ? esc(R.money(c.value)) : ''}</div>
            ${c.leads.map(l => {
              const over = l.next_action_date && l.next_action_date < d.today, today = l.next_action_date === d.today;
              return `<article class="card" draggable="true" data-id="${l.id}" tabindex="0">
                <b>${esc(l.company)}</b><small class="muted">${esc([l.contact_name, l.country].filter(Boolean).join(', '))}</small>
                ${l.deal_value ? `<div class="card__val">${esc(R.money(l.deal_value, l.deal_currency))}</div>` : ''}
                ${l.next_action || l.next_action_date ? `<div class="card__next">${l.next_action_date ? `<span class="due ${over ? 'due--over' : today ? 'due--today' : ''}">${over ? T('overdue') : today ? T('today') : esc(R.fmtDay(l.next_action_date))}</span>` : ''}<span class="ell">${esc(l.next_action || '')}</span></div>` : ''}
                ${l.last_contact_at ? `<small class="faint" style="margin-top:4px">${T('last contact {when}', { when: R.ago(l.last_contact_at) })}</small>` : ''}
              </article>`; }).join('')}
          </section>`).join('')}</div>`;
        let dragId = null;
        $$('.card', el).forEach(c => {
          c.onclick = () => R.openLead(+c.dataset.id, draw, 'deal');
          c.onkeydown = e => { if (e.key === 'Enter') R.openLead(+c.dataset.id, draw, 'deal'); };
          c.ondragstart = e => { dragId = +c.dataset.id; c.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', String(dragId)); } catch (_) {} };
          c.ondragend = () => c.classList.remove('dragging');
        });
        $$('.col', el).forEach(col => {
          col.ondragover = e => { e.preventDefault(); col.classList.add('drop'); };
          col.ondragleave = () => col.classList.remove('drop');
          col.ondrop = async e => {
            e.preventDefault(); col.classList.remove('drop');
            const id = dragId || +e.dataTransfer.getData('text/plain'); if (!id) return;
            await R.run(null, () => R.patch(`/api/leads/${id}/deal`, { stage: col.dataset.stage }), t('Moved to {stage}', { stage: t('stage.' + col.dataset.stage) }));
            R.refreshBadges(); draw();
          };
        });
      };
      await draw();
      R.every(() => R.quiet(draw()), 60000);
    },
  };
})();
