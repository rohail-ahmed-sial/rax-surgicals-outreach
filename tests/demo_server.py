"""Starts RAX Surgicals Outreach on port 8790 with stand-in services and sample data, for looking at the dashboard.
usage: python3 tests/demo_server.py [--empty] [--port N]"""
import os, sys, time, tempfile, threading, datetime as dt
from email.utils import make_msgid
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mocks
M = mocks.start_all()
os.environ['RAX_DATA_DIR'] = tempfile.mkdtemp(prefix='raxdemo-')
os.environ['RAX_NO_WORKER'] = '1'
os.environ['RAX_ANTHROPIC_BASE'] = f"http://127.0.0.1:{M['ai'].server_address[1]}"
os.environ['RAX_PLACES_BASE'] = f"http://127.0.0.1:{M['places'].server_address[1]}"
from app import db, server, worker, finder, mailer, dnscheck  # noqa
dnscheck.PROVIDERS = [f"http://127.0.0.1:{M['doh'].server_address[1]}/resolve"]
mailer._imap = lambda: mocks.FakeIMAP()
PORT = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else 8790

httpd = server.serve('127.0.0.1', PORT, require_login=False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

if '--empty' not in sys.argv:
    SP = M['sites'].server_address[1]
    names = ['meditrade.test', 'clinicline.test', 'praxisbedarf.test', 'nailpro.test', 'vetsource.test', 'ossmed.test', 'sialkotsteel.test',
             'dentaire-lyon.test', 'gulfmed.test', 'aussurg.test', 'tokyomed.test', 'medibrasil.test']
    hosts = open('/etc/hosts').read()
    missing = [n for n in names if n not in hosts]
    if missing:
        open('/etc/hosts', 'a').write('\n127.0.0.1 ' + ' '.join(missing) + '\n')
    for n in names + ['raxsurgicals.test']:
        mocks.DNS[(n, 'MX')] = [f'10 mx.{n}.']
    mocks.DNS[('raxsurgicals.test', 'TXT')] = ['"v=spf1 include:_spf.google.com ~all"']
    mocks.DNS[('google._domainkey.raxsurgicals.test', 'TXT')] = ['"v=DKIM1; p=MIIB"']
    page = lambda title, text, mail: {'/': f'<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{text}</p><a href="/contact">Contact</a></body></html>',
                                      '/contact': f'<html><body><a href="mailto:{mail}">{mail}</a></body></html>' if mail else '<html><body>Call us.</body></html>'}
    mocks.SITES.update({
        'meditrade.test': page('MediTrade Supplies Ltd', 'Distributor of surgical instruments and hospital supplies across the UK.', 'purchasing@meditrade.test'),
        'clinicline.test': page('ClinicLine', 'Medical supplies wholesale for clinics and surgeries. Anna Keller, Buyer.', 'anna.keller@clinicline.test'),
        'praxisbedarf.test': page('Praxisbedarf Nord', 'Großhandel für Chirurgie und Dental Instrumente.', 'einkauf@praxisbedarf.test'),
        'nailpro.test': page('NailPro Wholesale', 'Beauty supply wholesale: manicure and pedicure instruments for salons.', 'orders@nailpro.test'),
        'vetsource.test': page('VetSource Distribution', 'Veterinary supplies distributor and importer.', 'info@vetsource.test'),
        'ossmed.test': page('OSS Medical', 'Orthopedic implants.', ''),
        'sialkotsteel.test': page('Sialkot Steel Works', 'Surgical instruments manufacturer in Sialkot, Pakistan.', 'export@sialkotsteel.test'),
        'dentaire-lyon.test': page('Dentaire Lyon', 'Fournitures dentaires et instruments chirurgicaux, distributeur.', 'contact@dentaire-lyon.test'),
        'gulfmed.test': page('Gulf Medical Trading', 'Hospital supply company and medical equipment importer in Dubai.', 'procurement@gulfmed.test'),
        'aussurg.test': page('AusSurg Supplies', 'Surgical instruments distributor for Australian hospitals.', 'sales@aussurg.test'),
        'tokyomed.test': page('Tokyo Medical Trading', 'Medical equipment importer and wholesaler.', 'info@tokyomed.test'),
        'medibrasil.test': page('MediBrasil', 'Distribuidora de produtos hospitalares e material cirúrgico.', 'compras@medibrasil.test'),
    })
    rows = [('MediTrade Supplies Ltd', 'meditrade.test', 'United Kingdom', 'Leeds'), ('ClinicLine', 'clinicline.test', 'Ireland', 'Dublin'),
            ('Praxisbedarf Nord', 'praxisbedarf.test', 'Germany', 'Hamburg'), ('NailPro Wholesale', 'nailpro.test', 'United States', 'Dallas'),
            ('VetSource Distribution', 'vetsource.test', 'Netherlands', 'Utrecht'), ('OSS Medical', 'ossmed.test', 'France', 'Lyon'),
            ('Sialkot Steel Works', 'sialkotsteel.test', 'Pakistan', 'Sialkot'), ('Dentaire Lyon', 'dentaire-lyon.test', 'France', 'Lyon'),
            ('Gulf Medical Trading', 'gulfmed.test', 'United Arab Emirates', 'Dubai'), ('AusSurg Supplies', 'aussurg.test', 'Australia', 'Sydney'),
            ('Tokyo Medical Trading', 'tokyomed.test', 'Japan', 'Tokyo'), ('MediBrasil', 'medibrasil.test', 'Brazil', 'São Paulo')]
    for n, h, c, city in rows:
        finder.add_lead({'company': n, 'website': f'http://{h}:{SP}', 'country': c, 'city': city}, 'google_maps')
    finder.add_lead({'company': 'Surgimed Trading', 'country': 'Saudi Arabia', 'city': 'Riyadh'}, 'google_maps')
    for k, v in {'anthropic_api_key': 'sk-test', 'google_places_api_key': 'places-test', 'sender_name': 'Rohail Ahmed', 'sender_title': 'Export Manager',
                 'sender_email': 'sales@raxsurgicals.test', 'smtp_host': '127.0.0.1', 'smtp_port': str(M['smtp'].server_address[1]), 'smtp_security': 'none',
                 'smtp_user': 'sales@raxsurgicals.test', 'smtp_password': 'smtp-pass', 'imap_host': 'imap.example.test', 'company_website': 'https://raxsurgicals.com',
                 'send_hour_start': '0', 'send_hour_end': '24', 'send_weekdays_only': '0', 'gap_min_minutes': '0', 'gap_max_minutes': '0', 'setup_done': '1',
                 'email_provider': 'google', 'fact_moq': '50 pieces per item', 'fact_lead_time': '4 to 6 weeks', 'warmup_on': '1',
                 'warmup_started': (dt.date.today() - dt.timedelta(days=9)).isoformat(), 'daily_limit': '40', 'save_sent_copy': 'off',
                 }.items():
        db.put(k, v)
    for l in db.q('SELECT id FROM leads'):
        finder.crawl(l['id']); finder.verify_email(l['id']); finder.qualify(l['id'])
    cid = db.x("INSERT INTO campaigns(name, pitch, instructions, steps, active, created_at) VALUES (?,?,?,?,1,?)",
               ('Distributors, first contact', 'Our surgical and beauty instrument range, custom instruments and private label for distributors.',
                'Minimum order 50 pieces per item. Do not mention prices.',
                '[{"day":0,"kind":"ai","instructions":"Offer the catalogue"},{"day":4,"kind":"ai","instructions":"Private label"},{"day":10,"kind":"ai","instructions":"Offer samples"}]', db.now()))
    ready = [r['id'] for r in db.q("SELECT id FROM leads WHERE status='ready' ORDER BY id")]
    worker.enroll(cid, ready[:8]); worker.draft_tick(20)
    ms = db.q("SELECT id FROM messages WHERE status='draft' ORDER BY id")
    for m in ms[:4]:
        db.x("UPDATE messages SET status='approved', approved_at=? WHERE id=?", (db.now(), m['id']))
    for _ in range(3):
        db.put('next_send_at', ''); worker.send_tick(force_now=True)
    # pretend earlier days had activity, for the charts (spread over leads that are not in the campaign above)
    others = db.q("SELECT id, email, company FROM leads WHERE email<>'' AND id NOT IN (SELECT lead_id FROM enrollments) ORDER BY id")
    ans = [('interested', 'Asked for the catalogue and the MOQ.'), ('other', 'Said they will look at the range next month.'), ('not_interested', 'Buys locally for now.')]
    for d in range(1, 14):
        day = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=d)).replace(hour=10).isoformat()
        for k in range((d * 7) % 9 + 3):
            o = others[(d * 3 + k) % len(others)]
            db.x("INSERT INTO messages(lead_id, step, to_email, subject, body, status, kind, sent_at, message_id) VALUES (?,0,?,?,?,'sent','campaign',?,?)",
                 (o['id'], o['email'], f"Surgical instruments for {o['company']}", 'Hello,\n\nWe make surgical and beauty instruments in Sialkot.', day, make_msgid()))
        if d % 3 == 0:
            o = others[d % len(others)]
            kind, summary = ans[(d // 3) % 3]
            db.x("INSERT INTO replies(lead_id, from_email, subject, body, kind, summary, received_at, msg_key, handled) VALUES (?,?,?,?,?,?,?,?,1)",
                 (o['id'], o['email'], f"Re: Surgical instruments for {o['company']}", summary, kind, summary, day, make_msgid()))
    sent = db.q("SELECT * FROM messages WHERE status='sent' AND enrollment_id IS NOT NULL ORDER BY id")
    r1 = (f"From: Tom Baker <purchasing@meditrade.test>\r\nSubject: Re: {sent[0]['subject']}\r\nMessage-ID: {make_msgid()}\r\nIn-Reply-To: {sent[0]['message_id']}\r\n"
          "Content-Type: text/plain\r\n\r\nHello Rohail,\r\n\r\nPlease send your price list for needle holders and Metzenbaum scissors, and your MOQ.\r\n\r\nRegards, Tom\r\n").encode()
    r2 = (f"From: Anna Keller <anna.keller@clinicline.test>\r\nSubject: Re: {sent[1]['subject']}\r\nMessage-ID: {make_msgid()}\r\nIn-Reply-To: {sent[1]['message_id']}\r\n"
          "Content-Type: text/plain\r\n\r\nThanks, we are not interested at the moment.\r\n").encode()
    mocks.FakeIMAP.INBOX = [r1, r2]
    mailer.check_replies()
    lead_by = lambda n: db.q('SELECT id FROM leads WHERE company=?', (n,), one=True)['id']
    for name, stage, val, act, days in [('Gulf Medical Trading', 'quote', 4200, 'Follow up on the quote', 0), ('AusSurg Supplies', 'sample', 1800, 'Courier the samples', -2),
                                        ('Tokyo Medical Trading', 'negotiation', 9500, 'Agree on payment terms', 3), ('MediBrasil', 'won', 6400, '', None)]:
        lid = lead_by(name)
        db.x('UPDATE leads SET stage=?, deal_value=?, next_action=?, next_action_date=?, stage_changed_at=?, last_contact_at=? WHERE id=?',
             (stage, val, act, (dt.date.today() + dt.timedelta(days=days)).isoformat() if days is not None else None, db.now(), db.now(), lid))
        db.note(lid, f'>{stage}', 'stage')
    db.note(lead_by('Gulf Medical Trading'), 'Called Ahmed: wants 300 needle holders and 200 scissors, OEM with their logo.')
    db.x("INSERT INTO searches(query, location, max, found, added, status, created_at, finished_at) VALUES ('surgical instruments distributor','Germany',60,58,21,'done',?,?)", (db.now(), db.now()))
    db.x("INSERT INTO searches(query, location, max, found, added, status, created_at) VALUES ('Medizinischer Großhandel','Hamburg, Germany',60,0,0,'queued',?)", (db.now(),))
    open(os.path.join(db.FILES_DIR, 'demo_cat.pdf'), 'wb').write(b'%PDF-1.4 demo')
    db.x("INSERT INTO files(name, stored, size, mime, created_at) VALUES ('RAX Catalogue 2026.pdf','demo_cat.pdf',2400000,'application/pdf',?)", (db.now(),))
    db.put('gap_min_minutes', '3'); db.put('gap_max_minutes', '8'); db.put('send_hour_start', '9'); db.put('send_hour_end', '17'); db.put('send_weekdays_only', '1')
    db.put('next_send_at', '')
    db.log('Daily backup saved in the data/backups folder')
print(f'ready on http://127.0.0.1:{PORT}', flush=True)
while True:
    time.sleep(3600)
