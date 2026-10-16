"""Email: sending through any mailbox with SMTP, and reading replies and bounces with IMAP (Google Workspace, Zoho,
Outlook, Hostinger or the email that comes with web hosting). Also: answering replies in the same thread,
forwarding replies to another address, attachments, and keeping a copy of sent emails in the Sent folder."""
import smtplib, imaplib, ssl, socket, email, email.policy, mimetypes, os, re, html, threading, time, datetime as dt
from email.message import EmailMessage
from email.utils import make_msgid, formataddr, formatdate, parseaddr
from email.header import decode_header, make_header
from . import db, ai

CTX = ssl.create_default_context()


class MailError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ConfigError(MailError):
    """The mailbox could not be reached or logged into: a settings problem, not a problem with one email."""


class RecipientRefused(Exception):
    """The receiving server said this address does not exist."""


def explain(e, host=''):
    """Turns a connection or login error into a short code the dashboard explains in plain words."""
    s = str(e).lower()
    host = (host or '').lower()
    google = 'gmail' in host or 'google' in host
    if isinstance(e, smtplib.SMTPAuthenticationError) or 'authenticationfailed' in s or 'invalid credentials' in s \
            or 'username and password not accepted' in s or 'authentication failed' in s or 'login failed' in s:
        if google or 'application-specific password' in s or 'badcredentials' in s:
            return 'gmail_app_password'
        return 'auth_failed'
    if 'application-specific password' in s:
        return 'gmail_app_password'
    if isinstance(e, socket.gaierror) or 'name or service not known' in s or 'getaddrinfo failed' in s or 'nodename nor servname' in s:
        return 'host_not_found'
    if isinstance(e, ssl.SSLError) or 'wrong version number' in s or 'starttls' in s or isinstance(e, smtplib.SMTPServerDisconnected):
        return 'tls_mismatch'
    if isinstance(e, ConnectionRefusedError) or 'refused' in s:
        return 'connect_refused'
    if isinstance(e, (socket.timeout, TimeoutError)) or 'timed out' in s:
        return 'timeout'
    if 'daily' in s and 'limit' in s or 'quota' in s or 'too many' in s:
        return 'provider_limit'
    return 'mail_error'


# ---------- building emails ----------
def signature():
    sig = (db.get('signature') or '').strip()
    if sig:
        return sig
    name, title = db.get('sender_name'), db.get('sender_title')
    return '\n'.join(x for x in [name, f"{title}, {db.get('company_name')}" if title else db.get('company_name'),
                                  db.get('company_website'), db.get('sender_email')] if x)


def footer(mode='cold'):
    """cold: first emails and follow-ups (with address and opt-out line, as email laws require). warm: answers."""
    parts = [signature()]
    if mode == 'cold':
        parts.append(f"{db.get('company_name')}, {db.get('company_address')}\n"
                     "If this is not relevant for you, reply \"unsubscribe\" and we will not email you again.")
    return '\n\n'.join(p for p in parts if p)


def file_rows(ids):
    ids = [int(i) for i in (ids or []) if str(i).isdigit()]
    if not ids:
        return []
    return db.q(f"SELECT * FROM files WHERE id IN ({','.join('?' * len(ids))})", ids)


def build(m, mode='cold', attachments=()):
    sender = db.get('sender_email')
    if not sender:
        raise ConfigError('no_sender', 'Set the sender email in Settings.')
    msg = EmailMessage()
    msg['From'] = formataddr((db.get('sender_name') or db.get('company_name'), sender))
    msg['To'] = m['to_email']
    msg['Subject'] = m['subject']
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = m.get('message_id') or make_msgid(domain=sender.split('@')[-1])
    if db.get('reply_to'):
        msg['Reply-To'] = db.get('reply_to')
    if m.get('in_reply_to'):
        msg['In-Reply-To'] = m['in_reply_to']
        msg['References'] = m.get('references') or m['in_reply_to']
    if mode == 'cold':
        msg['List-Unsubscribe'] = f'<mailto:{db.get("reply_to") or sender}?subject=unsubscribe>'
    tail = footer(mode) if mode in ('cold', 'warm') else ''
    msg.set_content(m['body'].rstrip() + ('\n\n' + tail if tail else '') + '\n')
    for f in attachments:
        path = os.path.join(db.FILES_DIR, f['stored'])
        with open(path, 'rb') as fh:
            data = fh.read()
        ctype = f.get('mime') or mimetypes.guess_type(f['name'])[0] or 'application/octet-stream'
        main, _, sub = ctype.partition('/')
        msg.add_attachment(data, maintype=main, subtype=sub or 'octet-stream', filename=f['name'])
    return msg


def _smtp():
    host, port, sec = db.get('smtp_host'), db.get_int('smtp_port', 587), db.get('smtp_security')
    if not host:
        raise ConfigError('no_smtp', 'Set the SMTP server in Settings.')
    try:
        if sec == 'ssl':
            s = smtplib.SMTP_SSL(host, port, timeout=30, context=CTX)
        else:
            s = smtplib.SMTP(host, port, timeout=30)
            if sec == 'starttls':
                s.starttls(context=CTX)
    except (OSError, smtplib.SMTPException) as e:
        raise ConfigError(explain(e, host), f'Could not connect to {host}:{port} ({e}).')
    if db.get('smtp_user'):
        try:
            s.login(db.get('smtp_user'), db.get('smtp_password'))
        except (OSError, smtplib.SMTPException) as e:
            try: s.close()
            except Exception: pass
            raise ConfigError(explain(e, host), f'Email login failed ({e}).')
    return s


def send_msg(msg):
    s = _smtp()
    try:
        s.send_message(msg)
    except smtplib.SMTPRecipientsRefused as e:
        raise RecipientRefused(str(e)[:300])
    except smtplib.SMTPSenderRefused as e:
        raise ConfigError(explain(e, db.get('smtp_host')), f'The mailbox refused to send: {e}')
    except smtplib.SMTPDataError as e:
        code = explain(e, db.get('smtp_host'))
        if code == 'provider_limit':
            raise ConfigError(code, f'The email provider stopped sending: {e}')
        raise MailError('rejected', f'The email was refused: {e}')
    finally:
        try: s.quit()
        except Exception: pass
    raw = msg.as_bytes()
    if should_save_copy():
        threading.Thread(target=save_copy, args=(raw,), daemon=True).start()
    return msg['Message-ID']


def send(m, mode='cold', attachments=()):
    return send_msg(build(m, mode, attachments))


def send_test(to):
    send_msg(build({'to_email': to, 'subject': 'Test email from RAX Surgicals Outreach',
                    'body': 'This is a test. If you can read this, sending works.'}, mode='warm'))


# ---------- a copy in the Sent folder ----------
def should_save_copy():
    mode = db.get('save_sent_copy')
    if mode == 'off' or not db.get('imap_host'):
        return False
    if mode == 'on':
        return True
    host = (db.get('smtp_host') or '').lower()   # Gmail and Microsoft keep a copy by themselves
    return not any(h in host for h in ('gmail', 'googlemail', 'office365', 'outlook'))


LIST_RE = re.compile(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$')


def find_sent_folder(i):
    try:
        typ, data = i.list()
    except Exception:
        return 'Sent'
    names = []
    for line in data or []:
        if not line:
            continue
        s = line.decode(errors='replace') if isinstance(line, bytes) else str(line)
        m = LIST_RE.match(s)
        if not m:
            continue
        name = m.group('name').strip().strip('"')
        if '\\sent' in m.group('flags').lower():
            return name
        names.append(name)
    for want in ('Sent', 'INBOX.Sent', 'Sent Items', 'Sent Messages', 'INBOX.Sent Items', 'Sent Mail'):
        for n in names:
            if n.lower() == want.lower():
                return n
    return 'Sent'


_imap_lock = threading.Lock()


def save_copy(raw):
    try:
        with _imap_lock:
            i = _imap()
            try:
                folder = db.get('sent_folder') or find_sent_folder(i)
                i.append('"' + folder.replace('"', '') + '"', '(\\Seen)', imaplib.Time2Internaldate(time.time()), raw)
            finally:
                try: i.logout()
                except Exception: pass
    except Exception as e:  # noqa
        db.log(f'Could not put a copy in the Sent folder: {e}', 'warn')


# ---------- answering, writing and forwarding ----------
def _thread_refs(lead_id, their_mid=None):
    """Message-IDs of the conversation with this lead, oldest first (so mail programs show one thread)."""
    ids = [r['message_id'] for r in db.q("SELECT message_id FROM messages WHERE lead_id=? AND status='sent' AND kind IN ('campaign','reply') AND message_id IS NOT NULL ORDER BY sent_at", (lead_id,))]
    ids += [r['message_id'] for r in db.q("SELECT message_id FROM replies WHERE lead_id=? AND message_id IS NOT NULL AND kind<>'bounce' ORDER BY received_at", (lead_id,))]
    if their_mid and their_mid not in ids:
        ids.append(their_mid)
    return [i for i in dict.fromkeys(ids) if i][-10:]


def send_direct(lead_id, subject, body, file_ids=(), reply_id=None, written_by='me'):
    """Send an answer (or a new email) to a lead now, in the same thread as earlier emails. Not limited by the daily limit:
    these are conversations with people who already answered."""
    lead = db.q('SELECT * FROM leads WHERE id=?', (lead_id,), one=True)
    if not lead:
        raise MailError('not_found', 'Lead not found')
    r = db.q('SELECT * FROM replies WHERE id=?', (reply_id,), one=True) if reply_id else None
    to = (r['from_email'] if r and r.get('from_email') else lead['email']) or ''
    if not to:
        raise MailError('no_email', 'This lead has no email address.')
    if db.suppressed(to) and not r:
        raise MailError('suppressed', 'This address is on the do-not-email list.')
    refs = _thread_refs(lead_id, r.get('message_id') if r else None)
    in_reply_to = (r.get('message_id') if r and r.get('message_id') else (refs[-1] if refs else None))
    files = file_rows(file_ids)
    m = {'to_email': to, 'subject': subject, 'body': body, 'in_reply_to': in_reply_to, 'references': ' '.join(refs) if refs else None}
    msgid = send(m, mode='warm', attachments=files)
    enr = db.q('SELECT id, campaign_id FROM enrollments WHERE lead_id=? ORDER BY id DESC LIMIT 1', (lead_id,), one=True)
    mid = db.x('''INSERT INTO messages(enrollment_id, lead_id, campaign_id, step, to_email, subject, body, status, message_id, in_reply_to,
                  references_hdr, written_by, kind, reply_to_id, created_at, approved_at, sent_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               (enr['id'] if enr else None, lead_id, enr['campaign_id'] if enr else None, -1, to, subject, body, 'sent', msgid,
                in_reply_to, m['references'], written_by, 'reply', reply_id, db.now(), db.now(), db.now()))
    for f in files:
        db.x('INSERT OR IGNORE INTO message_files(message_id, file_id) VALUES (?, ?)', (mid, f['id']))
    if r:
        db.x('UPDATE replies SET handled=1 WHERE id=?', (reply_id,))
    db.x('UPDATE leads SET last_contact_at=?, updated_at=? WHERE id=?', (db.now(), db.now(), lead_id))
    db.log(f"Answer sent to {to} ({lead['company']})" + (f", {len(files)} attachment(s)" if files else ''))
    return mid


def forward_reply(rid, to, note=''):
    r = db.q('SELECT * FROM replies WHERE id=?', (rid,), one=True)
    if not r:
        raise MailError('not_found', 'Reply not found')
    lead = db.q('SELECT * FROM leads WHERE id=?', (r['lead_id'],), one=True) or {}
    body = ((note.strip() + '\n\n') if note and note.strip() else '') + (
        f"New reply from a lead (forwarded by RAX Surgicals Outreach)\n\n"
        f"Company: {lead.get('company', '')}{' (' + lead['country'] + ')' if lead.get('country') else ''}\n"
        f"From: {r['from_email']}\n"
        f"Type: {(r['kind'] or '').replace('_', ' ')}\n"
        f"Summary: {r['summary'] or ''}\n\n"
        f"---------- Their email ----------\nSubject: {r['subject']}\n\n{r['body']}\n")
    msg = build({'to_email': to, 'subject': 'Fwd: ' + (r['subject'] or 'reply'), 'body': body}, mode='none')
    msgid = send_msg(msg)
    db.x('''INSERT INTO messages(lead_id, step, to_email, subject, body, status, message_id, written_by, kind, reply_to_id, created_at, sent_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (r['lead_id'], -1, to, 'Fwd: ' + (r['subject'] or ''), body, 'sent', msgid, 'forward', 'forward', rid, db.now(), db.now()))
    db.x('UPDATE replies SET forwarded_at=? WHERE id=?', (db.now(), rid))
    db.log(f"Reply from {r['from_email']} forwarded to {to}")
    return msgid


# ---------- reading the inbox ----------
def _imap():
    host, port = db.get('imap_host'), db.get_int('imap_port', 993)
    if not host:
        raise ConfigError('no_imap', 'Set the IMAP server in Settings to read replies.')
    try:
        if port == 993:
            i = imaplib.IMAP4_SSL(host, port, ssl_context=CTX, timeout=30)
        else:
            i = imaplib.IMAP4(host, port, timeout=30)
            try: i.starttls(ssl_context=CTX)
            except Exception: pass
    except Exception as e:  # noqa
        raise ConfigError(explain(e, host), f'Could not connect to {host}:{port} ({e}).')
    try:
        i.login(db.get('imap_user') or db.get('smtp_user'), db.get('imap_password') or db.get('smtp_password'))
    except Exception as e:  # noqa
        try: i.shutdown()
        except Exception: pass
        raise ConfigError(explain(e, host), f'Inbox login failed ({e}).')
    return i


def test_imap():
    i = _imap()
    try:
        typ, data = i.select(db.get('imap_folder') or 'INBOX', readonly=True)
        return int(data[0]) if typ == 'OK' else 0
    finally:
        try: i.logout()
        except Exception: pass


def _dec(v):
    try:
        return str(make_header(decode_header(v or '')))
    except Exception:
        return v or ''


def text_of(msg):
    part = msg.get_body(preferencelist=('plain', 'html')) if hasattr(msg, 'get_body') else None
    if part is None:
        return ''
    try:
        t = part.get_content()
    except Exception:
        t = (part.get_payload(decode=True) or b'').decode(errors='replace')
    if part.get_content_type() == 'text/html':
        t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', t, flags=re.S | re.I)
        t = html.unescape(re.sub(r'<br\s*/?>|</p>|</div>', '\n', t, flags=re.I))
        t = re.sub(r'<[^>]+>', '', t)
    return t


def strip_quote(t):
    out = []
    for line in t.splitlines():
        if re.match(r'^\s*>', line) or re.match(r'^\s*(On .{5,200} wrote:|Am .{5,200} schrieb|Le .{5,200} a écrit|El .{5,200} escribió|-----\s*Original Message|From: .+@)', line, re.I):
            break
        out.append(line)
    return '\n'.join(out).strip()


BOUNCE_FROM = re.compile(r'mailer-daemon|postmaster|mail delivery', re.I)
BOUNCE_SUBJ = re.compile(r'undeliver|delivery status|delivery fail|failure notice|returned mail|could not be delivered|nicht zustellbar', re.I)
FREE = ('gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'icloud.com', 'live.com')


def check_replies(days=14):
    """Look at the last `days` of the inbox and record replies and bounces for emails we sent."""
    sent = db.q("SELECT id, enrollment_id, lead_id, to_email, message_id FROM messages WHERE status='sent' AND COALESCE(kind,'campaign')<>'forward'")
    if not sent:
        return {'new': 0}
    by_mid = {r['message_id'].strip('<>'): r for r in sent if r['message_id']}
    by_addr = {}
    for r in sent:
        by_addr.setdefault((r['to_email'] or '').lower(), r)
    me = (db.get('sender_email') or '').lower()
    i = _imap()
    new = 0
    try:
        i.select(db.get('imap_folder') or 'INBOX', readonly=True)
        since = (dt.date.today() - dt.timedelta(days=days)).strftime('%d-%b-%Y')
        typ, data = i.search(None, 'SINCE', since)
        ids = data[0].split()[-300:] if typ == 'OK' and data and data[0] else []
        for num in ids:
            typ, parts = i.fetch(num, '(BODY.PEEK[])')
            if typ != 'OK' or not parts or not isinstance(parts[0], tuple):
                continue
            msg = email.message_from_bytes(parts[0][1], policy=email.policy.default)
            their_mid = (msg.get('Message-ID') or '').strip() or None
            key = their_mid or f"{msg.get('Date')}|{msg.get('From')}|{msg.get('Subject')}"
            if db.q('SELECT 1 FROM replies WHERE msg_key=?', (key,), one=True):
                continue
            frm = parseaddr(msg.get('From', ''))[1].lower()
            if frm == me:
                continue
            subject = _dec(msg.get('Subject'))
            body = text_of(msg)
            refs = re.findall(r'<([^>]+)>', (msg.get('In-Reply-To') or '') + ' ' + (msg.get('References') or ''))
            hit = next((by_mid[r] for r in refs if r in by_mid), None)
            bounce = bool(BOUNCE_FROM.search(msg.get('From', '')) or BOUNCE_SUBJ.search(subject))
            if bounce:
                hit = hit or next((by_addr[a] for a in by_addr if a and a in body.lower()), None)
                if not hit:
                    continue
                record(hit, key, frm, subject, body[:3000], {'kind': 'bounce', 'summary': 'Email could not be delivered to ' + hit['to_email']}, their_mid)
                new += 1
                continue
            if not hit:
                hit = by_addr.get(frm)
                if not hit:   # same company, different person (same domain)
                    dom = frm.split('@')[-1]
                    hit = next((r for a, r in by_addr.items() if a.split('@')[-1] == dom and dom not in FREE), None)
            if not hit:
                continue
            clean = strip_quote(body)[:4000]
            try:
                c = ai.classify_reply(subject, clean) if ai.available() else ai.classify_reply_rules(subject, clean)
            except Exception:
                c = ai.classify_reply_rules(subject, clean)
            record(hit, key, frm, subject, clean, c, their_mid)
            new += 1
    finally:
        try: i.logout()
        except Exception: pass
    db.put('last_inbox_check', db.now())
    return {'new': new}


def record(hit, key, frm, subject, body, c, their_mid=None):
    kind = c['kind']
    rid = db.x('INSERT OR IGNORE INTO replies(lead_id, enrollment_id, from_email, subject, body, kind, summary, received_at, msg_key, message_id) VALUES (?,?,?,?,?,?,?,?,?,?)',
               (hit['lead_id'], hit['enrollment_id'], frm, subject, body, kind, c['summary'], db.now(), key, their_mid))
    if kind == 'out_of_office':
        db.x('UPDATE replies SET handled=1 WHERE id=?', (rid,))
        db.log(f"Out-of-office from {frm}; follow-ups continue")
        return rid
    if kind in ('bounce', 'unsubscribe'):
        db.suppress(hit['to_email'], kind)
        if kind == 'unsubscribe' and frm: db.suppress(frm, kind)
    if kind in ('bounce', 'unsubscribe', 'not_interested'):
        db.x('UPDATE replies SET handled=1 WHERE id=?', (rid,))   # nothing to answer; still listed under Closed
    lead_status = {'bounce': 'bounced', 'unsubscribe': 'unsubscribed', 'not_interested': 'not_interested'}.get(kind, 'replied')
    db.x('UPDATE leads SET status=?, last_contact_at=?, updated_at=? WHERE id=?', (lead_status, db.now(), db.now(), hit['lead_id']))
    if kind in ('interested', 'question'):
        db.x("UPDATE leads SET stage='interested', stage_changed_at=? WHERE id=? AND stage IS NULL", (db.now(), hit['lead_id']))
    stop_lead(hit['lead_id'], 'bounced' if kind == 'bounce' else 'replied')
    db.log(f"{kind.replace('_', ' ').capitalize()} from {frm or hit['to_email']}: {c['summary']}")
    if kind == 'bounce':
        from . import worker   # late import: worker imports this module
        worker.bounce_guard()
    kinds = [k.strip() for k in (db.get('forward_kinds') or '').split(',') if k.strip()]
    to = (db.get('forward_to') or '').strip()
    if db.get('forward_on') == '1' and to and kind in kinds and rid:
        try:
            forward_reply(rid, to)
        except Exception as e:  # noqa
            db.log(f'Could not forward the reply from {frm} to {to}: {e}', 'warn')
    return rid


def stop_lead(lead_id, why):
    db.x("UPDATE enrollments SET status=? WHERE lead_id=? AND status IN ('active','waiting')", (why, lead_id))
    db.x("UPDATE messages SET status='cancelled', error=? WHERE lead_id=? AND status IN ('draft','approved')", (f'stopped: {why}', lead_id))
