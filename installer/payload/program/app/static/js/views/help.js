'use strict';
/* Help: the daily routine, what happens by itself, keys, and common questions. */
(function () {
  const R = window.R, { esc, t, T } = R;
  const FAQ = ['spam', 'limit', 'gmail', 'legal', 'cost', 'pc_off', 'data', 'ai_wrong', 'more_leads'];

  R.views.help = {
    render(el) {
      el.innerHTML = `<div class="head"><div><h1>${T('nav.help')}</h1><p>${T('help.lead')}</p></div>
        <div class="head__actions"><button class="btn" id="wiz">${R.icon('settings')}${T('Open setup guide')}</button></div></div>
        <div class="grid g2 help">
          <div class="panel"><h2 class="h-ic">${R.icon('calendar')}${T('Your daily routine')}</h2>${R.steps('help.routine')}</div>
          <div class="panel"><h2 class="h-ic">${R.icon('refresh')}${T('What happens by itself')}</h2><ul>${t('help.auto').split('\n').filter(Boolean).map(l => `<li>${esc(l)}</li>`).join('')}</ul></div>
        </div>
        <div class="grid g2 help">
          <div class="panel faq"><h2 class="h-ic">${R.icon('help')}${T('Questions')}</h2>${FAQ.map(k => `<details><summary>${T('faq.' + k + '.q')}</summary><p>${R.linkify(esc(t('faq.' + k + '.a')))}</p></details>`).join('')}</div>
          <div class="panel"><h2 class="h-ic">${R.icon('keyboard')}${T('Keyboard')}</h2><div class="keys">
            <kbd>Ctrl K</kbd><span>${T('search companies')}</span>
            <kbd>J / K</kbd><span>${T('next or previous email (Approve)')}</span>
            <kbd>A</kbd><span>${T('approve (Approve)')}</span>
            <kbd>S</kbd><span>${T('skip this company (Approve)')}</span>
            <kbd>R</kbd><span>${T('rewrite with AI (Approve)')}</span>
            <kbd>Esc</kbd><span>${T('close a window')}</span></div>
            <hr class="sep"><div class="about">${R.logo()}<div><b>RAX Surgicals Outreach ${esc(R.version || '')}</b><span class="muted">${T('Find buyers. Email them. Turn replies into orders.')}</span></div></div></div>
        </div>`;
      el.querySelector('#wiz').onclick = () => R.openWizard();
    },
  };
})();
