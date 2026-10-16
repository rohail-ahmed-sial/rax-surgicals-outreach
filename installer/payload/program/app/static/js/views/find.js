'use strict';
/* Find leads: Google Maps search (several places at once, with search ideas in the local language), a pasted list of
   websites or emails, a CSV or Excel file with a column preview, or one company by hand. */
(function () {
  const R = window.R, { $, $$, esc, t, T } = R;
  const FIELDS = ['company', 'website', 'email', 'country', 'city', 'phone', 'contact_name', 'notes'];

  R.jobsHtml = jobs => jobs.length ? jobs.slice(0, 6).map(j => `<div class="taskrow"><span style="min-width:150px;font-weight:600;font-size:13px">${T('job.' + j.kind)}</span>
      ${j.status === 'running' ? `<span class="prog"><i style="width:${j.total ? Math.max(4, Math.round(100 * j.done / j.total)) : 8}%"></i></span>` : R.pill(t('jobstatus.' + j.status), j.status === 'failed' ? 'bad' : 'good')}
      <small class="muted ell" style="flex:2">${esc(j.message || '')}</small></div>`).join('') : `<p class="muted" style="margin:0">${T('Nothing running.')}</p>`;

  R.views.find = {
    async render(el, { params }) {
      let tab = params.get('tab') || 'maps';
      const s = await R.get('/api/settings');
      el.innerHTML = `<div class="head"><div><h1>${T('nav.find')}</h1><p>${T('find.lead')}</p></div></div>
        <div class="tabs" id="tabs">${['maps', 'paste', 'file', 'one'].map(k => `<button data-tab="${k}" class="${k === tab ? 'on' : ''}">${R.icon({ maps: 'pin', paste: 'clipboard', file: 'sheet', one: 'plus' }[k])}${T('find.tab.' + k)}</button>`).join('')}</div>
        <div class="grid g84"><div id="tabbody"></div>
          <div><div class="panel"><div class="panel__head"><h2>${T('Working in the background')}</h2></div><div id="jobs"></div></div>
            <div class="panel"><h2 style="margin-bottom:8px">${T('Tips')}</h2><ul class="guide" style="margin:0">${['tip.1', 'tip.2', 'tip.3', 'tip.4'].map(k => `<li>${T(k)}</li>`).join('')}</ul></div></div></div>`;
      $$('#tabs button', el).forEach(b => b.onclick = () => { tab = b.dataset.tab; $$('#tabs button', el).forEach(x => x.classList.toggle('on', x === b)); history.replaceState(null, '', '#/find?tab=' + tab); paint(); });
      const body = $('#tabbody', el);

      const paint = () => ({ maps, paste, file, one }[tab] || maps)();

      function maps() {
        body.innerHTML = `<form class="panel" id="f-maps">
            ${s.google_places_api_key ? '' : R.note(`${T('Add a Google Maps key in Settings to search, or use a list or file instead.')} <a href="#/settings/google">${T('Add the key')}</a>`, 'info')}
            <label>${T('What kind of business')}<input name="query" required placeholder="surgical instruments distributor" autocomplete="off"></label>
            <div class="row" style="margin:-6px 0 14px"><div class="chips" id="ideas"></div></div>
            <label>${T('Where')}<span class="hint">${T('One place per line. In big countries, search city by city: you find more companies.')}</span>
              <textarea name="locations" rows="3" style="min-height:84px" placeholder="Germany&#10;Munich, Germany&#10;Hamburg, Germany"></textarea></label>
            <div class="row" style="margin:-6px 0 14px"><button type="button" class="linkbtn" id="more-ideas">${R.icon('spark', 'ic--sm')} ${T('Search ideas in the local language')}</button></div>
            <div class="inline"><label class="w-s" style="flex-basis:190px">${T('Results per place')}<select name="max"><option>20</option><option>40</option><option selected>60</option></select></label>
              <label class="check" style="flex:2 1 220px;align-self:center"><input type="checkbox" name="auto" checked><span>${T('Read their websites and check the fit right away')}</span></label></div>
            <button class="btn btn--primary">${R.icon('find')}${T('Search')}</button>
          </form>
          <div class="panel panel--flush"><div class="panel__head"><h2>${T('Searches')}</h2></div><div class="tablewrap" id="hist"></div></div>`;
        const f = $('#f-maps', body);
        const setIdeas = qs => { $('#ideas', body).innerHTML = qs.map(q => `<button type="button" class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join(''); $$('#ideas .chip', body).forEach(c => c.onclick = () => { f.query.value = c.dataset.q; }); };
        setIdeas(['surgical instruments distributor', 'medical supplies wholesaler', 'dental supply company', 'beauty supply wholesaler', 'veterinary supplies distributor']);
        $('#more-ideas', body).onclick = async e => {
          const loc = (f.locations.value.split('\n').find(x => x.trim()) || '').trim();
          if (!loc) { R.toast(t('Type a country or city first.'), 'err'); f.locations.focus(); return; }
          const r = await R.run(e.currentTarget, () => R.post('/api/search/suggest', { location: loc }));
          setIdeas(r.queries);
        };
        f.onsubmit = async e => {
          e.preventDefault();
          const locations = f.locations.value.split('\n').map(x => x.trim()).filter(Boolean);
          await R.run(e.submitter, () => R.post('/api/search', { query: f.query.value, locations, max: +f.max.value, auto_check: f.auto.checked }),
            r => R.tn(r.queued, '1 search started', '{n} searches started, one after another'));
          hist(); jobs();
        };
        hist();
      }
      async function hist() {
        const box = $('#hist', body); if (!box) return;
        const rows = await R.get('/api/searches');
        box.innerHTML = rows.length ? `<table><thead><tr><th>${T('Search')}</th><th>${T('Status')}</th><th class="r">${T('Found')}</th><th class="r">${T('New')}</th><th>${T('When')}</th><th></th></tr></thead><tbody>
          ${rows.map(r => `<tr><td><b>${esc(r.query)}</b>${r.location ? `<small class="muted" style="display:block">${esc(r.location)}</small>` : ''}</td>
            <td>${R.pill(t('search.' + r.status), r.status === 'done' ? 'good' : r.status === 'failed' ? 'bad' : r.status === 'running' ? 'blue' : '')}${r.error ? `<small class="muted" style="display:block;max-width:260px">${esc(R.has('err.' + r.error) ? t('err.' + r.error) : r.error)}</small>` : ''}</td>
            <td class="r num">${R.num(r.found)}</td><td class="r num">${R.num(r.added)}</td><td class="muted nowrap">${esc(R.ago(r.created_at))}</td>
            <td>${r.status === 'queued' ? `<button class="linkbtn" data-cancel="${r.id}">${T('Cancel')}</button>` : r.status === 'done' && r.added ? `<a href="#/leads?sort=new">${T('See leads')}</a>` : ''}</td></tr>`).join('')}</tbody></table>`
          : `<p class="muted" style="padding:14px 18px;margin:0">${T('No searches yet.')}</p>`;
        $$('[data-cancel]', box).forEach(b => b.onclick = async () => { await R.post(`/api/searches/${b.dataset.cancel}/cancel`); hist(); });
      }

      function paste() {
        body.innerHTML = `<form class="panel" id="f-paste">
          <p class="muted">${T('paste.lead')}</p>
          <label>${T('Websites or email addresses')}<textarea name="text" rows="8" style="min-height:180px" placeholder="medsupply.de&#10;www.dentalhaus.at&#10;orders@clinicline.ie"></textarea></label>
          <div class="inline"><label>${T('Country')}<span class="hint">${T('Used for office hours and the AI. Leave empty if mixed.')}</span><input name="country" placeholder="Germany"></label>
            <label class="check" style="align-self:center"><input type="checkbox" name="auto" checked><span>${T('Check them right away')}</span></label></div>
          <button class="btn btn--primary">${R.icon('plus')}${T('Add to leads')}</button></form>`;
        $('#f-paste', body).onsubmit = async e => {
          e.preventDefault(); const f = e.target;
          const r = await R.run(e.submitter, () => R.post('/api/leads/paste', { text: f.text.value, country: f.country.value, auto_check: f.auto.checked }),
            r => t('{a} added, {b} skipped (already there or not readable)', { a: r.added, b: r.skipped }));
          if (r.added) f.text.value = '';
          jobs();
        };
      }

      function file() {
        let picked = null, pv = null;
        body.innerHTML = `<div class="panel"><p class="muted">${T('file.lead')}</p>
            <div class="drop-zone" id="dz" tabindex="0" role="button">${R.icon('upload', 'ic--lg')}<p style="margin:8px 0 0"><b>${T('Drop a CSV or Excel file here')}</b><br>${T('or click to choose')}</p></div>
            <input type="file" id="fi" accept=".csv,.txt,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden></div>
          <div id="mapbox"></div>`;
        const dz = $('#dz', body), fi = $('#fi', body);
        dz.onclick = () => fi.click();
        dz.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fi.click(); } };
        dz.ondragover = e => { e.preventDefault(); dz.classList.add('over'); };
        dz.ondragleave = () => dz.classList.remove('over');
        dz.ondrop = e => { e.preventDefault(); dz.classList.remove('over'); if (e.dataTransfer.files[0]) take(e.dataTransfer.files[0]); };
        fi.onchange = () => fi.files[0] && take(fi.files[0]);
        async function take(f) {
          if (f.size > 25e6) return R.toast(t('err.too_large'), 'err');
          picked = { name: f.name, data: await R.fileToB64(f) };
          try { pv = await R.post('/api/import/preview', picked); } catch (e) { return R.fail(e); }
          const opts = sel => `<option value="-1">${T('not used')}</option>` + pv.headers.map((h, i) => `<option value="${i}" ${sel === i ? 'selected' : ''}>${esc(h || t('column {n}', { n: i + 1 }))}</option>`).join('');
          $('#mapbox', body).innerHTML = `<div class="panel"><div class="panel__head"><h2>${esc(picked.name)}</h2><span class="muted">${R.TN(pv.rows, '1 row', '{n} rows')}</span></div>
            <p class="muted">${T('Check which column holds what. Columns with known names are matched already.')}</p>
            <div class="mapgrid">${FIELDS.map(fl => `<label>${T('field.' + fl)}<select data-field="${fl}">${opts(pv.mapping[fl] ?? -1)}</select></label>`).join('')}</div>
            <div class="tablewrap" style="margin:6px 0 16px;border:1px solid var(--line);border-radius:var(--r)"><table><thead><tr>${pv.headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
              <tbody>${pv.sample.map(r => `<tr>${r.map(c => `<td class="ell" style="max-width:200px">${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
            <div class="inline"><label>${T('Country for rows without one')}<input id="imp-country" placeholder="Germany"></label>
              <label class="check" style="align-self:center"><input type="checkbox" id="imp-auto" checked><span>${T('Check them right away')}</span></label></div>
            <button class="btn btn--primary" id="imp-go">${R.icon('download')}${T('Import')}</button></div>`;
          $('#imp-go', body).onclick = async e => {
            const mapping = {}; $$('[data-field]', body).forEach(s_ => { if (+s_.value >= 0) mapping[s_.dataset.field] = +s_.value; });
            const r = await R.run(e.currentTarget, () => R.post('/api/import/commit', Object.assign({}, picked, { mapping, country: $('#imp-country', body).value, auto_check: $('#imp-auto', body).checked })),
              r => t('{a} added, {b} skipped (already there or empty)', { a: r.added, b: r.skipped }));
            $('#mapbox', body).innerHTML = R.note(T('{a} added, {b} skipped (already there or empty)', { a: r.added, b: r.skipped }) + ` <a href="#/leads">${T('See leads')}</a>`, 'good');
            jobs();
          };
        }
      }

      function one() {
        body.innerHTML = `<form class="panel" id="f-one">
          <div class="inline"><label>${T('Company')}<input name="company"></label><label>${T('Website')}<input name="website" placeholder="example.com"></label></div>
          <div class="inline"><label>${T('Email')}<input name="email" type="email"></label><label>${T('Contact person')}<input name="contact_name"></label></div>
          <div class="inline"><label>${T('Country')}<input name="country"></label><label>${T('City')}<input name="city"></label></div>
          <button class="btn btn--primary">${R.icon('plus')}${T('Add and check')}</button></form>`;
        $('#f-one', body).onsubmit = async e => {
          e.preventDefault();
          const r = await R.run(e.submitter, () => R.post('/api/leads', Object.fromEntries(new FormData(e.target))), t('Added. Checking the website now.'));
          e.target.reset(); jobs();
          return r;
        };
      }

      const jobs = async () => { const box = $('#jobs', el); if (box) box.innerHTML = R.jobsHtml(await R.get('/api/jobs')); };
      paint(); jobs();
      R.every(() => { R.quiet(jobs()); if (tab === 'maps') R.quiet(hist()); }, 2500);
    },
  };
})();
