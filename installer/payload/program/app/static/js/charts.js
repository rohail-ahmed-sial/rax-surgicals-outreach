'use strict';
/* Small hand-drawn SVG charts (no libraries):
   - R.columns: one series per chart (small multiples instead of two scales), hairline grid, 4px rounded tops,
     hover/focus tooltip on every column; the same numbers are always available as a table elsewhere.
   - R.windowBand: the office hours of each market drawn on the user's own 24-hour day, with a "now" line. */
(function () {
  const R = window.R;
  const NS = 'http://www.w3.org/2000/svg';
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function niceMax(v) {
    if (v <= 4) return 4;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }
  /* charts are drawn at their real pixel width; when the width changes they are drawn again */
  const ro = 'ResizeObserver' in window ? new ResizeObserver(es => es.forEach(e => {
    const h = e.target, w = Math.round(h.clientWidth);
    if (h._redraw && h._w && Math.abs(w - h._w) > 8) h._redraw();
  })) : null;
  const watch = (host, fn) => { host._redraw = fn; host._w = Math.round(host.clientWidth); if (ro && !host._watched) { ro.observe(host); host._watched = true; } };
  const compact = n => n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '') + 'K' : String(n);

  function columnPath(x, y, w, h, r) {
    if (h <= 0) return '';
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }

  /* data: [{label, value, title}] */
  R.columns = (host, data, { unit = '', height = 170 } = {}) => {
    const W = Math.max(280, Math.round(host.clientWidth || host.parentElement.clientWidth || 560)), H = height, padL = 34, padR = 8, padT = 16, padB = 26;
    const max = niceMax(Math.max(0, ...data.map(d => d.value)));
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const slot = plotW / Math.max(1, data.length);
    const bw = Math.min(24, Math.max(4, slot * 0.62));
    const y = v => padT + plotH - (v / max) * plotH;
    const ink2 = css('--ink-2'), grid = css('--grid'), series = css('--series-1'), ink = css('--ink');
    let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${R.esc(unit)}">`;
    for (const t of [0, max / 2, max]) {
      const yy = Math.round(y(t)) + .5;
      s += `<line x1="${padL}" x2="${W - padR}" y1="${yy}" y2="${yy}" stroke="${grid}" stroke-width="1"/>`;
      s += `<text x="${padL - 8}" y="${yy + 4}" text-anchor="end" font-size="11" fill="${ink2}">${compact(Math.round(t))}</text>`;
    }
    const every = Math.ceil(data.length / Math.max(3, Math.floor(plotW / 70)));
    const peak = data.reduce((m, d, i) => d.value > (data[m] || {}).value ? i : m, 0);
    data.forEach((d, i) => {
      const cx = padL + slot * i + slot / 2;
      const x = cx - bw / 2, top = y(d.value), h = padT + plotH - top;
      if (d.value > 0) s += `<path class="bar" data-i="${i}" d="${columnPath(x, top, bw, h, 4)}" fill="${series}"/>`;
      if ((data.length - 1 - i) % every === 0) s += `<text x="${cx}" y="${H - 8}" text-anchor="middle" font-size="11" fill="${ink2}">${R.esc(d.label)}</text>`;
      if (i === peak && d.value > 0) s += `<text x="${cx}" y="${top - 5}" text-anchor="middle" font-size="11" font-weight="700" fill="${ink}">${d.value}</text>`;
      s += `<rect class="hit" data-i="${i}" x="${padL + slot * i}" y="${padT}" width="${slot}" height="${plotH + 4}" tabindex="0" aria-label="${R.esc(d.title)}: ${d.value}"/>`;
    });
    s += '</svg>';
    host.innerHTML = s + '<div class="tip" hidden></div>';
    host.classList.add('chart');
    watch(host, () => R.columns(host, data, { unit, height }));
    const tip = host.querySelector('.tip'), svg = host.querySelector('svg');
    const show = (i, el) => {
      const d = data[i];
      host.querySelectorAll('.bar').forEach(b => b.classList.toggle('bar-on', +b.dataset.i === i));
      tip.innerHTML = `<b>${R.esc(R.num(d.value))}</b><i style="background:${series}"></i>${R.esc(d.title)}`;
      const box = svg.getBoundingClientRect(), hb = host.getBoundingClientRect(), r = el.getBoundingClientRect();
      tip.style.left = (r.left - hb.left + r.width / 2) + 'px';
      tip.style.top = (Math.min(r.top, box.top + (y(d.value) / H) * box.height) - hb.top) + 'px';
      tip.hidden = false;
    };
    const hide = () => { tip.hidden = true; host.querySelectorAll('.bar').forEach(b => b.classList.remove('bar-on')); };
    host.querySelectorAll('.hit').forEach(h => {
      h.addEventListener('pointerenter', () => show(+h.dataset.i, h));
      h.addEventListener('focus', () => show(+h.dataset.i, h));
      h.addEventListener('pointerleave', hide);
      h.addEventListener('blur', hide);
    });
  };

  /* markets: [{country, local_time:"HH:MM", local_day:"Mon", open_now, queued}] — hours: [start, end] in their local time */
  R.windowBand = (host, markets, { hours = [9, 17], weekdaysOnly = true } = {}) => {
    const now = new Date();
    const myMin = now.getHours() * 60 + now.getMinutes();
    const hostW = Math.round(host.clientWidth || 720), narrow = hostW < 600;     // phones: shorter labels, ticks every 6 hours
    const rowH = 34, padL = narrow ? 112 : 160, padR = narrow ? 10 : 16, padT = 24, W = Math.max(narrow ? 300 : 640, hostW);
    const SHORT = { 'United Arab Emirates': 'UAE', 'United States': 'USA', 'United Kingdom': 'UK', 'Saudi Arabia': 'Saudi Arabia', 'South Africa': 'S. Africa', 'New Zealand': 'N. Zealand' };
    const name = c => { c = c || '?'; if (!narrow) return c; c = SHORT[c] || c; return c.length > 14 ? c.slice(0, 13) + '…' : c; };
    const H = padT + rowH * markets.length + 22;
    const plotW = W - padL - padR;
    const x = m => padL + (m / 1440) * plotW;
    const grid = css('--grid'), ink2 = css('--ink-2'), ink = css('--ink'), sunk = css('--sunk'), em = css('--emerald'), blue = css('--series-1');
    let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${R.T('Office hours in your markets')}">`;
    for (let h = 0; h <= 24; h += narrow ? 6 : 3) {
      const xx = Math.round(x(h * 60)) + .5;
      s += `<line x1="${xx}" x2="${xx}" y1="${padT - 6}" y2="${H - 20}" stroke="${grid}" stroke-width="1"/>`;
      s += `<text x="${h === 24 ? W - 1 : xx}" y="${H - 6}" text-anchor="${h === 24 ? 'end' : 'middle'}" font-size="11" fill="${ink2}">${String(h % 24).padStart(2, '0')}:00</text>`;
    }
    markets.forEach((m, i) => {
      const top = padT + i * rowH;
      const [hh, mm] = (m.local_time || '00:00').split(':').map(Number);
      let diff = (hh * 60 + mm) - myMin;                     // their clock minus my clock, in minutes
      if (diff > 720) diff -= 1440; if (diff < -720) diff += 1440;
      const weekend = weekdaysOnly && /^(Sat|Sun)/.test(m.local_day || '');
      s += `<text x="0" y="${top + 13}" font-size="13" font-weight="600" fill="${ink}">${R.esc(name(m.country))}<title>${R.esc(m.country || '?')}</title></text>`;
      s += `<text x="0" y="${top + 28}" font-size="12" fill="${ink2}">${R.esc(R.t(weekend ? '{time} there, weekend' : '{time} there', { time: m.local_time }))}</text>`;
      s += `<rect x="${padL}" y="${top + 10}" width="${plotW}" height="10" rx="5" fill="${sunk}"/>`;
      if (!weekend) {
        let a = hours[0] * 60 - diff, b = hours[1] * 60 - diff;
        const segs = [];
        a = ((a % 1440) + 1440) % 1440; b = a + (hours[1] - hours[0]) * 60;
        if (b <= 1440) segs.push([a, b]); else { segs.push([a, 1440]); segs.push([0, b - 1440]); }
        segs.forEach(([p, q]) => s += `<rect x="${x(p)}" y="${top + 10}" width="${Math.max(2, x(q) - x(p))}" height="10" rx="5" fill="${m.open_now ? em : blue}" opacity="${m.open_now ? 1 : .45}"/>`);
      }
    });
    const nx = Math.round(x(myMin)) + .5, lx = Math.min(W - 34, Math.max(padL + 34, nx));
    s += `<line x1="${nx}" x2="${nx}" y1="${padT - 12}" y2="${H - 20}" stroke="${ink}" stroke-width="1.5"/>`;
    s += `<text x="${lx}" y="${padT - 14}" text-anchor="middle" font-size="11" font-weight="700" fill="${ink}">${R.esc(R.t('now'))} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}</text>`;
    s += '</svg>';
    host.innerHTML = s;
    watch(host, () => R.windowBand(host, markets, { hours, weekdaysOnly }));
  };

  /* horizontal bars as HTML rows: [{label, value, note, cls}] */
  R.barRows = (rows, { fmt = R.num } = {}) => {
    const max = Math.max(1, ...rows.map(r => r.value || 0));
    return `<ul class="stagebars">${rows.map(r => `<li class="${r.cls || ''}"><span>${R.esc(r.label)}</span><span class="track"><i style="width:${Math.round(100 * (r.value || 0) / max)}%"></i></span>
      <span class="num">${R.esc(fmt(r.value || 0))}${r.note ? ` <small class="muted">${R.esc(r.note)}</small>` : ''}</span></li>`).join('')}</ul>`;
  };
})();
