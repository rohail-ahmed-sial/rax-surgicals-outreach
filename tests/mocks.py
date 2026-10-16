"""Stand-ins used only for testing: Claude API, Google Places API, DNS-over-HTTPS, company websites, an SMTP server and
an IMAP inbox. Nothing here is used by the software itself."""
import json, re, threading, socketserver, base64, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

AI_CALLS = []
SENT = []          # raw emails received by the fake SMTP server
PLACES = []
PLACES_CALLS = []
SITES = {}         # host -> {path: html}
DNS = {}           # (name, type) -> list of answers; ('x', 'NX') -> NXDOMAIN


def _serve(handler, port=0):
    s = ThreadingHTTPServer(('127.0.0.1', port), handler)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _json(h, code, obj):
    data = json.dumps(obj).encode()
    h.send_response(code); h.send_header('Content-Type', 'application/json'); h.send_header('Content-Length', str(len(data))); h.end_headers()
    h.wfile.write(data)


class AIHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers.get('anthropic-version') == '2023-06-01'
        if self.headers.get('x-api-key') != 'sk-test':
            return _json(self, 401, {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}})
        sysm, user = body.get('system', ''), body['messages'][0]['content']
        AI_CALLS.append({'model': body['model'], 'system': sysm, 'user': user})
        if 'check whether a company' in sysm:
            sialkot = 'sialkot' in user.lower()
            out = {'fit': 'no' if sialkot else 'good', 'score': 12 if sialkot else 86, 'category': 'manufacturer' if sialkot else 'distributor',
                   'reason': 'Another instrument maker in Sialkot.' if sialkot else 'Distributes surgical and dental instruments to clinics.',
                   'language': 'de' if 'Chirurgie' in user else 'en', 'contact_name': 'Anna Keller' if 'Anna Keller' in user else ''}
            text = 'Here you go: ' + json.dumps(out)
        elif 'B2B sales emails' in sysm:
            m = re.search(r'Recipient company: (.+)', user)
            follow = 'follow-up number' in user
            text = json.dumps({'subject': 'Instruments for ' + m.group(1), 'body': ('Hello,\n\nShort follow-up about private label. Shall I send photos?' if follow else
                                f'Hello,\n\nI saw that {m.group(1)} supplies clinics. We make surgical instruments in Sialkot. Would a catalogue help?')})
        elif "seller's answer" in sysm:
            text = json.dumps({'body': 'Hello,\n\nThank you. Our price list follows shortly. Which items and quantities do you need?'})
        elif 'Google Maps search phrases' in sysm:
            text = json.dumps({'queries': ['Medizinischer Großhandel', 'Chirurgische Instrumente', 'surgical instruments distributor']})
        elif 'sort replies' in sysm:
            kind = 'interested' if 'price' in user.lower() else 'not_interested' if 'not interested' in user.lower() else 'other'
            text = json.dumps({'kind': kind, 'summary': 'They ask for prices.' if kind == 'interested' else 'No.'})
        else:
            text = 'Hello RAX Surgicals'
        _json(self, 200, {'content': [{'type': 'text', 'text': text}], 'model': body['model'],
                          'usage': {'input_tokens': len(sysm + user) // 4, 'output_tokens': len(text) // 4}})


class PlacesHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.headers.get('X-Goog-Api-Key') != 'places-test':
            return _json(self, 400, {'error': {'code': 400, 'message': 'API key not valid. Please pass a valid API key.', 'status': 'INVALID_ARGUMENT'}})
        assert 'places.websiteUri' in self.headers.get('X-Goog-FieldMask', '')
        PLACES_CALLS.append(body)
        if body.get('pageSize') == 1:
            return _json(self, 200, {'places': PLACES[:1]})
        page = 1 if body.get('pageToken') == 'p2' else 0
        chunk = PLACES[page * 2:(page + 1) * 2]
        out = {'places': chunk}
        if page == 0 and len(PLACES) > 2: out['nextPageToken'] = 'p2'
        _json(self, 200, out)


class DoHHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        name, rtype = q['name'].lower().rstrip('.'), q['type']
        code = {'A': 1, 'CNAME': 5, 'MX': 15, 'TXT': 16}[rtype]
        if DNS.get((name, 'NX')):
            return _json(self, 200, {'Status': 3})
        ans = [{'name': name, 'type': code, 'data': d} for d in DNS.get((name, rtype), [])]
        _json(self, 200, {'Status': 0, 'Answer': ans} if ans else {'Status': 0})


class SiteHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        host = self.headers.get('Host', '').split(':')[0]
        pages = SITES.get(host, {})
        path = self.path.split('?')[0]
        html = pages.get(path)
        if html is None:
            self.send_response(404); self.send_header('Content-Length', '0'); self.end_headers(); return
        data = html.encode()
        ctype = 'text/plain' if path == '/robots.txt' else 'text/html; charset=utf-8'
        self.send_response(200); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(data))); self.end_headers()
        self.wfile.write(data)


class SMTPHandler(socketserver.StreamRequestHandler):
    def w(self, s): self.wfile.write((s + '\r\n').encode())

    def handle(self):
        self.w('220 fake smtp')
        rcpt, frm = [], None
        while True:
            line = self.rfile.readline().decode(errors='replace').rstrip('\r\n')
            if not line: return
            cmd = line.upper()
            if cmd.startswith(('EHLO', 'HELO')):
                self.w('250-fake'); self.w('250-AUTH PLAIN LOGIN'); self.w('250 SIZE 10000000')
            elif cmd.startswith('AUTH PLAIN'):
                creds = base64.b64decode(line.split()[2]).split(b'\0')
                self.w('235 ok' if creds[2] == b'smtp-pass' else '535 5.7.8 Authentication credentials invalid')
            elif cmd.startswith('AUTH LOGIN'):
                self.w('535 5.7.8 Authentication credentials invalid')
            elif cmd.startswith('MAIL FROM'):
                frm = line; self.w('250 ok')
            elif cmd.startswith('RCPT TO'):
                if 'NOUSER' in cmd: self.w('550 5.1.1 No such user')
                else: rcpt.append(line); self.w('250 ok')
            elif cmd == 'DATA':
                self.w('354 go'); buf = []
                while True:
                    l = self.rfile.readline()
                    if l in (b'.\r\n', b'.\n'): break
                    buf.append(l[1:] if l.startswith(b'..') else l)
                SENT.append({'from': frm, 'rcpt': rcpt[:], 'raw': b''.join(buf)}); rcpt.clear()
                self.w('250 queued')
            elif cmd == 'QUIT':
                self.w('221 bye'); return
            elif cmd in ('RSET', 'NOOP'):
                self.w('250 ok')
            else:
                self.w('502 no')


def smtp_server():
    s = socketserver.ThreadingTCPServer(('127.0.0.1', 0), SMTPHandler)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


class FakeIMAP:
    """Enough of imaplib.IMAP4 for check_replies() and for saving a copy in the Sent folder."""
    INBOX = []
    APPENDED = []

    def select(self, folder, readonly=False):
        return 'OK', [str(len(self.INBOX)).encode()]

    def search(self, charset, *crit):
        return 'OK', [' '.join(str(i + 1) for i in range(len(self.INBOX))).encode()]

    def fetch(self, num, what):
        return 'OK', [(b'1 (BODY[] {n}', self.INBOX[int(num) - 1]), b')']

    def list(self):
        return 'OK', [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "Sent Items"']

    def append(self, folder, flags, when, raw):
        self.APPENDED.append((folder, raw))
        return 'OK', [b'done']

    def logout(self):
        pass


def start_all():
    return {'ai': _serve(AIHandler), 'places': _serve(PlacesHandler), 'sites': _serve(SiteHandler, 0), 'smtp': smtp_server(),
            'doh': _serve(DoHHandler)}
