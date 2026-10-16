"""Web dashboard and JSON API, on Python's built-in web server (no extra packages).
Errors come back as {"error": "...", "code": "..."}: the dashboard shows the code in plain words."""
import json, os, re, secrets, hashlib, hmac, socket, time, threading, base64, sqlite3, urllib.parse, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import db, ai, finder, mailer, worker, dnscheck, quality, winstart

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
# fixed types: on some Windows computers the registry maps .js to text/plain, which browsers then refuse to run
MIME = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2',
        '.png': 'image/png', '.ico': 'image/x-icon', '.json': 'application/json', '.txt': 'text/plain', '.webmanifest': 'application/manifest+json'}
SESSIONS = {}
LOGIN_FAILS = {}
REQUIRE_LOGIN = False
HTTPD = None
STOP_TOKEN = secrets.token_hex(16)   # lets the installer stop this copy before it replaces files (kept in data/stop.token)
STAGES = ['interested', 'quote', 'sample', 'negotiation', 'won', 'lost']
OPEN_STAGES = STAGES[:4]


# ---------- password ----------
def hash_pw(pw):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()
    return f'pbkdf2${salt}${h}'


def check_pw(pw, stored):
    try:
        _, salt, h = stored.split('$')
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex(), h)


class API(Exception):
    def __init__(self, msg, http=400, code=None, data=None):
        super().__init__(msg)
        self.http, self.code, self.data = http, code, data


def ids_of(body):
    return [int(i) for i in (body.get('ids') or []) if str(i).isdigit()]


def local_date(iso):
    try:
        return dt.datetime.fromisoformat(iso).astimezone(worker.my_tz()).date()
    except (TypeError, ValueError):
        return None


def today_local():
    return worker.utcnow().astimezone(worker.my_tz()).date()


def masked_settings():
    s = db.all_settings()
    out = {}
    for k, v in s.items():
        if k in ('admin_password_hash', 'next_send_at') or k not in db.DEFAULTS and k not in ('db_version', 'last_inbox_check'):
            continue
        out[k] = ('•' * 8 + v[-4:]) if k in db.SECRET_KEYS and v else v
    out['password_set'] = bool(s.get('admin_password_hash'))
    out['ai_calls_today'] = ai.calls_today()
    return out


LEAD_COLS = ('id, company, website, domain, country, city, phone, email, email_status, contact_name, fit, score, category, status, source, '
             'crawl_status, crawl_note, ai_reason, language, stage, deal_value, deal_currency, next_action, next_action_date, '
             'last_contact_at, created_at, updated_at')


# ---------- small things for the sidebar (polled often) ----------
def badges(_q, _b):
    c = lambda sql, a=(): db.q(sql, a, one=True)['n']
    # desktop alerts only for replies worth reading now (not bounces, auto-replies, unsubscribes or a plain "no")
    last = db.q("SELECT id, lead_id, from_email, kind, summary FROM replies WHERE kind NOT IN ('bounce','out_of_office','unsubscribe','not_interested') ORDER BY id DESC LIMIT 1", one=True)
    return {
        'drafts': c("SELECT COUNT(*) n FROM messages WHERE status='draft'"),
        'inbox': c("SELECT COUNT(DISTINCT lead_id) n FROM replies WHERE handled=0 AND kind NOT IN ('bounce','out_of_office')"),
        'tasks': c("SELECT COUNT(*) n FROM leads WHERE next_action_date IS NOT NULL AND next_action_date<>'' AND next_action_date<=? "
                   "AND COALESCE(stage,'') NOT IN ('won','lost')", (today_local().isoformat(),)),
        'ready': c("SELECT COUNT(*) n FROM leads WHERE status='ready'"),
        'paused': db.get('sending_paused') == '1', 'paused_reason': db.get('paused_reason') or '',
        'email_ready': bool(db.get('smtp_host') and db.get('sender_email')),
        'sent_today': worker.sent_today(), 'limit': worker.effective_limit()['limit'],
        'last_reply': last,
        'jobs_running': c("SELECT COUNT(*) n FROM jobs WHERE status='running'") + c("SELECT COUNT(*) n FROM searches WHERE status IN ('queued','running')"),
    }


# ---------- today ----------
def day_series(days):
    """Per day in the user's own time zone: emails sent, replies, interested replies, bounces."""
    start_day = today_local() - dt.timedelta(days=days - 1)
    since = dt.datetime.combine(start_day, dt.time(0), worker.my_tz()).astimezone(dt.timezone.utc).isoformat()
    buckets = {(start_day + dt.timedelta(days=i)).isoformat(): {'sent': 0, 'replies': 0, 'interested': 0, 'bounces': 0} for i in range(days)}
    for r in db.q("SELECT sent_at FROM messages WHERE status='sent' AND kind='campaign' AND sent_at>=?", (since,)):
        d = local_date(r['sent_at'])
        if d and d.isoformat() in buckets: buckets[d.isoformat()]['sent'] += 1
    for r in db.q("SELECT received_at, kind FROM replies WHERE received_at>=?", (since,)):
        d = local_date(r['received_at'])
        if not d or d.isoformat() not in buckets: continue
        b = buckets[d.isoformat()]
        if r['kind'] == 'bounce': b['bounces'] += 1
        elif r['kind'] != 'out_of_office':
            b['replies'] += 1
            if r['kind'] in ('interested', 'question'): b['interested'] += 1
    return [dict(day=k, **v) for k, v in buckets.items()]


def setup_state():
    return {'company': bool((db.get('company_profile') or '').strip() and db.get('sender_name')),
            'email': bool(db.get('smtp_host') and db.get('sender_email')), 'inbox': bool(db.get('imap_host')),
            'ai': ai.available(), 'places': bool(db.get('google_places_api_key')),
            'campaign': bool(db.q('SELECT 1 FROM campaigns LIMIT 1', one=True)),
            'facts': any((db.get(k) or '').strip() for k, _ in ai.FACTS)}


def today(_q, _b):
    c = lambda sql, a=(): db.q(sql, a, one=True)['n']
    tday = today_local().isoformat()
    series = day_series(14)
    week = series[-7:]
    sent7, replies7, int7 = sum(d['sent'] for d in week), sum(d['replies'] for d in week), sum(d['interested'] for d in week)
    since30 = (worker.utcnow() - dt.timedelta(days=30)).isoformat()
    contacted30 = c("SELECT COUNT(DISTINCT lead_id) n FROM messages WHERE status='sent' AND kind='campaign' AND sent_at>=?", (since30,))
    replied30 = c('''SELECT COUNT(DISTINCT r.lead_id) n FROM replies r WHERE r.kind NOT IN ('bounce','out_of_office') AND r.lead_id IN
                     (SELECT lead_id FROM messages WHERE status='sent' AND kind='campaign' AND sent_at>=?)''', (since30,))
    pipe = {s: {'n': 0, 'value': 0.0} for s in STAGES}
    for r in db.q("SELECT stage, COUNT(*) n, SUM(COALESCE(deal_value,0)) v FROM leads WHERE stage IS NOT NULL AND stage<>'' GROUP BY stage"):
        if r['stage'] in pipe: pipe[r['stage']] = {'n': r['n'], 'value': r['v'] or 0}
    tasks = db.q(f'''SELECT id, company, country, stage, next_action, next_action_date, deal_value, deal_currency FROM leads
                     WHERE next_action_date IS NOT NULL AND next_action_date<>'' AND next_action_date<=? AND COALESCE(stage,'') NOT IN ('won','lost')
                     ORDER BY next_action_date LIMIT 8''', ((today_local() + dt.timedelta(days=2)).isoformat(),))
    replies = db.q('''SELECT r.id, r.lead_id, r.kind, r.summary, r.subject, r.received_at, l.company, l.country FROM replies r JOIN leads l ON l.id=r.lead_id
                      WHERE r.handled=0 AND r.kind NOT IN ('bounce','out_of_office') ORDER BY r.id DESC LIMIT 5''')
    first_of_month = worker.utcnow().astimezone(worker.my_tz()).replace(day=1, hour=0, minute=0, second=0).astimezone(dt.timezone.utc).isoformat()
    lim = worker.effective_limit()
    return {
        'date': tday, 'company_name': db.get('company_name'), 'sender_name': db.get('sender_name'),
        'counts': {'drafts': c("SELECT COUNT(*) n FROM messages WHERE status='draft'"),
                   'queued': c("SELECT COUNT(*) n FROM messages WHERE status='approved' AND kind='campaign'"),
                   'failed': c("SELECT COUNT(*) n FROM messages WHERE status='failed'"),
                   'inbox': c("SELECT COUNT(DISTINCT lead_id) n FROM replies WHERE handled=0 AND kind NOT IN ('bounce','out_of_office')"),
                   'tasks_due': c("SELECT COUNT(*) n FROM leads WHERE next_action_date IS NOT NULL AND next_action_date<>'' AND next_action_date<=? "
                                  "AND COALESCE(stage,'') NOT IN ('won','lost')", (tday,)),
                   'ready': c("SELECT COUNT(*) n FROM leads WHERE status='ready'"),
                   'unchecked': c("SELECT COUNT(*) n FROM leads WHERE fit IS NULL"),
                   'leads': c('SELECT COUNT(*) n FROM leads'), 'active': c("SELECT COUNT(*) n FROM enrollments WHERE status IN ('active','waiting')")},
        'week': {'sent': sent7, 'replies': replies7, 'interested': int7,
                 'reply_rate': round(100.0 * replied30 / contacted30, 1) if contacted30 else None, 'contacted30': contacted30},
        'series': series,
        'sending': {'paused': db.get('sending_paused') == '1', 'reason': db.get('paused_reason') or '',
                    'email_ready': bool(db.get('smtp_host') and db.get('sender_email')), 'sent_today': worker.sent_today(), **lim,
                    'forecast': worker.forecast(), 'markets': worker.markets(), 'hours': [db.get_int('send_hour_start', 9), db.get_int('send_hour_end', 17)],
                    'weekdays_only': db.get('send_weekdays_only') == '1', 'my_tz': db.get('my_timezone') or 'Asia/Karachi'},
        'pipeline': pipe, 'tasks': tasks, 'replies': replies,
        'usage': {**ai.usage_summary(first_of_month), 'calls_today': ai.calls_today(), 'call_limit': db.get_int('ai_daily_call_limit', 400)},
        'setup': setup_state(), 'last_inbox_check': db.get('last_inbox_check') or '',
        'log': db.q('SELECT at, level, text FROM log ORDER BY id DESC LIMIT 8'),
    }


# ---------- leads ----------
VIEWS = {'ready': "status='ready'", 'needs_email': "COALESCE(email,'')='' AND status NOT IN ('rejected')",
         'in_campaign': "status='in_campaign'", 'replied': "status IN ('replied','not_interested')", 'rejected': "status='rejected'",
         'unchecked': 'fit IS NULL', 'bad_email': "email_status IN ('no_mx','invalid')", 'no_reply': "status='no_reply'"}


def leads_list(qs, _b):
    where, args = [], []
    for f in ('status', 'fit', 'country', 'source', 'stage', 'email_status'):
        v = qs.get(f)
        if v:
            where.append(f'{f}=?'); args.append(v)
    if qs.get('view') in VIEWS:
        where.append(VIEWS[qs['view']])
    if qs.get('has_email') == '1':
        where.append("COALESCE(email,'')<>''")
    if qs.get('q'):
        where.append('(company LIKE ? OR email LIKE ? OR domain LIKE ? OR city LIKE ? OR contact_name LIKE ?)'); args += ['%' + qs['q'] + '%'] * 5
    w = ('WHERE ' + ' AND '.join(where)) if where else ''
    order = {'score': 'COALESCE(score,-1) DESC, id DESC', 'company': 'company COLLATE NOCASE', 'new': 'id DESC',
             'contact': "COALESCE(last_contact_at,'') DESC, id DESC", 'country': 'country COLLATE NOCASE, company COLLATE NOCASE'}.get(qs.get('sort'), 'id DESC')
    page = max(1, int(qs.get('page') or 1)); per = min(500, max(20, int(qs.get('per') or 100)))
    total = db.q(f'SELECT COUNT(*) n FROM leads {w}', args, one=True)['n']
    rows = db.q(f'SELECT {LEAD_COLS} FROM leads {w} ORDER BY {order} LIMIT ? OFFSET ?', args + [per, (page - 1) * per])
    countries = [r['country'] for r in db.q("SELECT DISTINCT country FROM leads WHERE COALESCE(country,'')<>'' ORDER BY country")]
    counts = {k: db.q(f'SELECT COUNT(*) n FROM leads WHERE {v}', one=True)['n'] for k, v in VIEWS.items()}
    counts['all'] = db.q('SELECT COUNT(*) n FROM leads', one=True)['n']
    return {'total': total, 'page': page, 'per': per, 'rows': rows, 'countries': countries, 'counts': counts}


def timeline(lead, messages, replies, notes):
    ev = [{'at': lead['created_at'], 'type': 'found', 'data': {'source': lead.get('source'), 'query': lead.get('search_query')}}]
    for m in messages:
        if m['status'] == 'sent' and m['sent_at']:
            ev.append({'at': m['sent_at'], 'type': {'reply': 'answered', 'forward': 'forwarded'}.get(m['kind'], 'sent'),
                       'data': {'step': m['step'], 'subject': m['subject'], 'to': m['to_email']}})
    for r in replies:
        ev.append({'at': r['received_at'], 'type': 'reply', 'data': {'kind': r['kind'], 'summary': r['summary']}})
    for n in notes:
        ev.append({'at': n['at'], 'type': n['kind'] or 'note', 'data': {'text': n['text'], 'id': n['id']}})
    return sorted(ev, key=lambda e: e['at'] or '', reverse=True)


def lead_get(_q, _b, lid):
    l = db.q('SELECT * FROM leads WHERE id=?', (lid,), one=True)
    if not l: raise API('Not found', 404)
    l['emails'] = db.jloads(l['emails'], [])
    msgs = db.q('SELECT id, step, subject, body, status, error, sent_at, created_at, written_by, kind, to_email FROM messages WHERE lead_id=? ORDER BY id', (lid,))
    reps = db.q('SELECT * FROM replies WHERE lead_id=? ORDER BY id', (lid,))
    notes = db.q('SELECT * FROM notes WHERE lead_id=? ORDER BY id', (lid,))
    l['messages'], l['replies'], l['note_list'] = msgs, reps, [n for n in notes if n['kind'] == 'note']
    l['campaigns'] = db.q('SELECT e.*, c.name FROM enrollments e JOIN campaigns c ON c.id=e.campaign_id WHERE e.lead_id=?', (lid,))
    l['timeline'] = timeline(l, msgs, reps, notes)
    l['suppressed'] = db.suppressed(l.get('email'))
    return l


def lead_add(_q, b):
    if not (b.get('company') or b.get('website') or b.get('email')):
        raise API('Give at least a company name, website or email.', code='need_one')
    if b.get('email') and not finder.valid_email(b['email']):
        raise API('That email address does not look right.', code='bad_email')
    lid = finder.add_lead(b, 'manual')
    if not lid: raise API('This company is already in your leads.', code='duplicate')
    if b.get('check', True):
        finder.process_leads([lid])
    return {'id': lid}


def lead_edit(_q, b, lid):
    allowed = ['company', 'website', 'email', 'contact_name', 'country', 'city', 'phone', 'status', 'notes', 'fit']
    sets = {k: (b[k] or '').strip() for k in allowed if k in b and b[k] is not None}
    lead = db.q('SELECT * FROM leads WHERE id=?', (lid,), one=True)
    if not lead: raise API('Not found', 404)
    recheck = False
    if 'email' in sets:
        sets['email'] = sets['email'].lower()
        if sets['email'] and not finder.valid_email(sets['email']):
            raise API('That email address does not look right.', code='bad_email')
        if sets['email'] != (lead['email'] or ''):
            sets['email_status'] = None
            recheck = bool(sets['email'])
            ems = db.jloads(lead['emails'], [])
            if sets['email'] and sets['email'] not in ems:
                sets['emails'] = json.dumps([sets['email']] + ems)
    if 'website' in sets:
        sets['website'] = finder.norm_url(sets['website']); sets['domain'] = finder.domain_of(sets['website'])
    if 'fit' in sets and sets['fit'] not in ('good', 'maybe', 'no', ''):
        del sets['fit']
    if sets.get('fit') == '':
        sets['fit'] = None
    if not sets: return {'ok': True}
    if sets.get('status') in ('rejected', 'unsubscribed', 'not_interested'):
        mailer.stop_lead(lid, 'stopped')
    if sets.get('status') == 'unsubscribed':
        db.suppress(sets.get('email') or lead['email'], 'marked by you')
    new_email = sets.get('email', lead['email'])
    new_fit = sets.get('fit', lead['fit'])
    if 'status' not in sets and lead['status'] in ('new', 'ready') and new_fit in ('good', 'maybe'):
        sets['status'] = 'ready' if new_email else 'new'
    db.x(f"UPDATE leads SET {', '.join(k + '=?' for k in sets)}, updated_at=? WHERE id=?", (*sets.values(), db.now(), lid))
    if recheck and db.get('mx_check_on') == '1':
        threading.Thread(target=finder.verify_email, args=(lid,), daemon=True).start()
    return {'ok': True}


def lead_deal(_q, b, lid):
    lead = db.q('SELECT stage FROM leads WHERE id=?', (lid,), one=True)
    if not lead: raise API('Not found', 404)
    sets = {}
    if 'stage' in b:
        st = b['stage'] or None
        if st and st not in STAGES: raise API('Unknown stage', code='bad_stage')
        if st != lead['stage']:
            sets['stage'] = st; sets['stage_changed_at'] = db.now()
            db.note(lid, f"{lead['stage'] or ''}>{st or ''}", 'stage')
    if 'deal_value' in b:
        v = str(b['deal_value'] or '').replace(',', '').strip()
        try:
            sets['deal_value'] = float(v) if v else None
        except ValueError:
            raise API('Value must be a number', code='bad_number')
    if 'deal_currency' in b:
        sets['deal_currency'] = (b['deal_currency'] or 'USD').upper()[:3]
    if 'next_action' in b:
        sets['next_action'] = (b['next_action'] or '').strip()[:300]
    if 'next_action_date' in b:
        d = (b['next_action_date'] or '').strip()
        if d and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d): raise API('Date must look like 2026-10-20', code='bad_date')
        sets['next_action_date'] = d or None
    if sets:
        db.x(f"UPDATE leads SET {', '.join(k + '=?' for k in sets)}, updated_at=? WHERE id=?", (*sets.values(), db.now(), lid))
    return {'ok': True}


def note_add(_q, b, lid):
    text = (b.get('text') or '').strip()
    if not text: raise API('Write something first', code='empty')
    return {'id': db.note(lid, text, 'note')}


def note_delete(_q, _b, nid):
    db.x("DELETE FROM notes WHERE id=? AND kind='note'", (nid,)); return {'ok': True}


def pipeline(_q, _b):
    rows = db.q(f'''SELECT {LEAD_COLS}, stage_changed_at FROM leads WHERE stage IS NOT NULL AND stage<>'' ORDER BY
                    CASE WHEN next_action_date IS NULL OR next_action_date='' THEN 1 ELSE 0 END, next_action_date, stage_changed_at DESC''')
    cols = []
    for s in STAGES:
        items = [r for r in rows if r['stage'] == s]
        cols.append({'stage': s, 'leads': items, 'value': sum(r['deal_value'] or 0 for r in items)})
    return {'stages': cols, 'today': today_local().isoformat()}


def leads_delete(_q, b):
    for i in ids_of(b):
        mailer.stop_lead(i, 'deleted')
        db.x("DELETE FROM messages WHERE lead_id=? AND status IN ('draft','approved','cancelled','failed')", (i,))
        db.x("DELETE FROM enrollments WHERE lead_id=? AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.enrollment_id=enrollments.id)", (i,))
        if db.q("SELECT 1 FROM messages WHERE lead_id=? AND status='sent'", (i,), one=True):
            db.x("UPDATE leads SET status='rejected' WHERE id=?", (i,))   # keep the history of what was sent
        else:
            db.x('DELETE FROM notes WHERE lead_id=?', (i,))
            db.x('DELETE FROM leads WHERE id=?', (i,))
    return {'ok': True}


def leads_check(_q, b):
    ids = ids_of(b)
    if not ids:
        ids = [r['id'] for r in db.q("SELECT id FROM leads WHERE fit IS NULL OR crawl_status='pending' ORDER BY id LIMIT 500")]
    if not ids: raise API('No unchecked leads.', code='nothing_to_check')
    return {'job': finder.process_leads(ids, do_crawl=b.get('crawl', True), do_qualify=b.get('qualify', True)), 'count': len(ids)}


def leads_verify(_q, b):
    ids = ids_of(b) or [r['id'] for r in db.q("SELECT id FROM leads WHERE COALESCE(email,'')<>'' AND email_status IS NULL LIMIT 1000")]
    if not ids: raise API('Nothing to check', code='nothing_to_check')
    return {'job': finder.verify_leads(ids), 'count': len(ids)}


def leads_import(_q, b):
    try:
        r = finder.import_csv(b.get('csv') or '', b.get('country') or '')
    except ValueError as e:
        raise API(str(e), code='need_column')
    return {'added': r['added'], 'skipped': r['skipped']}


def leads_paste(_q, b):
    r = finder.import_pasted(b.get('text') or '', (b.get('country') or '').strip())
    if r['ids'] and b.get('auto_check', True):
        r['job'] = finder.process_leads(r['ids'])
    return r


def _upload(b):
    try:
        data = base64.b64decode(b.get('data') or '', validate=False)
    except ValueError:
        raise API('Could not read the file', code='bad_file')
    if not data: raise API('The file is empty', code='empty_file')
    return b.get('name') or 'file.csv', data


def import_preview(_q, b):
    name, data = _upload(b)
    try:
        return finder.preview(name, data)
    except ValueError as e:
        raise API(str(e), code=str(e))


def import_commit(_q, b):
    name, data = _upload(b)
    try:
        r = finder.import_rows(name, data, b.get('mapping') or {}, (b.get('country') or '').strip())
    except ValueError as e:
        raise API(str(e), code=str(e))
    if r['ids'] and b.get('auto_check', True):
        r['job'] = finder.process_leads(r['ids'])
    return r


def search(_q, b):
    query = (b.get('query') or '').strip()
    if not query: raise API('Type what to search for.', code='need_query')
    if not db.get('google_places_api_key'): raise API('Add a Google Places API key in Settings first.', code='places_no_key')
    locs = b.get('locations')
    if isinstance(locs, str):
        locs = re.split(r'[\n;]+', locs)
    if not locs and b.get('location'):
        locs = [b['location']]
    locs = [l.strip() for l in (locs or []) if l and l.strip()][:30]
    mx = max(1, min(60, int(b.get('max') or 60)))
    ids = finder.queue_searches(query, locs, mx, b.get('auto_check', True))
    return {'queued': len(ids), 'ids': ids}


def searches(_q, _b):
    return db.q("SELECT * FROM searches ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END, id DESC LIMIT 40")


def search_cancel(_q, _b, sid):
    db.x("UPDATE searches SET status='cancelled', finished_at=? WHERE id=? AND status='queued'", (db.now(), sid)); return {'ok': True}


def search_suggest(_q, b):
    return finder.suggest_queries((b.get('location') or '').strip(), (b.get('focus') or '').strip())


def jobs(_q, _b):
    return db.q('SELECT * FROM jobs ORDER BY id DESC LIMIT 10')


# ---------- campaigns ----------
def campaigns_list(_q, _b):
    rows = db.q('SELECT * FROM campaigns ORDER BY active DESC, id DESC')
    for r in rows:
        r['steps'] = db.jloads(r['steps'], [])
        st = {x['status']: x['n'] for x in db.q('SELECT status, COUNT(*) n FROM enrollments WHERE campaign_id=? GROUP BY status', (r['id'],))}
        sent = db.q("SELECT COUNT(*) n, COUNT(DISTINCT lead_id) l FROM messages WHERE campaign_id=? AND status='sent' AND kind='campaign'", (r['id'],), one=True)
        replied = db.q('''SELECT COUNT(DISTINCT r.lead_id) n FROM replies r JOIN enrollments e ON e.lead_id=r.lead_id AND e.campaign_id=?
                          WHERE r.kind NOT IN ('bounce','out_of_office')''', (r['id'],), one=True)['n']
        interested = db.q('''SELECT COUNT(DISTINCT r.lead_id) n FROM replies r JOIN enrollments e ON e.lead_id=r.lead_id AND e.campaign_id=?
                             WHERE r.kind IN ('interested','question')''', (r['id'],), one=True)['n']
        r['stats'] = {'leads': sum(st.values()), 'active': st.get('active', 0) + st.get('waiting', 0), 'replied': replied, 'interested': interested,
                      'bounced': st.get('bounced', 0), 'done': st.get('done', 0), 'sent': sent['n'], 'contacted': sent['l'],
                      'reply_rate': round(100.0 * replied / sent['l'], 1) if sent['l'] else None,
                      'drafts': db.q("SELECT COUNT(*) n FROM messages WHERE campaign_id=? AND status='draft'", (r['id'],), one=True)['n']}
    return rows


def _camp_fields(b):
    steps = b.get('steps') or []
    clean = []
    for i, s in enumerate(steps[:6]):
        clean.append({'day': max(0, int(s.get('day') or (0 if i == 0 else 3 * i))), 'kind': 'template' if s.get('kind') == 'template' else 'ai',
                      'instructions': (s.get('instructions') or '').strip()[:1500], 'subject': (s.get('subject') or '').strip()[:200],
                      'body': (s.get('body') or '').strip()[:5000]})
    if not clean: raise API('A campaign needs at least one email.', code='need_step')
    for i in range(1, len(clean)):
        if clean[i]['day'] <= clean[i - 1]['day']: clean[i]['day'] = clean[i - 1]['day'] + 1
    clean[0]['day'] = 0
    return {'name': (b.get('name') or 'Campaign').strip()[:120], 'pitch': (b.get('pitch') or '').strip()[:2000],
            'instructions': (b.get('instructions') or '').strip()[:2000], 'steps': json.dumps(clean),
            'write_in_their_language': 1 if b.get('write_in_their_language') else 0,
            'auto_approve_followups': 1 if b.get('auto_approve_followups') else 0, 'active': 0 if b.get('active') is False else 1}


def campaign_get(_q, _b, cid):
    r = db.q('SELECT * FROM campaigns WHERE id=?', (cid,), one=True)
    if not r: raise API('Not found', 404)
    r['steps'] = db.jloads(r['steps'], [])
    return r


def campaign_add(_q, b):
    f = _camp_fields(b)
    return {'id': db.x(f"INSERT INTO campaigns({', '.join(f)}, created_at) VALUES ({', '.join('?' * len(f))}, ?)", (*f.values(), db.now()))}


def campaign_edit(_q, b, cid):
    if set(b) == {'active'}:
        db.x('UPDATE campaigns SET active=? WHERE id=?', (1 if b['active'] else 0, cid)); return {'ok': True}
    f = _camp_fields(b)
    db.x(f"UPDATE campaigns SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), cid))
    return {'ok': True}


def campaign_duplicate(_q, _b, cid):
    c = db.q('SELECT * FROM campaigns WHERE id=?', (cid,), one=True)
    if not c: raise API('Not found', 404)
    return {'id': db.x('''INSERT INTO campaigns(name, pitch, instructions, steps, write_in_their_language, auto_approve_followups, active, created_at)
                          VALUES (?,?,?,?,?,?,?,?)''', (c['name'] + ' (copy)', c['pitch'], c['instructions'], c['steps'],
                                                        c['write_in_their_language'], c['auto_approve_followups'], 0, db.now()))}


def campaign_delete(_q, _b, cid):
    if db.q("SELECT 1 FROM messages WHERE campaign_id=? AND status='sent'", (cid,), one=True):
        db.x('UPDATE campaigns SET active=0 WHERE id=?', (cid,))
        return {'ok': True, 'code': 'paused_not_deleted'}
    for e in db.q('SELECT lead_id FROM enrollments WHERE campaign_id=?', (cid,)):
        db.x("UPDATE leads SET status='ready' WHERE id=? AND status='in_campaign'", (e['lead_id'],))
    db.x('DELETE FROM messages WHERE campaign_id=?', (cid,)); db.x('DELETE FROM enrollments WHERE campaign_id=?', (cid,))
    db.x('DELETE FROM campaigns WHERE id=?', (cid,))
    return {'ok': True}


def campaign_enroll(_q, b, cid):
    ids = ids_of(b)
    if b.get('all_ready'):
        ids = [r['id'] for r in db.q("SELECT id FROM leads WHERE status='ready' AND fit IN ('good','maybe') ORDER BY score DESC")]
    if not ids: raise API('Choose leads first (they need an email address).', code='no_leads')
    r = worker.enroll(cid, ids)
    threading.Thread(target=worker.draft_tick, kwargs={'limit': 3}, daemon=True).start()
    return r


def campaign_preview(_q, b, cid):
    camp = db.q('SELECT * FROM campaigns WHERE id=?', (cid,), one=True) if cid else None
    if b.get('draft'):          # preview of a campaign that is being edited and not saved yet
        f = _camp_fields(b['draft'])
        camp = dict(camp or {}, **f)
    if not camp: raise API('Not found', 404)
    lead = db.q('SELECT * FROM leads WHERE id=?', (int(b.get('lead_id') or 0),), one=True) or \
        db.q("SELECT * FROM leads WHERE fit='good' ORDER BY score DESC LIMIT 1", one=True) or db.q('SELECT * FROM leads LIMIT 1', one=True)
    if not lead: raise API('Add at least one lead to preview with.', code='no_leads')
    steps = db.jloads(camp['steps'], [])
    i = max(0, min(len(steps) - 1, int(b.get('step') or 0)))
    step = steps[i]
    if step.get('kind', 'ai') == 'ai' and ai.available():
        hist = [{'subject': 'Earlier email', 'body': '(earlier email in this thread)'}] * i
        try:
            out = ai.write_email(lead, camp, i, step, hist); by = 'ai'
        except (ai.AIError, ai.NoAI) as e:
            raise API(f'AI could not write: {e}', code=getattr(e, 'code', 'ai_error'))
    else:
        sname = db.get('sender_name')
        out = {'subject': ai.fill_template(step.get('subject'), lead, sname), 'body': ai.fill_template(step.get('body'), lead, sname)}; by = 'template'
    if i > 0:
        out['subject'] = 'Re: ' + (out.get('subject') or 'earlier email')
    return {'lead': lead['company'], 'lead_id': lead['id'], 'subject': out['subject'], 'body': out['body'], 'footer': mailer.footer('cold'),
            'written_by': by, 'lint': quality.lint(out['subject'], out['body'], 'campaign', i, lead['company'])}


# ---------- emails waiting for approval, queued, sent ----------
def messages_list(qs, _b):
    st = qs.get('status') or 'draft'
    rows = db.q('''SELECT m.*, l.company, l.country, l.city, l.contact_name, l.website, l.score, l.fit, l.ai_reason, l.category, l.email_status,
                   substr(l.site_text, 1, 900) site_text, c.name campaign, c.steps campaign_steps FROM messages m
                   JOIN leads l ON l.id=m.lead_id LEFT JOIN campaigns c ON c.id=m.campaign_id
                   WHERE m.status=? AND m.kind='campaign' ORDER BY ''' + ('m.sent_at DESC' if st == 'sent' else 'm.id') + ' LIMIT 500', (st,))
    for r in rows:
        r['steps_total'] = len(db.jloads(r.pop('campaign_steps') or '[]', []))
        if st in ('draft', 'approved', 'failed'):
            r['lint'] = quality.lint(r['subject'], r['body'], 'campaign', r['step'] or 0, r['company'])
        else:
            r.pop('site_text', None)
    return {'rows': rows, 'footer': mailer.footer('cold')}


def message_edit(_q, b, mid):
    m = db.q('SELECT status FROM messages WHERE id=?', (mid,), one=True)
    if not m or m['status'] not in ('draft', 'approved', 'failed'): raise API('This email can no longer be changed.', code='locked')
    db.x('UPDATE messages SET subject=?, body=? WHERE id=?', ((b.get('subject') or '').strip()[:200], (b.get('body') or '').strip(), mid))
    m = db.q('SELECT m.subject, m.body, m.step, l.company FROM messages m JOIN leads l ON l.id=m.lead_id WHERE m.id=?', (mid,), one=True)
    return {'ok': True, 'lint': quality.lint(m['subject'], m['body'], 'campaign', m['step'] or 0, m['company'])}


def messages_approve(_q, b):
    n, blocked = 0, []
    for i in ids_of(b):
        m = db.q('SELECT m.*, l.company FROM messages m JOIN leads l ON l.id=m.lead_id WHERE m.id=?', (i,), one=True)
        if not m or m['status'] not in ('draft', 'failed'):
            continue
        if quality.blocks(quality.lint(m['subject'], m['body'], 'campaign', m['step'] or 0, m['company'])):
            blocked.append(i); continue
        n += db.x("UPDATE messages SET status='approved', approved_at=?, error=NULL WHERE id=?", (db.now(), i))
    return {'approved': n, 'blocked': blocked}


def messages_reject(_q, b):
    """Skip this company: cancel the email and take the lead out of the campaign."""
    for i in ids_of(b):
        m = db.q('SELECT * FROM messages WHERE id=?', (i,), one=True)
        if not m or m['status'] not in ('draft', 'approved', 'failed'): continue
        db.x("UPDATE messages SET status='cancelled', error='skipped by you' WHERE id=?", (i,))
        db.x("UPDATE enrollments SET status='stopped' WHERE id=?", (m['enrollment_id'],))
        if m['step'] == 0:
            db.x("UPDATE leads SET status='ready' WHERE id=? AND status='in_campaign'", (m['lead_id'],))
    return {'ok': True}


def message_rewrite(_q, b, mid):
    m = db.q('SELECT * FROM messages WHERE id=?', (mid,), one=True)
    if not m or m['status'] not in ('draft', 'failed', 'approved'): raise API('This email can no longer be rewritten.', code='locked')
    if not ai.available(): raise API('Rewriting needs the AI key (Settings, AI).', code='ai_needed')
    db.x('DELETE FROM messages WHERE id=?', (mid,))
    db.x("UPDATE enrollments SET status='active', next_due=? WHERE id=?", (db.now(), m['enrollment_id']))
    enr = db.q('SELECT * FROM enrollments WHERE id=?', (m['enrollment_id'],), one=True)
    new = worker.write_for(enr, note=(b.get('note') or '').strip()[:500])
    if not new: raise API('Could not write a new version now (see Activity).', code='rewrite_failed')
    r = db.q('SELECT m.*, l.company FROM messages m JOIN leads l ON l.id=m.lead_id WHERE m.id=?', (new,), one=True)
    r['lint'] = quality.lint(r['subject'], r['body'], 'campaign', r['step'] or 0, r['company'])
    return r


def messages_retry(_q, b):
    n = sum(db.x("UPDATE messages SET status='approved', error=NULL, approved_at=? WHERE id=? AND status='failed'", (db.now(), i)) for i in ids_of(b))
    return {'retried': n}


def message_test(_q, b, mid):
    m = db.q('SELECT * FROM messages WHERE id=?', (mid,), one=True)
    if not m: raise API('Not found', 404)
    to = (b.get('to') or db.get('sender_email') or '').strip()
    if not to: raise API('Set your own email in Settings first.', code='no_sender')
    try:
        mailer.send({'to_email': to, 'subject': '[Test] ' + (m['subject'] or ''), 'body': m['body'] or ''}, mode='cold')
    except mailer.MailError as e:
        raise API(str(e), code=e.code)
    return {'ok': True, 'to': to}


def forecast(_q, _b):
    lim = worker.effective_limit()
    return {**worker.forecast(), 'sent_today': worker.sent_today(), **lim, 'paused': db.get('sending_paused') == '1',
            'reason': db.get('paused_reason') or '', 'email_ready': bool(db.get('smtp_host') and db.get('sender_email'))}


def send_now(_q, _b):
    return {'result': worker.send_tick(force_now=True)}


# ---------- inbox: replies, answers, forwarding ----------
def inbox_list(qs, _b):
    f = qs.get('f') or 'needs'
    rows = db.q('''SELECT r.id, r.lead_id, r.kind, r.summary, r.subject, r.received_at, r.handled, r.from_email,
                   l.company, l.country, l.stage, l.contact_name FROM replies r JOIN leads l ON l.id=r.lead_id ORDER BY r.id DESC LIMIT 3000''')
    convos = {}
    for r in rows:
        c = convos.get(r['lead_id'])
        if not c:
            c = convos[r['lead_id']] = {'lead_id': r['lead_id'], 'company': r['company'], 'country': r['country'], 'stage': r['stage'],
                                        'contact_name': r['contact_name'], 'last': r, 'open': 0, 'count': 0}
        c['count'] += 1
        if not r['handled'] and r['kind'] not in ('bounce', 'out_of_office'):
            c['open'] += 1
    out = list(convos.values())
    if f == 'needs':
        out = [c for c in out if c['open']]
    elif f == 'interested':
        out = [c for c in out if c['last']['kind'] in ('interested', 'question') or c['stage']]
    elif f == 'bounces':
        out = [c for c in out if c['last']['kind'] in ('bounce', 'unsubscribe', 'not_interested', 'out_of_office')]
    counts = {'needs': sum(1 for c in convos.values() if c['open']), 'all': len(convos)}
    return {'rows': out, 'counts': counts}


def _thread(lead_id):
    items = []
    for m in db.q("SELECT id, subject, body, sent_at, kind, written_by, step, to_email FROM messages WHERE lead_id=? AND status='sent' ORDER BY sent_at", (lead_id,)):
        files = db.q('SELECT f.id, f.name, f.size FROM message_files mf JOIN files f ON f.id=mf.file_id WHERE mf.message_id=?', (m['id'],))
        items.append({'who': 'fwd' if m['kind'] == 'forward' else 'us', 'id': m['id'], 'at': m['sent_at'], 'subject': m['subject'], 'body': m['body'],
                      'kind': m['kind'], 'step': m['step'], 'to': m['to_email'], 'files': files})
    for r in db.q('SELECT * FROM replies WHERE lead_id=? ORDER BY received_at', (lead_id,)):
        items.append({'who': 'them', 'id': r['id'], 'at': r['received_at'], 'subject': r['subject'], 'body': r['body'], 'kind': r['kind'],
                      'summary': r['summary'], 'handled': r['handled'], 'from': r['from_email'], 'forwarded_at': r['forwarded_at'], 'ai_draft': r['ai_draft']})
    rank = {'us': 0, 'them': 1, 'fwd': 2}      # same second: a forward always follows the reply it forwards
    return sorted(items, key=lambda i: (i['at'] or '', rank[i['who']]))


def inbox_thread(_q, _b, lead_id):
    lead = db.q(f'SELECT {LEAD_COLS} FROM leads WHERE id=?', (lead_id,), one=True)
    if not lead: raise API('Not found', 404)
    items = _thread(lead_id)
    last = next((i for i in reversed(items) if i['who'] == 'them' and i['kind'] != 'bounce'), None)
    subj = (last or {}).get('subject') or next((i['subject'] for i in items if i['who'] == 'us'), '') or ''
    return {'lead': lead, 'items': items, 'answer_to': last['id'] if last else None, 'draft': (last or {}).get('ai_draft') or '',
            'subject': subj if subj.lower().startswith('re:') else 'Re: ' + subj, 'footer': mailer.footer('warm')}


def inbox_draft(_q, b, lead_id):
    lead = db.q('SELECT * FROM leads WHERE id=?', (lead_id,), one=True)
    if not lead: raise API('Not found', 404)
    items = [i for i in _thread(lead_id) if i['who'] in ('us', 'them') and i['kind'] != 'bounce']
    if ai.available():
        try:
            text, by = ai.draft_reply(lead, items, (b.get('note') or '').strip()[:500]), 'ai'
        except (ai.AIError, ai.NoAI) as e:
            raise API(str(e), code=getattr(e, 'code', 'ai_error'))
    else:
        text, by = ai.reply_template(lead), 'template'
    rid = b.get('reply_id')
    if rid:
        db.x('UPDATE replies SET ai_draft=? WHERE id=?', (text, int(rid)))
    return {'body': text, 'by': by, 'lint': quality.lint('Re', text, 'reply')}


def inbox_send(_q, b, lead_id):
    subject, body = (b.get('subject') or '').strip(), (b.get('body') or '').strip()
    found = quality.lint(subject or 'Re', body, 'reply')
    if quality.blocks(found):
        raise API('Fix the marked parts first', code='blocked', data=found)
    try:
        mid = mailer.send_direct(lead_id, subject or 'Re:', body, b.get('file_ids') or [], b.get('reply_id'))
    except mailer.MailError as e:
        raise API(str(e), code=e.code)
    if b.get('stage') and b['stage'] in STAGES:
        lead_deal({}, {'stage': b['stage']}, lead_id)
    return {'id': mid}


def reply_handled(_q, b, rid):
    db.x('UPDATE replies SET handled=? WHERE id=?', (0 if b.get('handled') is False else 1, rid)); return {'ok': True}


def lead_replies_handled(_q, _b, lead_id):
    db.x('UPDATE replies SET handled=1 WHERE lead_id=?', (lead_id,)); return {'ok': True}


def reply_forward(_q, b, rid):
    to = (b.get('to') or db.get('forward_to') or '').strip()
    if not finder.valid_email(to): raise API('Give the email address to forward to', code='bad_email')
    try:
        mailer.forward_reply(rid, to, b.get('note') or '')
    except mailer.MailError as e:
        raise API(str(e), code=e.code)
    return {'ok': True, 'to': to}


def replies_list(qs, _b):
    w = "WHERE r.kind NOT IN ('bounce','out_of_office')" if qs.get('show') != 'all' else ''
    return db.q(f'''SELECT r.*, l.company, l.country, l.email lead_email FROM replies r LEFT JOIN leads l ON l.id=r.lead_id
                    {w} ORDER BY r.handled, r.id DESC LIMIT 300''')


def inbox_check(_q, b):
    days = max(1, min(90, int(b.get('days') or 14)))
    try:
        mailer._imap().logout()
    except mailer.MailError as e:
        raise API(str(e), code=e.code)
    except Exception as e:  # noqa
        raise API(str(e), code='mail_error')
    return {'job': finder.start_job('inbox', 1, lambda p: f"{mailer.check_replies(days)['new']} new replies or bounces")}


# ---------- files for attachments ----------
def files_list(_q, _b):
    return db.q('SELECT id, name, size, mime, created_at FROM files ORDER BY id DESC')


def file_delete(_q, _b, fid):
    f = db.q('SELECT * FROM files WHERE id=?', (fid,), one=True)
    if f:
        try:
            os.remove(os.path.join(db.FILES_DIR, f['stored']))
        except OSError:
            pass
        db.x('DELETE FROM files WHERE id=?', (fid,))
    return {'ok': True}


def save_upload(name, data, mime):
    name = os.path.basename(name or 'file').strip() or 'file'
    safe = re.sub(r'[^A-Za-z0-9._ -]+', '_', name)[:120]
    stored = f'{secrets.token_hex(6)}_{safe}'
    os.makedirs(db.FILES_DIR, exist_ok=True)
    with open(os.path.join(db.FILES_DIR, stored), 'wb') as fh:
        fh.write(data)
    return db.x('INSERT INTO files(name, stored, size, mime, created_at) VALUES (?,?,?,?,?)', (name[:200], stored, len(data), mime, db.now()))


# ---------- reports ----------
def reports(qs, _b):
    days = max(7, min(365, int(qs.get('days') or 30)))
    since = (worker.utcnow() - dt.timedelta(days=days)).isoformat()
    c = lambda sql, a=(): db.q(sql, a, one=True)['n']
    contacted = c("SELECT COUNT(DISTINCT lead_id) n FROM messages WHERE status='sent' AND kind='campaign' AND sent_at>=?", (since,))
    base = "(SELECT lead_id FROM messages WHERE status='sent' AND kind='campaign' AND sent_at>=?)"
    replied = c(f"SELECT COUNT(DISTINCT lead_id) n FROM replies WHERE kind NOT IN ('bounce','out_of_office') AND lead_id IN {base}", (since,))
    interested = c(f"SELECT COUNT(DISTINCT lead_id) n FROM replies WHERE kind IN ('interested','question') AND lead_id IN {base}", (since,))
    bounced = c(f"SELECT COUNT(DISTINCT lead_id) n FROM replies WHERE kind='bounce' AND lead_id IN {base}", (since,))
    won = c(f"SELECT COUNT(*) n FROM leads WHERE stage='won' AND id IN {base}", (since,))
    funnel = {'found': c('SELECT COUNT(*) n FROM leads WHERE created_at>=?', (since,)),
              'good': c("SELECT COUNT(*) n FROM leads WHERE created_at>=? AND fit='good'", (since,)),
              'contacted': contacted, 'replied': replied, 'interested': interested, 'won': won, 'bounced': bounced}
    by_country = db.q(f'''SELECT COALESCE(NULLIF(l.country,''),'?') country, COUNT(DISTINCT l.id) contacted,
              COUNT(DISTINCT CASE WHEN r.kind NOT IN ('bounce','out_of_office') THEN r.lead_id END) replied,
              COUNT(DISTINCT CASE WHEN r.kind IN ('interested','question') THEN r.lead_id END) interested
              FROM leads l LEFT JOIN replies r ON r.lead_id=l.id WHERE l.id IN {base}
              GROUP BY 1 ORDER BY contacted DESC LIMIT 20''', (since,))
    for r in by_country:
        r['rate'] = round(100.0 * r['replied'] / r['contacted'], 1) if r['contacted'] else None
    camps = campaigns_list({}, {})
    won_value = db.q("SELECT COALESCE(SUM(deal_value),0) v FROM leads WHERE stage='won'", one=True)['v']
    open_value = db.q(f"SELECT COALESCE(SUM(deal_value),0) v FROM leads WHERE stage IN ({','.join('?' * len(OPEN_STAGES))})", OPEN_STAGES, one=True)['v']
    return {'days': days, 'series': day_series(min(days, 120)), 'funnel': funnel, 'by_country': by_country,
            'campaigns': [{'id': x['id'], 'name': x['name'], 'active': x['active'], **x['stats']} for x in camps],
            'usage': ai.usage_summary(since), 'won_value': won_value, 'open_value': open_value,
            'rates': {'reply': round(100.0 * replied / contacted, 1) if contacted else None,
                      'interested': round(100.0 * interested / contacted, 1) if contacted else None,
                      'bounce': round(100.0 * bounced / contacted, 1) if contacted else None}}


# ---------- settings and tests ----------
def settings_get(_q, _b):
    return masked_settings()


INT_LIMITS = {'daily_limit': (1, 200), 'gap_min_minutes': (0, 120), 'gap_max_minutes': (0, 240), 'send_hour_start': (0, 23),
              'send_hour_end': (1, 24), 'warmup_start': (1, 200), 'warmup_step': (0, 100), 'warmup_every_days': (1, 60),
              'ai_daily_call_limit': (0, 100000), 'smtp_port': (1, 65535), 'imap_port': (1, 65535), 'bounce_guard_pct': (1, 50),
              'backup_keep': (1, 365)}


def settings_save(_q, b):
    for k, v in b.items():
        if k not in db.DEFAULTS or k in ('admin_password_hash', 'warmup_started', 'last_backup', 'setup_done'):
            continue
        v = '' if v is None else str(v).strip()
        if k in db.SECRET_KEYS and v.startswith('•'):
            continue
        if k in INT_LIMITS and v:
            try:
                n = int(float(v))
            except ValueError:
                raise API(f'{k} must be a number', code='bad_number', data={'field': k})
            lo, hi = INT_LIMITS[k]
            v = str(max(lo, min(hi, n)))
        if k in ('sender_email', 'reply_to', 'forward_to') and v and not finder.valid_email(v):
            raise API('That email address does not look right.', code='bad_email', data={'field': k})
        if k == 'warmup_on' and v == '1' and db.get('warmup_on') != '1':
            db.put('warmup_started', '')
        db.put(k, v)
    return masked_settings()


def setup_done(_q, _b):
    db.put('setup_done', '1'); return {'ok': True}


def set_password(_q, b):
    pw = b.get('password') or ''
    if len(pw) < 8: raise API('Use at least 8 characters.', code='pw_short')
    stored = db.get('admin_password_hash')
    if stored and not check_pw(b.get('current') or '', stored): raise API('Current password is wrong.', code='pw_wrong')
    db.put('admin_password_hash', hash_pw(pw))
    return {'ok': True}


def test_smtp(_q, b):
    to = (b.get('to') or db.get('sender_email') or '').strip()
    if not finder.valid_email(to): raise API('Give an email address to send the test to.', code='bad_email')
    try:
        mailer.send_test(to)
    except mailer.MailError as e:
        raise API(str(e), code=e.code)
    except Exception as e:  # noqa
        raise API(str(e), code=mailer.explain(e, db.get('smtp_host')))
    return {'ok': True, 'to': to}


def test_imap(_q, _b):
    try:
        n = mailer.test_imap()
    except mailer.MailError as e:
        raise API(str(e), code=e.code)
    except Exception as e:  # noqa
        raise API(str(e), code=mailer.explain(e, db.get('imap_host')))
    return {'ok': True, 'count': n}


def test_ai(_q, _b):
    try:
        t = ai.chat('You answer in five words or fewer.', 'Say hello to RAX Surgicals.', writer=False, max_tokens=30)
    except (ai.AIError, ai.NoAI) as e:
        raise API(str(e), code=getattr(e, 'code', 'ai_no_key'))
    return {'ok': True, 'said': t}


def test_places(_q, _b):
    try:
        n = finder.test_places()
    except finder.PlacesError as e:
        raise API(str(e), code=e.code)
    return {'ok': True, 'found': n}


def check_domain(_q, _b):
    return dnscheck.check_sender(db.get('sender_email'))


def sending(_q, b):
    paused = bool(b.get('paused'))
    db.put('sending_paused', '1' if paused else '0')
    db.put('paused_reason', 'manual' if paused else '')
    if not paused: db.put('next_send_at', '')
    db.log('Sending paused by you' if paused else 'Sending resumed')
    return {'paused': paused}


def log_list(qs, _b):
    return db.q('SELECT * FROM log ORDER BY id DESC LIMIT ?', (min(1000, int(qs.get('n') or 300)),))


def suppression_list(_q, _b):
    return db.q('SELECT * FROM suppression ORDER BY created_at DESC')


def suppression_add(_q, b):
    n = 0
    for e in re.split(r'[\s,;]+', b.get('emails') or ''):
        e = e.strip().lower()
        if not e: continue
        if e.startswith('@') and '.' in e:
            db.suppress(e, 'added by you'); n += 1
            for l in db.q('SELECT id FROM leads WHERE lower(email) LIKE ?', ('%' + e,)):
                db.x("UPDATE leads SET status='unsubscribed' WHERE id=?", (l['id'],)); mailer.stop_lead(l['id'], 'stopped')
        elif finder.valid_email(e):
            db.suppress(e, 'added by you'); n += 1
            for l in db.q('SELECT id FROM leads WHERE lower(email)=?', (e,)):
                db.x("UPDATE leads SET status='unsubscribed' WHERE id=?", (l['id'],)); mailer.stop_lead(l['id'], 'stopped')
    return {'added': n}


def suppression_remove(_q, b):
    db.x('DELETE FROM suppression WHERE email=?', ((b.get('email') or '').lower(),)); return {'ok': True}


def backups_list(_q, _b):
    out = []
    if os.path.isdir(db.BACKUP_DIR):
        for f in sorted(os.listdir(db.BACKUP_DIR), reverse=True):
            if f.endswith('.db'):
                p = os.path.join(db.BACKUP_DIR, f)
                out.append({'name': f, 'size': os.path.getsize(p), 'at': dt.datetime.fromtimestamp(os.path.getmtime(p), dt.timezone.utc).isoformat()})
    return {'files': out, 'folder': db.BACKUP_DIR, 'last': db.get('last_backup')}


def restore(data):
    if not data.startswith(b'SQLite format 3\x00'):
        raise API('This is not a RAX Surgicals Outreach backup file.', code='bad_backup')
    tmp = os.path.join(db.DATA_DIR, f'restore-{secrets.token_hex(4)}.db')
    with open(tmp, 'wb') as fh:
        fh.write(data)
    try:
        t = sqlite3.connect(tmp)
        tables = {r[0] for r in t.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        t.close()
    except sqlite3.DatabaseError:
        tables = set()
    if not {'leads', 'settings', 'messages'} <= tables:
        os.remove(tmp)
        raise API('This is not a RAX Surgicals Outreach backup file.', code='bad_backup')
    with db._lock:
        db.backup(os.path.join(db.BACKUP_DIR, f'before-restore-{dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")}.db'))
        c = sqlite3.connect(db.DB_PATH)
        try:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            c.close()
        os.replace(tmp, db.DB_PATH)
        for ext in ('-wal', '-shm'):
            try:
                os.remove(db.DB_PATH + ext)
            except OSError:
                pass
        db.init()
    db.log('Data restored from a backup file')
    return {'ok': True}


def autostart_get(_q, _b):
    return {'supported': winstart.supported(), 'on': winstart.is_on()}


def autostart_set(_q, b):
    try:
        on = winstart.set_on(bool(b.get('on')))
    except OSError as e:
        raise API(str(e), 400, code='autostart')
    db.log('Start with Windows turned ' + ('on' if on else 'off'))
    return {'supported': True, 'on': on}


def shutdown(_q, _b):
    if REQUIRE_LOGIN:
        raise API('Not on a server', code='server_mode')
    db.log('Stopped from the dashboard')
    threading.Timer(0.5, lambda: HTTPD and HTTPD.shutdown()).start()
    return {'ok': True}


ROUTES = [
    ('GET', r'/api/badges', badges), ('GET', r'/api/today', today), ('GET', r'/api/overview', today),
    ('GET', r'/api/leads', leads_list), ('GET', r'/api/leads/(\d+)', lead_get), ('POST', r'/api/leads', lead_add),
    ('PATCH', r'/api/leads/(\d+)', lead_edit), ('PATCH', r'/api/leads/(\d+)/deal', lead_deal), ('POST', r'/api/leads/(\d+)/notes', note_add),
    ('DELETE', r'/api/notes/(\d+)', note_delete), ('POST', r'/api/leads/delete', leads_delete), ('POST', r'/api/leads/check', leads_check),
    ('POST', r'/api/leads/verify', leads_verify), ('POST', r'/api/leads/import', leads_import), ('POST', r'/api/leads/paste', leads_paste),
    ('POST', r'/api/import/preview', import_preview), ('POST', r'/api/import/commit', import_commit), ('GET', r'/api/pipeline', pipeline),
    ('POST', r'/api/search', search), ('GET', r'/api/searches', searches), ('POST', r'/api/searches/(\d+)/cancel', search_cancel),
    ('POST', r'/api/search/suggest', search_suggest), ('GET', r'/api/jobs', jobs),
    ('GET', r'/api/campaigns', campaigns_list), ('POST', r'/api/campaigns', campaign_add), ('GET', r'/api/campaigns/(\d+)', campaign_get),
    ('PATCH', r'/api/campaigns/(\d+)', campaign_edit), ('DELETE', r'/api/campaigns/(\d+)', campaign_delete),
    ('POST', r'/api/campaigns/(\d+)/duplicate', campaign_duplicate), ('POST', r'/api/campaigns/(\d+)/enroll', campaign_enroll),
    ('POST', r'/api/campaigns/(\d+)/preview', campaign_preview),
    ('GET', r'/api/messages', messages_list), ('PATCH', r'/api/messages/(\d+)', message_edit), ('POST', r'/api/messages/approve', messages_approve),
    ('POST', r'/api/messages/reject', messages_reject), ('POST', r'/api/messages/(\d+)/rewrite', message_rewrite),
    ('POST', r'/api/messages/retry', messages_retry), ('POST', r'/api/messages/(\d+)/test', message_test), ('POST', r'/api/send-now', send_now), ('GET', r'/api/forecast', forecast),
    ('GET', r'/api/inbox', inbox_list), ('GET', r'/api/inbox/(\d+)', inbox_thread), ('POST', r'/api/inbox/(\d+)/draft', inbox_draft),
    ('POST', r'/api/inbox/(\d+)/send', inbox_send), ('POST', r'/api/inbox/(\d+)/done', lead_replies_handled), ('POST', r'/api/inbox/check', inbox_check),
    ('GET', r'/api/replies', replies_list), ('POST', r'/api/replies/(\d+)/handled', reply_handled), ('POST', r'/api/replies/(\d+)/forward', reply_forward),
    ('GET', r'/api/files', files_list), ('DELETE', r'/api/files/(\d+)', file_delete), ('GET', r'/api/reports', reports),
    ('GET', r'/api/settings', settings_get), ('POST', r'/api/settings', settings_save), ('POST', r'/api/setup/done', setup_done),
    ('POST', r'/api/settings/password', set_password), ('POST', r'/api/test/smtp', test_smtp), ('POST', r'/api/test/imap', test_imap),
    ('POST', r'/api/test/ai', test_ai), ('POST', r'/api/test/places', test_places), ('GET', r'/api/check/domain', check_domain),
    ('POST', r'/api/sending', sending), ('GET', r'/api/log', log_list),
    ('GET', r'/api/suppression', suppression_list), ('POST', r'/api/suppression', suppression_add), ('POST', r'/api/suppression/remove', suppression_remove),
    ('GET', r'/api/backups', backups_list), ('POST', r'/api/shutdown', shutdown),
    ('GET', r'/api/autostart', autostart_get), ('POST', r'/api/autostart', autostart_set),
]


class Handler(BaseHTTPRequestHandler):
    server_version = 'RAXSurgicalsOutreach'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json', headers=None, cache='no-store'):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str).encode() if ctype == 'application/json' else body.encode())
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith(('text', 'application/json')) else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def _session(self):
        m = re.search(r'(?:^|;\s*)rax_s=([A-Za-z0-9_-]+)', self.headers.get('Cookie', ''))
        tok = m and m.group(1)
        exp = SESSIONS.get(tok) if tok else None
        return tok if exp and exp > time.time() else None

    def _auth_needed(self):
        return REQUIRE_LOGIN or bool(db.get('admin_password_hash'))

    def _read_body(self, path):
        """Reads the whole request body first, so a refused request never leaves bytes behind on a kept-alive connection."""
        limit = 500_000_000 if path == '/api/restore' else 15_000_000 if path == '/api/files' else 40_000_000
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        if n > limit:
            self.close_connection = True
            raise API('The file is too large', 413, code='too_large')
        return self.rfile.read(n) if n > 0 else b''

    @staticmethod
    def _json(raw):
        try:
            return json.loads(raw.decode() or '{}') if raw else {}
        except ValueError:
            raise API('Bad request', 400, code='bad_request')

    def handle_any(self, method):
        path, _, query = self.path.partition('?')
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        try:
            raw = self._read_body(path) if method in ('POST', 'PATCH', 'DELETE', 'PUT') else b''
            if not path.startswith('/api/'):
                if method not in ('GET', 'HEAD'): raise API('Not found', 404)
                return self.static(path)
            if path == '/api/me':
                # 'app' is how the launcher and setup recognise a running copy: it keeps the name from before 2.2
                return self._send(200, {'app': 'RAX Outreach', 'name': db.NAME, 'auth_required': self._auth_needed(), 'logged_in': bool(self._session()) or not self._auth_needed(),
                                        'password_set': bool(db.get('admin_password_hash')), 'version': db.VERSION,
                                        'lang': 'en', 'setup_done': db.get('setup_done') == '1', 'server_mode': REQUIRE_LOGIN,
                                        'installed': bool(os.environ.get('RAX_LAUNCHER'))})
            stop = self.headers.get('X-RAX-Stop') or ''
            if path == '/api/shutdown' and method == 'POST' and stop and hmac.compare_digest(stop.encode(), STOP_TOKEN.encode()):
                db.log('Stopped by the installer')
                threading.Timer(0.3, lambda: HTTPD and HTTPD.shutdown()).start()
                return self._send(200, {'ok': True})
            if method != 'GET' and self.headers.get('X-Requested-With') != 'rax':
                raise API('Bad request', 400, code='bad_request')
            if path == '/api/login':
                return self.login(self._json(raw))
            if path == '/api/logout':
                SESSIONS.pop(self._session(), None)
                return self._send(200, {'ok': True}, headers={'Set-Cookie': 'rax_s=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict'})
            if self._auth_needed() and not self._session():
                raise API('Please log in', 401, code='login')
            # downloads and uploads
            if path == '/api/leads/export.csv':
                rows = db.q(f'SELECT {LEAD_COLS} FROM leads ORDER BY id')
                return self._send(200, finder.export_csv(rows), 'text/csv', {'Content-Disposition': 'attachment; filename="rax-leads.csv"'})
            if path == '/api/backup' and method == 'GET':
                p = db.backup(os.path.join(db.BACKUP_DIR, f'manual-{dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")}.db'))
                with open(p, 'rb') as fh:
                    data = fh.read()
                return self._send(200, data, 'application/octet-stream', {'Content-Disposition': f'attachment; filename="{os.path.basename(p)}"'})
            if path == '/api/restore' and method == 'POST':
                return self._send(200, restore(raw))
            m = re.fullmatch(r'/api/files/(\d+)/download', path)
            if m and method == 'GET':
                f = db.q('SELECT * FROM files WHERE id=?', (int(m.group(1)),), one=True)
                if not f: raise API('Not found', 404)
                with open(os.path.join(db.FILES_DIR, f['stored']), 'rb') as fh:
                    data = fh.read()
                return self._send(200, data, f['mime'] or 'application/octet-stream',
                                  {'Content-Disposition': "attachment; filename*=UTF-8''" + urllib.parse.quote(f['name'])})
            if path == '/api/files' and method == 'POST':
                data = raw
                if not data: raise API('The file is empty', code='empty_file')
                name = urllib.parse.unquote(self.headers.get('X-File-Name') or 'file')
                mime = (self.headers.get('Content-Type') or 'application/octet-stream').split(';')[0]
                if mime == 'application/json': mime = 'application/octet-stream'
                return self._send(200, {'id': save_upload(name, data, mime)})
            body = self._json(raw) if method in ('POST', 'PATCH', 'DELETE') else {}
            for mth, pat, fn in ROUTES:
                if mth != method: continue
                m = re.fullmatch(pat, path)
                if m:
                    args = [int(g) for g in m.groups()]
                    return self._send(200, fn(qs, body, *args))
            raise API('Not found', 404)
        except API as e:
            out = {'error': str(e)}
            if e.code: out['code'] = e.code
            if e.data is not None: out['data'] = e.data
            self._send(e.http, out)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa
            db.log(f'{method} {path}: {e}', 'error')
            try:
                self._send(500, {'error': f'Something went wrong: {e}', 'code': 'server_error'})
            except Exception:
                pass

    def login(self, b):
        ip = self.client_address[0]
        if ip == '127.0.0.1' and self.headers.get('X-Forwarded-For'):
            ip = self.headers['X-Forwarded-For'].split(',')[-1].strip()
        fails = [t for t in LOGIN_FAILS.get(ip, []) if t > time.time() - 900]
        if len(fails) >= 8: raise API('Too many wrong passwords. Wait 15 minutes.', 429, code='pw_locked')
        stored = db.get('admin_password_hash')
        if not stored: raise API('No password has been set yet. Run: python start.py --set-password', 400, code='pw_none')
        if not check_pw(b.get('password') or '', stored):
            LOGIN_FAILS[ip] = fails + [time.time()]; time.sleep(0.6)
            raise API('Wrong password', 401, code='pw_wrong')
        tok = secrets.token_urlsafe(32)
        SESSIONS[tok] = time.time() + 14 * 86400
        secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' else ''
        return self._send(200, {'ok': True}, headers={'Set-Cookie': f'rax_s={tok}; Max-Age={14 * 86400}; Path=/; HttpOnly; SameSite=Strict{secure}'})

    def static(self, path):
        if path in ('/', ''): path = '/index.html'
        full = os.path.normpath(os.path.join(STATIC, urllib.parse.unquote(path).lstrip('/')))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            if os.path.splitext(path)[1]:            # a missing file (not a page address): say so
                raise API('Not found', 404)
            full = os.path.join(STATIC, 'index.html')
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, 'application/octet-stream')
        cache = 'max-age=604800' if ext in ('.woff2', '.png', '.ico', '.svg') else 'no-cache'
        with open(full, 'rb') as f:
            self._send(200, f.read(), ctype, cache=cache)

    def do_GET(self): self.handle_any('GET')
    def do_HEAD(self): self.handle_any('HEAD')
    def do_POST(self): self.handle_any('POST')
    def do_PATCH(self): self.handle_any('PATCH')
    def do_DELETE(self): self.handle_any('DELETE')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows "reuse address" lets a second program take the same port, so a second copy could start next to the
    # first one. There the port is claimed exclusively instead.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(host, port, require_login):
    global REQUIRE_LOGIN, HTTPD
    REQUIRE_LOGIN = require_login
    db.init()
    HTTPD = Server((host, port), Handler)   # claim the port first: if it is taken, nothing else has started yet
    try:
        with open(os.path.join(db.DATA_DIR, 'stop.token'), 'w') as f:
            f.write(STOP_TOKEN)
    except OSError:
        pass
    finder.recover_searches()
    worker.start()
    return HTTPD
