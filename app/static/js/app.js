'use strict';
/* Start-up: login, sidebar, badges, first-run setup guide. */
(function () {
  const R = window.R, { $, $$, t } = R;

  function stopped() {
    const sprite = document.querySelector('body > svg').outerHTML;       // keep the logo drawing
    document.body.innerHTML = `${sprite}<div class="wizard" style="grid-template-columns:1fr"><div class="wizard__main stopped">
      <div class="stopped__logo">${R.logo()}</div><h1>${R.T('RAX Surgicals Outreach is stopped')}</h1><p class="lead">${R.T('stopped.lead')}</p></div></div>`;
  }

  function start(me) {
    $('#login').hidden = true; $('#shell').hidden = false; $('#tabbar').hidden = false; $('#mobilebar').hidden = false;
    R.buildNav();
    R.initSearch();
    $('#theme-btn').onclick = () => R.setTheme(R.isDark() ? 'light' : 'dark');
    $('#menu-btn').onclick = R.openSide;
    const pw = $('#power-btn');
    pw.hidden = !!me.server_mode;
    pw.onclick = async () => {
      if (!await R.confirm(t('Stop RAX Surgicals Outreach?'), t('stop.text'), { ok: t('Stop'), danger: true })) return;
      try { await R.post('/api/shutdown'); } catch (e) {}
      stopped();
    };
    const lo = $('#logout-btn');
    lo.hidden = !me.auth_required;
    lo.onclick = async () => { await R.post('/api/logout'); location.reload(); };
    R.refreshBadges();
    setInterval(R.refreshBadges, 20000);
    R.route();
    if (!me.setup_done) R.openWizard();
  }

  async function boot() {
    R.applyTheme();
    let me;
    try { me = await (await fetch('/api/me', { cache: 'no-store' })).json(); }
    catch (e) {
      document.body.innerHTML = '<div style="padding:40px;font:16px system-ui">RAX Surgicals Outreach is not running. Start it again from the desktop icon.</div>';
      return;
    }
    R.version = me.version;
    if (!me.logged_in) {
      R.showLogin();
      $('#login-form').onsubmit = async e => {
        e.preventDefault();
        try {
          await R.post('/api/login', { password: e.target.password.value });
          const m2 = await (await fetch('/api/me', { cache: 'no-store' })).json();
          start(m2);
        } catch (err) { $('#login-err').textContent = R.errText(err); }
      };
      return;
    }
    start(me);
  }
  boot();
})();
