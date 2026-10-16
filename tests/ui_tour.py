"""Browser check of the dashboard: visits every page, the company drawer and the setup guide, saves screenshots,
and fails on script errors, failed requests, content wider than the screen, or text codes without an English entry.

    python tests/demo_server.py                        # demo data on http://127.0.0.1:8790
    python tests/ui_tour.py http://127.0.0.1:8790 1366 light
    python tests/ui_tour.py http://127.0.0.1:8790 390 dark   # phone width, dark mode
Needs: pip install playwright && playwright install chromium
"""
import os, sys, json
from playwright.sync_api import sync_playwright
B = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790'
W = int(sys.argv[2]) if len(sys.argv) > 2 else 1366
SCHEME = sys.argv[3] if len(sys.argv) > 3 else 'light'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots')
os.makedirs(OUT, exist_ok=True)
PAGES = ['today', 'approve', 'inbox', 'pipeline', 'find', 'find?tab=paste', 'find?tab=file', 'find?tab=one', 'leads', 'campaigns', 'campaigns/new',
         'outbox', 'outbox?t=sent', 'reports', 'activity', 'help'] + ['settings/' + s for s in ['company', 'mailbox', 'sending', 'ai', 'google', 'forwarding', 'files', 'donotemail', 'backup', 'access']]
ONLY = [x for x in os.environ.get('ONLY', '').split(',') if x]
if ONLY: PAGES = ONLY
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': W, 'height': 900}, color_scheme=SCHEME, is_mobile=W < 700, has_touch=W < 700)
    ctx.add_init_script('window.__i18nMiss = new Set();')
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append('js: ' + str(e)))
    pg.on('console', lambda m: errs.append('console: ' + m.text) if m.type == 'error' else None)
    pg.on('response', lambda r: errs.append(f'http {r.status} {r.url}') if r.status >= 400 else None)
    pg.goto(B + '/'); pg.wait_for_timeout(1200)
    for name in PAGES:
        pg.evaluate(f"location.hash = '#/{name}'"); pg.wait_for_timeout(1300)
        wide = pg.evaluate('''() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('body *')].filter(e => {
            const r = e.getBoundingClientRect(); if (!(r.width && r.right > W + 1)) return false;
            for (let q = e.parentElement; q; q = q.parentElement) { const o = getComputedStyle(q).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return false; }
            return true; }).map(e => e.tagName + '.' + e.className).slice(0, 4); }''')
        if wide: errs.append(f'too wide on {name}: {wide}')
        pg.screenshot(path=f"{OUT}/{name.replace('/', '_').replace('?', '_').replace('=', '_')}_{W}_{SCHEME}.png", full_page=True)
    if os.environ.get('NODIALOGS'):
        miss = pg.evaluate('[...window.__i18nMiss]')
        print('errors:', json.dumps(errs[:20], indent=1)); print('missing texts:', json.dumps(sorted(miss), ensure_ascii=False)); b.close()
        sys.exit(1 if errs or miss else 0)
    # dialogs: lead drawer (all tabs), campaign preview, setup guide
    pg.evaluate("location.hash = '#/leads'"); pg.wait_for_timeout(1200)
    pg.locator('tr.click').first.click(); pg.wait_for_timeout(800)
    for tab in ['details', 'deal', 'timeline', 'site']:
        pg.click(f'[data-tab={tab}]'); pg.wait_for_timeout(300)
        pg.screenshot(path=f'{OUT}/drawer_{tab}_{W}_{SCHEME}.png')
    pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    pg.evaluate("R.openWizard()"); pg.wait_for_timeout(800)
    for i in range(8):
        pg.screenshot(path=f'{OUT}/wizard_{i}_{W}_{SCHEME}.png', full_page=True)
        nxt = pg.locator('[data-go=next]')
        if nxt.count(): nxt.click(); pg.wait_for_timeout(700)
    miss = pg.evaluate('[...window.__i18nMiss]')
    print('errors:', json.dumps(errs[:20], indent=1))
    print('missing texts:', json.dumps(sorted(miss), indent=1, ensure_ascii=False))
    b.close()
    sys.exit(1 if errs or miss else 0)
