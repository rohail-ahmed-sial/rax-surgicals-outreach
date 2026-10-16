"""Database: one SQLite file (data/outreach.db). Every module opens its own short connection through conn().
Opening an older database adds the new tables and columns by itself (see migrate())."""
import sqlite3, os, json, threading, datetime as dt

DATA_DIR = os.environ.get('RAX_DATA_DIR') or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DB_PATH = os.path.join(DATA_DIR, 'outreach.db')
FILES_DIR = os.path.join(DATA_DIR, 'files')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
VERSION = '1.0'
NAME = 'RAX Surgicals Outreach'      # called RAX Outreach up to version 2.1
SLOGAN = 'Find buyers. Email them. Turn replies into orders.'
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT NOT NULL, website TEXT, domain TEXT, country TEXT, city TEXT, address TEXT, phone TEXT,
  source TEXT, search_query TEXT, place_id TEXT UNIQUE,
  emails TEXT DEFAULT '[]', email TEXT, contact_name TEXT,
  site_text TEXT, crawl_status TEXT DEFAULT 'pending', crawl_note TEXT,
  fit TEXT, score INTEGER, category TEXT, ai_reason TEXT, language TEXT,
  status TEXT DEFAULT 'new', notes TEXT,
  created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS leads_status ON leads(status);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, pitch TEXT, instructions TEXT,
  steps TEXT DEFAULT '[]', write_in_their_language INTEGER DEFAULT 0, auto_approve_followups INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS enrollments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, lead_id INTEGER,
  step INTEGER DEFAULT 0, status TEXT DEFAULT 'active', next_due TEXT, first_message_id TEXT, thread_subject TEXT,
  created_at TEXT, UNIQUE(campaign_id, lead_id));
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, enrollment_id INTEGER, lead_id INTEGER, campaign_id INTEGER, step INTEGER,
  to_email TEXT, subject TEXT, body TEXT, status TEXT DEFAULT 'draft', error TEXT,
  message_id TEXT, in_reply_to TEXT, written_by TEXT,
  created_at TEXT, approved_at TEXT, sent_at TEXT);
CREATE INDEX IF NOT EXISTS messages_status ON messages(status);
CREATE TABLE IF NOT EXISTS replies (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER, enrollment_id INTEGER, from_email TEXT, subject TEXT,
  body TEXT, kind TEXT, summary TEXT, received_at TEXT, msg_key TEXT UNIQUE, handled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS suppression (email TEXT PRIMARY KEY, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, status TEXT, done INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
  message TEXT, created_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, level TEXT, text TEXT);
-- added in version 2
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER, at TEXT, kind TEXT DEFAULT 'note', text TEXT);
CREATE INDEX IF NOT EXISTS notes_lead ON notes(lead_id);
CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, stored TEXT, size INTEGER, mime TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS message_files (message_id INTEGER, file_id INTEGER, PRIMARY KEY (message_id, file_id));
CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, location TEXT, max INTEGER,
  found INTEGER DEFAULT 0, added INTEGER DEFAULT 0, status TEXT, error TEXT, created_at TEXT, auto_check INTEGER DEFAULT 1,
  finished_at TEXT);
CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, kind TEXT, model TEXT,
  input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS domains (domain TEXT PRIMARY KEY, mx_ok INTEGER, checked_at TEXT);
"""

# columns added in version 2 to tables that already existed in version 1
NEW_COLUMNS = {
    'leads': [('stage', 'TEXT'), ('deal_value', 'REAL'), ('deal_currency', "TEXT DEFAULT 'USD'"), ('next_action', 'TEXT'),
              ('next_action_date', 'TEXT'), ('email_status', 'TEXT'), ('last_contact_at', 'TEXT'), ('stage_changed_at', 'TEXT')],
    'messages': [('kind', "TEXT DEFAULT 'campaign'"), ('reply_to_id', 'INTEGER'), ('references_hdr', 'TEXT')],
    'replies': [('message_id', 'TEXT'), ('forwarded_at', 'TEXT'), ('ai_draft', 'TEXT')],
    'searches': [('auto_check', 'INTEGER DEFAULT 1'), ('finished_at', 'TEXT')],
}

DEFAULTS = {
    'company_name': 'RAX Surgicals',
    'company_website': '',
    'company_address': 'Sialkot, Punjab, Pakistan',
    'company_profile': ('Manufacturer and exporter of surgical, dental and beauty instruments from Sialkot, Pakistan. '
                        'Range: forceps, needle holders, scissors, retractors, neurosurgery instruments, cuticle nippers, '
                        'tweezers and other hand instruments in German stainless steel. Offers standard catalogue items, '
                        'custom instruments made to drawings or samples, and private label (OEM) with the buyer\'s own brand.'),
    'ideal_customer': ('Importers, wholesalers and distributors of medical, surgical, dental, veterinary or beauty instruments; '
                       'hospital and clinic supply companies; private-label brands that sell instruments under their own name. '
                       'Not a fit: other manufacturers in Sialkot/Pakistan, single doctors or patients, unrelated businesses.'),
    # facts the AI may use in emails and replies (left empty = the AI must not mention it)
    'fact_catalogue_link': '', 'fact_moq': '', 'fact_lead_time': '', 'fact_payment_terms': '', 'fact_certifications': '',
    'fact_samples': '', 'fact_shipping': '', 'fact_other': '',
    'sender_name': '', 'sender_title': '', 'sender_email': '', 'reply_to': '', 'signature': '',
    'email_provider': '',
    'smtp_host': '', 'smtp_port': '587', 'smtp_security': 'starttls', 'smtp_user': '', 'smtp_password': '',
    'imap_host': '', 'imap_port': '993', 'imap_user': '', 'imap_password': '', 'imap_folder': 'INBOX',
    'save_sent_copy': 'auto', 'sent_folder': '',
    'daily_limit': '30', 'gap_min_minutes': '3', 'gap_max_minutes': '8',
    'send_hour_start': '9', 'send_hour_end': '17', 'send_weekdays_only': '1',
    'sending_paused': '0', 'paused_reason': '',
    'warmup_on': '1', 'warmup_start': '10', 'warmup_step': '5', 'warmup_every_days': '7', 'warmup_started': '',
    'bounce_guard_on': '1', 'bounce_guard_pct': '5',
    'mx_check_on': '1',
    'forward_on': '0', 'forward_to': '', 'forward_kinds': 'interested,question',
    'ai_provider': 'anthropic', 'anthropic_api_key': '',
    'ai_model_fast': 'claude-haiku-5-5', 'ai_model_writer': 'claude-sonnet-5-5',
    'ai_daily_call_limit': '400',
    # US dollars per million tokens, only for the cost estimate on the overview (check your Anthropic bill for exact cost)
    'price_fast_in': '0.10', 'price_fast_out': '0.50', 'price_writer_in': '2', 'price_writer_out': '10',
    'google_places_api_key': '',
    'admin_password_hash': '',
    'my_timezone': 'Asia/Karachi', 'setup_done': '0',
    'backup_keep': '14', 'last_backup': '',
}
SECRET_KEYS = {'smtp_password', 'imap_password', 'anthropic_api_key', 'google_places_api_key'}


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def migrate(c):
    for table, cols in NEW_COLUMNS.items():
        have = {r[1] for r in c.execute(f'PRAGMA table_info({table})')}
        for name, decl in cols:
            if name not in have:
                c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
    c.execute("UPDATE messages SET kind='campaign' WHERE kind IS NULL")
    c.execute("UPDATE leads SET deal_currency='USD' WHERE deal_currency IS NULL")
    # replies stored before version 2 used the sender's Message-ID as msg_key
    c.execute("UPDATE replies SET message_id=msg_key WHERE message_id IS NULL AND msg_key LIKE '<%>'")
    c.execute("DELETE FROM settings WHERE key='ui_lang'")      # the dashboard is English only
    # a v1 user who already filled in email settings does not need the setup wizard again
    r = c.execute("SELECT value FROM settings WHERE key='smtp_host'").fetchone()
    if r and r[0]:
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('setup_done', '1')")


def _version_on_disk():
    """The version that last opened the database file: None for a new file, '1' for version 1 (it did not record one)."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        c = sqlite3.connect(DB_PATH, timeout=30)
        try:
            r = c.execute("SELECT value FROM settings WHERE key='db_version'").fetchone()
            return r[0] if r else '1'
        finally:
            c.close()
    except sqlite3.Error:
        return None


def init():
    old = _version_on_disk()
    if old and old != VERSION:
        # keep the data exactly as the older version left it, before anything is changed
        try:
            backup(os.path.join(BACKUP_DIR, f'before-{VERSION}-{dt.date.today().isoformat()}.db'))
        except (OSError, sqlite3.Error):
            pass
    with _lock, conn() as c:
        c.executescript(SCHEMA)
        migrate(c)
        for k, v in DEFAULTS.items():
            c.execute('INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)', (k, v))
        c.execute("INSERT INTO settings(key, value) VALUES ('db_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (VERSION,))
    os.makedirs(FILES_DIR, exist_ok=True)


def q(sql, args=(), one=False):
    with _lock, conn() as c:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid if sql.lstrip().upper().startswith('INSERT') else cur.rowcount


def get(key, default=None):
    r = q('SELECT value FROM settings WHERE key=?', (key,), one=True)
    return r['value'] if r and r['value'] is not None else (DEFAULTS.get(key, default) if default is None else default)


def get_int(key, default=0):
    try:
        return int(float(get(key) or default))
    except (TypeError, ValueError):
        return default


def get_float(key, default=0.0):
    try:
        return float(get(key) or default)
    except (TypeError, ValueError):
        return default


def put(key, value):
    x('INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))


def all_settings():
    return {r['key']: r['value'] for r in q('SELECT key, value FROM settings')}


def log(text, level='info'):
    x('INSERT INTO log(at, level, text) VALUES (?, ?, ?)', (now(), level, str(text)[:2000]))
    x('DELETE FROM log WHERE id < (SELECT MAX(id) - 5000 FROM log)')


def suppressed(email):
    """True if this address, or its whole domain (entered as @domain.com), is on the do-not-email list."""
    if not email:
        return False
    e = email.strip().lower()
    dom = '@' + e.split('@')[-1]
    return q('SELECT 1 FROM suppression WHERE email=? OR email=?', (e, dom), one=True) is not None


def suppress(email, reason):
    if email:
        x('INSERT OR IGNORE INTO suppression(email, reason, created_at) VALUES (?, ?, ?)', (email.strip().lower(), reason, now()))


def note(lead_id, text, kind='note'):
    return x('INSERT INTO notes(lead_id, at, kind, text) VALUES (?, ?, ?, ?)', (lead_id, now(), kind, str(text)[:4000]))


def jloads(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def backup(dest):
    """Copy the database safely (works while the software is running)."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with _lock:
        src = sqlite3.connect(DB_PATH, timeout=30)
        try:
            out = sqlite3.connect(dest)
            with out:
                src.backup(out)
            out.close()
        finally:
            src.close()
    return dest


def daily_backup():
    """Once a day keep a copy in data/backups, and delete copies older than the newest `backup_keep`."""
    today = dt.date.today().isoformat()
    if get('last_backup') == today:
        return None
    path = backup(os.path.join(BACKUP_DIR, f'outreach-{today}.db'))
    put('last_backup', today)
    keep = max(1, get_int('backup_keep', 14))
    old = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith('outreach-') and f.endswith('.db'))
    for f in old[:-keep]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f))
        except OSError:
            pass
    return path
