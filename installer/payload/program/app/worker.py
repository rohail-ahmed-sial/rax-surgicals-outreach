"""The background worker. Every 20 seconds it:
1. writes the next email for leads whose turn has come (AI or template) and puts it in the approval queue,
2. sends ONE approved email if today's limit, the gap between emails and the recipient's office hours allow,
3. every 10 minutes reads the inbox for replies and bounces,
4. once a day keeps a backup copy of the database.
Safety: a warm-up limit that grows week by week, a check that the recipient's domain takes email, and an automatic
pause when too many emails bounce."""
import os, threading, time, random, datetime as dt
from zoneinfo import ZoneInfo
from . import db, ai, mailer, dnscheck

COUNTRY_TZ = {
    'united states': 'America/New_York', 'usa': 'America/New_York', 'us': 'America/New_York', 'canada': 'America/Toronto',
    'mexico': 'America/Mexico_City', 'brazil': 'America/Sao_Paulo', 'argentina': 'America/Argentina/Buenos_Aires',
    'chile': 'America/Santiago', 'colombia': 'America/Bogota', 'peru': 'America/Lima',
    'united kingdom': 'Europe/London', 'uk': 'Europe/London', 'england': 'Europe/London', 'ireland': 'Europe/Dublin',
    'germany': 'Europe/Berlin', 'deutschland': 'Europe/Berlin', 'austria': 'Europe/Vienna', 'switzerland': 'Europe/Zurich',
    'france': 'Europe/Paris', 'belgium': 'Europe/Brussels', 'netherlands': 'Europe/Amsterdam', 'luxembourg': 'Europe/Luxembourg',
    'italy': 'Europe/Rome', 'spain': 'Europe/Madrid', 'portugal': 'Europe/Lisbon', 'poland': 'Europe/Warsaw',
    'czech republic': 'Europe/Prague', 'czechia': 'Europe/Prague', 'hungary': 'Europe/Budapest', 'romania': 'Europe/Bucharest',
    'greece': 'Europe/Athens', 'sweden': 'Europe/Stockholm', 'norway': 'Europe/Oslo', 'denmark': 'Europe/Copenhagen',
    'finland': 'Europe/Helsinki', 'turkey': 'Europe/Istanbul', 'türkiye': 'Europe/Istanbul', 'russia': 'Europe/Moscow',
    'ukraine': 'Europe/Kyiv', 'saudi arabia': 'Asia/Riyadh', 'united arab emirates': 'Asia/Dubai', 'uae': 'Asia/Dubai',
    'qatar': 'Asia/Qatar', 'kuwait': 'Asia/Kuwait', 'oman': 'Asia/Muscat', 'bahrain': 'Asia/Bahrain', 'iran': 'Asia/Tehran',
    'iraq': 'Asia/Baghdad', 'jordan': 'Asia/Amman', 'egypt': 'Africa/Cairo', 'israel': 'Asia/Jerusalem',
    'pakistan': 'Asia/Karachi', 'india': 'Asia/Kolkata', 'bangladesh': 'Asia/Dhaka', 'sri lanka': 'Asia/Colombo',
    'china': 'Asia/Shanghai', 'hong kong': 'Asia/Hong_Kong', 'japan': 'Asia/Tokyo', 'south korea': 'Asia/Seoul',
    'korea': 'Asia/Seoul', 'singapore': 'Asia/Singapore', 'malaysia': 'Asia/Kuala_Lumpur', 'indonesia': 'Asia/Jakarta',
    'thailand': 'Asia/Bangkok', 'vietnam': 'Asia/Ho_Chi_Minh', 'philippines': 'Asia/Manila',
    'australia': 'Australia/Sydney', 'new zealand': 'Pacific/Auckland', 'south africa': 'Africa/Johannesburg',
    'nigeria': 'Africa/Lagos', 'kenya': 'Africa/Nairobi', 'morocco': 'Africa/Casablanca', 'algeria': 'Africa/Algiers',
    'tunisia': 'Africa/Tunis', 'ghana': 'Africa/Accra',
}
_draft_lock = threading.RLock()   # one writer at a time, so a lead never gets two drafts
_send_lock = threading.Lock()     # one sender at a time, so an email is never sent twice
STOP_LEAD = ('replied', 'not_interested', 'unsubscribed', 'bounced', 'rejected')


def _std_offset(name):
    """Standard-time UTC offset, used only if the computer has no time-zone database (Windows without tzdata)."""
    special = {'Asia/Kolkata': 5.5, 'Asia/Colombo': 5.5, 'Asia/Tehran': 3.5, 'Asia/Karachi': 5, 'Asia/Dhaka': 6, 'Asia/Dubai': 4,
               'Asia/Muscat': 4, 'Europe/London': 0, 'Europe/Dublin': 0, 'Europe/Lisbon': 0, 'Africa/Casablanca': 1, 'Africa/Accra': 0,
               'Europe/Istanbul': 3, 'Europe/Moscow': 3, 'Asia/Riyadh': 3, 'Asia/Qatar': 3, 'Asia/Kuwait': 3, 'Asia/Bahrain': 3,
               'Asia/Baghdad': 3, 'Asia/Amman': 3, 'Africa/Nairobi': 3, 'Europe/Athens': 2, 'Europe/Bucharest': 2, 'Europe/Helsinki': 2,
               'Europe/Kyiv': 2, 'Africa/Cairo': 2, 'Asia/Jerusalem': 2, 'Africa/Johannesburg': 2, 'Asia/Shanghai': 8, 'Asia/Hong_Kong': 8,
               'Asia/Singapore': 8, 'Asia/Kuala_Lumpur': 8, 'Asia/Manila': 8, 'Asia/Tokyo': 9, 'Asia/Seoul': 9, 'Asia/Jakarta': 7,
               'Asia/Bangkok': 7, 'Asia/Ho_Chi_Minh': 7, 'Australia/Sydney': 10, 'Pacific/Auckland': 12, 'America/New_York': -5,
               'America/Toronto': -5, 'America/Mexico_City': -6, 'America/Sao_Paulo': -3, 'America/Argentina/Buenos_Aires': -3,
               'America/Santiago': -4, 'America/Bogota': -5, 'America/Lima': -5, 'Africa/Lagos': 1, 'Africa/Algiers': 1, 'Africa/Tunis': 1}
    return special.get(name, 1 if name.startswith('Europe/') else 0)


def zone(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return dt.timezone(dt.timedelta(hours=_std_offset(name)))


def tz_for(country):
    name = COUNTRY_TZ.get((country or '').strip().lower())
    return zone(name) if name else dt.timezone.utc


def my_tz():
    return zone(db.get('my_timezone') or 'Asia/Karachi')


def in_office_hours(country, when=None):
    when = when or dt.datetime.now(dt.timezone.utc)
    local = when.astimezone(tz_for(country))
    if db.get('send_weekdays_only') == '1' and local.weekday() >= 5:
        return False
    return db.get_int('send_hour_start', 9) <= local.hour < db.get_int('send_hour_end', 17)


def next_open(country, start=None):
    """The first moment at or after `start` when it is office time in that country (None if never, e.g. hours set to 0-0)."""
    t = (start or utcnow()).astimezone(dt.timezone.utc)
    if in_office_hours(country, t):
        return t
    t = t.replace(minute=0, second=0, microsecond=0)
    for _ in range(24 * 8):
        t += dt.timedelta(hours=1)
        if in_office_hours(country, t):
            return t
    return None


def parse(t):
    return dt.datetime.fromisoformat(t) if t else None


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def day_start_utc(days_ago=0):
    """Midnight of today (or an earlier day) in the user's own time zone, as UTC text for comparing with stored times."""
    local = utcnow().astimezone(my_tz()).replace(hour=0, minute=0, second=0) - dt.timedelta(days=days_ago)
    return local.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


# ---------- limits ----------
def effective_limit():
    """Today's limit: the daily limit, but while warming up a new mailbox it starts low and grows every week."""
    limit = db.get_int('daily_limit', 30)
    if db.get('warmup_on') != '1':
        return {'limit': limit, 'warmup': False}
    start, step, every = db.get_int('warmup_start', 10), db.get_int('warmup_step', 5), max(1, db.get_int('warmup_every_days', 7))
    began = db.get('warmup_started') or ''
    try:
        days = (dt.date.today() - dt.date.fromisoformat(began)).days if began else 0
    except ValueError:
        days = 0
    week = days // every
    warm = start + step * week
    if warm >= limit:
        return {'limit': limit, 'warmup': False, 'week': week + 1}
    return {'limit': max(1, warm), 'warmup': True, 'week': week + 1, 'full': limit}


def sent_today():
    return db.q("SELECT COUNT(*) n FROM messages WHERE status='sent' AND COALESCE(kind,'campaign')='campaign' AND sent_at>=?",
                (day_start_utc(),), one=True)['n']


def pause(reason, text):
    db.put('sending_paused', '1')
    db.put('paused_reason', reason)
    db.log(text, 'error')


def bounce_guard():
    """Pause sending when too many of the recent emails bounced: protects the mailbox's reputation."""
    if db.get('bounce_guard_on') != '1' or db.get('sending_paused') == '1':
        return False
    recent = db.q("SELECT id, lead_id FROM messages WHERE status IN ('sent','failed') AND COALESCE(kind,'campaign')='campaign' "
                  "AND (sent_at IS NOT NULL OR error LIKE 'Address does not exist%') ORDER BY id DESC LIMIT 50")
    if len(recent) < 20:
        return False
    ids = [r['id'] for r in recent]
    leads = list({r['lead_id'] for r in recent})
    marks = ','.join('?' * len(leads))
    bounced = db.q(f"SELECT COUNT(DISTINCT lead_id) n FROM replies WHERE kind='bounce' AND lead_id IN ({marks})", leads, one=True)['n']
    refused = db.q(f"SELECT COUNT(*) n FROM messages WHERE error LIKE 'Address does not exist%' AND id IN ({','.join('?' * len(ids))})", ids, one=True)['n']
    rate = 100.0 * (bounced + refused) / len(recent)
    if rate > db.get_float('bounce_guard_pct', 5):
        pause('bounces', f'Sending paused: {bounced + refused} of the last {len(recent)} emails bounced ({rate:.0f}%). '
                         'Check the email addresses of your leads before you resume.')
        return True
    return False


# ---------- adding leads to a campaign ----------
def enroll(campaign_id, lead_ids):
    added, skipped = 0, []
    for lid in lead_ids:
        lead = db.q('SELECT * FROM leads WHERE id=?', (lid,), one=True)
        if not lead:
            continue
        why = None
        if not lead['email']: why = 'no_email'
        elif lead.get('email_status') == 'no_mx': why = 'no_mail_server'
        elif db.suppressed(lead['email']): why = 'do_not_email'
        elif lead['status'] in STOP_LEAD: why = lead['status']
        elif db.q("SELECT 1 FROM enrollments WHERE lead_id=? AND status IN ('active','waiting')", (lid,), one=True): why = 'in_other_campaign'
        elif db.q('SELECT 1 FROM enrollments WHERE lead_id=? AND campaign_id=?', (lid, campaign_id), one=True): why = 'in_this_campaign'
        if why:
            skipped.append({'company': lead['company'], 'why': why})
            continue
        db.x('INSERT INTO enrollments(campaign_id, lead_id, step, status, next_due, created_at) VALUES (?,?,?,?,?,?)',
             (campaign_id, lid, 0, 'active', db.now(), db.now()))
        db.x("UPDATE leads SET status='in_campaign', updated_at=? WHERE id=?", (db.now(), lid))
        added += 1
    return {'added': added, 'skipped': skipped}


# ---------- writing drafts ----------
def write_for(enr, note=''):
    with _draft_lock:
        cur = db.q('SELECT * FROM enrollments WHERE id=?', (enr['id'],), one=True)
        if not cur or cur['status'] != 'active':
            return None
        return _write_for(cur, note)


def _write_for(enr, note=''):
    lead = db.q('SELECT * FROM leads WHERE id=?', (enr['lead_id'],), one=True)
    camp = db.q('SELECT * FROM campaigns WHERE id=?', (enr['campaign_id'],), one=True)
    if camp and note:
        camp = dict(camp, instructions=(camp['instructions'] or '') + '\nFor this email only: ' + note)
    if not lead or not camp:
        db.x("UPDATE enrollments SET status='stopped' WHERE id=?", (enr['id'],)); return None
    if lead['status'] in STOP_LEAD or not lead['email'] or db.suppressed(lead['email']):
        db.x("UPDATE enrollments SET status='stopped' WHERE id=?", (enr['id'],)); return None
    steps = db.jloads(camp['steps'], [])
    if enr['step'] >= len(steps):
        db.x("UPDATE enrollments SET status='done' WHERE id=?", (enr['id'],)); return None
    step = steps[enr['step']]
    history = db.q("SELECT subject, body FROM messages WHERE enrollment_id=? AND status='sent' AND COALESCE(kind,'campaign')='campaign' ORDER BY step", (enr['id'],))
    out, by = None, 'template'
    if step.get('kind', 'ai') == 'ai' and ai.available():
        try:
            out = ai.write_email(lead, camp, enr['step'], step, history); by = 'ai'
        except ai.NoAI as e:
            db.log(str(e), 'warn')
        except Exception as e:  # noqa
            db.log(f"AI could not write for {lead['company']}: {e}", 'error')
    if out is None:
        if not (step.get('body') or '').strip():
            if not ai.available():
                db.log(f"Campaign '{camp['name']}' email {enr['step'] + 1} has no template text and no AI key is set.", 'warn')
            db.x('UPDATE enrollments SET next_due=? WHERE id=?', ((utcnow() + dt.timedelta(hours=1)).isoformat(), enr['id']))
            return None
        sname = db.get('sender_name')
        out = {'subject': ai.fill_template(step.get('subject') or '', lead, sname), 'body': ai.fill_template(step['body'], lead, sname)}
    if enr['step'] > 0 and enr['thread_subject']:
        s = enr['thread_subject']
        out['subject'] = s if s.lower().startswith('re:') else 'Re: ' + s
    if not out['subject']:
        out['subject'] = f"{db.get('company_name')} instruments for {lead['company']}"
    status = 'approved' if enr['step'] > 0 and camp['auto_approve_followups'] else 'draft'
    mid = db.x('''INSERT INTO messages(enrollment_id, lead_id, campaign_id, step, to_email, subject, body, status, in_reply_to, written_by, kind, created_at, approved_at)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               (enr['id'], lead['id'], camp['id'], enr['step'], lead['email'], out['subject'], out['body'], status,
                enr['first_message_id'] if enr['step'] > 0 else None, by, 'campaign', db.now(), db.now() if status == 'approved' else None))
    db.x("UPDATE enrollments SET status='waiting' WHERE id=?", (enr['id'],))
    return mid


def draft_tick(limit=5):
    due = db.q('''SELECT e.* FROM enrollments e JOIN campaigns c ON c.id=e.campaign_id
                  WHERE e.status='active' AND c.active=1 AND e.next_due<=? ORDER BY e.next_due LIMIT ?''', (db.now(), limit))
    return sum(1 for e in due if write_for(e))


# ---------- sending ----------
def send_tick(force_now=False):
    with _send_lock:
        return _send_tick(force_now)


def _send_tick(force_now=False):
    if db.get('sending_paused') == '1':
        return 'paused'
    if sent_today() >= effective_limit()['limit']:
        return 'daily limit reached'
    nxt = parse(db.get('next_send_at') or '')
    if nxt and utcnow() < nxt and not force_now:
        return 'waiting for gap'
    rows = db.q('''SELECT m.*, l.country, l.status AS lead_status, l.domain AS lead_domain FROM messages m JOIN leads l ON l.id=m.lead_id
                   WHERE m.status='approved' AND COALESCE(m.kind,'campaign')='campaign' ORDER BY m.step DESC, m.approved_at LIMIT 200''')
    for m in rows:
        if m['lead_status'] in STOP_LEAD or db.suppressed(m['to_email']):
            db.x("UPDATE messages SET status='cancelled', error='lead stopped' WHERE id=?", (m['id'],)); continue
        if not in_office_hours(m['country']):
            continue
        if m['step'] == 0 and db.get('mx_check_on') == '1':
            ok = dnscheck.mx_ok(m['to_email'].split('@')[-1])
            if ok is False:
                db.x("UPDATE messages SET status='failed', error=? WHERE id=?", ('no_mail_server: the domain of this address does not accept email', m['id']))
                db.x("UPDATE leads SET status='bounced', email_status='no_mx', updated_at=? WHERE id=?", (db.now(), m['lead_id']))
                mailer.stop_lead(m['lead_id'], 'bounced')
                db.log(f"Not sent to {m['to_email']}: that domain does not accept email", 'warn')
                continue
        try:
            msgid = mailer.send(m)
        except mailer.ConfigError as e:
            pause(e.code if e.code == 'provider_limit' else 'config', f'Sending paused: {e} Fix it in Settings, then press Resume.')
            return 'failed'
        except mailer.RecipientRefused as e:
            db.x("UPDATE messages SET status='failed', error=? WHERE id=?", (f'Address does not exist: {e}'[:300], m['id']))
            db.suppress(m['to_email'], 'bounce')
            db.x("UPDATE leads SET status='bounced', updated_at=? WHERE id=?", (db.now(), m['lead_id']))
            mailer.stop_lead(m['lead_id'], 'bounced')
            db.log(f"{m['to_email']} does not exist (refused by their server); lead marked bounced", 'warn')
            bounce_guard()
            return 'failed'
        except Exception as e:  # noqa
            err = str(e)[:300]
            db.x("UPDATE messages SET status='failed', error=? WHERE id=?", (err, m['id']))
            db.log(f"Sending to {m['to_email']} failed: {err}", 'error')
            return 'failed'
        finish_send(m, msgid)
        gmin = db.get_float('gap_min_minutes', 3)
        gap = random.uniform(gmin, max(gmin, db.get_float('gap_max_minutes', 8)))
        db.put('next_send_at', (utcnow() + dt.timedelta(minutes=gap)).isoformat())
        return 'sent'
    return 'nothing to send now'


def finish_send(m, msgid):
    db.x("UPDATE messages SET status='sent', message_id=?, sent_at=?, error=NULL WHERE id=?", (msgid, db.now(), m['id']))
    db.x('UPDATE leads SET last_contact_at=? WHERE id=?', (db.now(), m['lead_id']))
    if not db.get('warmup_started'):
        db.put('warmup_started', dt.date.today().isoformat())
    enr = db.q('SELECT * FROM enrollments WHERE id=?', (m['enrollment_id'],), one=True)
    camp = db.q('SELECT steps FROM campaigns WHERE id=?', (m['campaign_id'],), one=True)
    steps = db.jloads(camp['steps'] if camp else '[]', [])
    if enr:
        if m['step'] == 0:
            db.x('UPDATE enrollments SET first_message_id=?, thread_subject=? WHERE id=?', (msgid, m['subject'], enr['id']))
        nxt = m['step'] + 1
        if nxt < len(steps):
            days = max(1, int(steps[nxt].get('day', 3)) - int(steps[m['step']].get('day', 0)))
            db.x("UPDATE enrollments SET step=?, status='active', next_due=? WHERE id=?",
                 (nxt, (utcnow() + dt.timedelta(days=days)).isoformat(), enr['id']))
        else:
            db.x("UPDATE enrollments SET step=?, status='done' WHERE id=?", (nxt, enr['id']))
    db.log(f"Sent email {m['step'] + 1} to {m['to_email']}")


def finish_sequences():
    """Leads whose last follow-up went out 7+ days ago without a reply become 'no reply'."""
    old = (utcnow() - dt.timedelta(days=7)).isoformat()
    db.x('''UPDATE leads SET status='no_reply', updated_at=? WHERE status='in_campaign' AND id IN (
              SELECT e.lead_id FROM enrollments e WHERE e.status='done' AND NOT EXISTS (
                SELECT 1 FROM messages m WHERE m.enrollment_id=e.id AND m.sent_at>?))''', (db.now(), old))


def forecast():
    """When will queued emails go out? Per country: how many are waiting, is it office time there now, when it opens."""
    now = utcnow()
    rows = db.q('''SELECT l.country, COUNT(*) n FROM messages m JOIN leads l ON l.id=m.lead_id
                   WHERE m.status='approved' AND COALESCE(m.kind,'campaign')='campaign' GROUP BY l.country ORDER BY n DESC''')
    lim = effective_limit()
    earliest = now
    nxt = parse(db.get('next_send_at') or '')
    if nxt and nxt > earliest:
        earliest = nxt
    if sent_today() >= lim['limit']:
        earliest = max(earliest, parse(day_start_utc(-1)))
    countries, best = [], None
    for r in rows:
        tz = tz_for(r['country'])
        opens = next_open(r['country'], earliest)
        local_now = now.astimezone(tz)
        countries.append({'country': r['country'] or '', 'queued': r['n'], 'open_now': in_office_hours(r['country'], now),
                          'local_time': local_now.strftime('%H:%M'), 'local_day': local_now.strftime('%a'),
                          'opens_at': opens.isoformat() if opens else None})
        if opens and (best is None or opens < best):
            best = opens
    return {'next_send': best.isoformat() if best and db.get('sending_paused') != '1' else None, 'countries': countries}


def markets(limit=6):
    """Countries to show on the office-hours band: where emails are waiting first, then where most leads are."""
    now = utcnow()
    queued = {(r['country'] or ''): r['n'] for r in db.q(
        "SELECT l.country, COUNT(*) n FROM messages m JOIN leads l ON l.id=m.lead_id "
        "WHERE m.status='approved' AND m.kind='campaign' GROUP BY l.country")}
    tops = [r['country'] for r in db.q(
        "SELECT country, COUNT(*) n FROM leads WHERE COALESCE(country,'')<>'' "
        "AND status NOT IN ('rejected','bounced','unsubscribed') GROUP BY country ORDER BY n DESC LIMIT 20")]
    out = []
    for c in dict.fromkeys([c for c in queued if c] + tops):
        if (c or '').strip().lower() not in COUNTRY_TZ:
            continue
        local = now.astimezone(tz_for(c))
        out.append({'country': c, 'local_time': local.strftime('%H:%M'), 'local_day': local.strftime('%a'),
                    'open_now': in_office_hours(c, now), 'queued': queued.get(c, 0)})
        if len(out) >= limit:
            break
    return out


# ---------- loop ----------
_started = False


def loop():
    last_inbox = 0
    while True:
        try:
            draft_tick()
            send_tick()
            finish_sequences()
            if db.get('imap_host') and time.time() - last_inbox > 600 and db.q("SELECT 1 FROM messages WHERE status='sent' LIMIT 1", one=True):
                last_inbox = time.time()
                r = mailer.check_replies()
                if r.get('new'): db.log(f"Inbox: {r['new']} new replies or bounces")
        except Exception as e:  # noqa
            db.log(f'Worker: {e}', 'error')
        try:
            if db.daily_backup():
                db.log('Daily backup saved in the data/backups folder')
        except Exception as e:  # noqa
            db.log(f'Backup failed: {e}', 'warn')
        time.sleep(20)


_lock_file = None


def _only_copy():
    """True when no other running copy of RAX Surgicals Outreach sends from this data folder.
    Two copies (for example one started on another port) would otherwise send the same emails twice."""
    global _lock_file
    try:
        os.makedirs(db.DATA_DIR, exist_ok=True)
        f = open(os.path.join(db.DATA_DIR, 'sending.lock'), 'a+')
        if os.name == 'nt':
            import msvcrt
            if f.tell() == 0:
                f.write('1'); f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file = f            # kept open: the lock lasts as long as this copy runs
        return True
    except OSError:
        return False


def start():
    global _started
    if os.environ.get('RAX_NO_WORKER'):
        return
    if not _started:
        _started = True
        if not _only_copy():
            db.log('Another copy of RAX Surgicals Outreach is already running from this folder; this copy does not send or read email.', 'warn')
            return
        threading.Thread(target=loop, daemon=True).start()
