"""Checks an email before it goes out. Each finding has a code (the dashboard explains it in plain words), a level and data:
- block: must be fixed before approving or sending (an empty field, a leftover placeholder like {first_name} or [Name]),
- warn:  worth a look (too long, words that spam filters dislike, several links, shouting),
- info:  a hint (no question at the end, the company is not mentioned)."""
import re

SPAM = [r'\bfree\b(?! of charge)(?<!feel free)', r'\bguarantee[ds]?\b', r'100\s?%', r'\bact now\b', r'\blimited time\b', r'\brisk[- ]free\b',
        r'\bwinner\b', r'\bcash\b', r'\bclick here\b', r'\bbuy now\b', r'\burgent\b', r'\bcheapest\b', r'\blowest price\b',
        r'\bbest price\b', r'\bspecial promotion\b', r'\bno obligation\b', r'\bcongratulations\b', r'\bdear friend\b',
        r'\bamazing\b', r'\bincredible\b', r'\bonce in a lifetime\b', r'\$\$+', r'\bearn money\b', r'\bdiscount\b', r'\boffer expires\b']
PLACEHOLDER = re.compile(r'\{[a-z_]{2,30}\}|\[\[[^\]]*\]\]|\[(?:name|first name|company|company name|your name|contact|contact name|insert[^\]]*|xxx+|date|price|link)\]'
                         r'|<(?:name|company|first name)>|lorem ipsum|\bXXX+\b', re.I)
ACRONYMS = {'ISO', 'CE', 'FDA', 'OEM', 'ODM', 'MOQ', 'EXW', 'FOB', 'CIF', 'DAP', 'DDP', 'USD', 'EUR', 'GBP', 'DHL', 'UPS', 'FEDEX', 'GMBH',
            'LLC', 'LTD', 'AISI', 'PDF', 'RAX', 'TIG', 'CNC', 'MDR', 'GMP', 'UAE', 'USA', 'UK', 'EU', 'SKU', 'PVD'}
LINK = re.compile(r'https?://|www\.', re.I)


def words(text):
    return re.findall(r"[\w'’-]+", text or '')


def lint(subject, body, kind='campaign', step=0, company=''):
    out = []
    add = lambda code, level, **data: out.append({'code': code, 'level': level, 'data': data})
    subject, body = (subject or '').strip(), (body or '').strip()
    if not subject and kind != 'reply':
        add('empty_subject', 'block')
    if not body:
        add('empty_body', 'block')
        return out
    found = sorted({m.group(0) for m in PLACEHOLDER.finditer(subject + '\n' + body)})
    if found:
        add('placeholder', 'block', text=', '.join(found[:4]))
    n = len(words(body))
    limit = 250 if kind == 'reply' else (150 if step == 0 else 100)
    if n > limit:
        add('too_long', 'warn', words=n, max=limit)
    if kind != 'reply':
        hits = sorted({m.group(0).lower() for p in SPAM for m in re.finditer(p, subject + ' ' + body, re.I)})
        if hits:
            add('spam_words', 'warn', words=', '.join(hits[:5]))
        links = len(LINK.findall(body))
        if links > 1:
            add('many_links', 'warn', n=links)
        if body.count('!') + subject.count('!') > 1:
            add('exclaim', 'warn')
        caps = [w for w in words(subject + ' ' + body) if len(w) >= 4 and w.isupper() and w.upper() not in ACRONYMS and not any(c.isdigit() for c in w)]
        if len(caps) > 2 or (subject and subject.isupper() and len(subject) > 6):
            add('caps', 'warn')
        if len(subject) > 70:
            add('subject_long', 'warn', n=len(subject))
        if step == 0 and subject.lower().startswith(('re:', 'fw:', 'fwd:')):
            add('fake_re', 'warn')
        if '?' not in body:
            add('no_question', 'info')
        if step == 0 and company and len(company) > 2:
            short = re.sub(r'\b(gmbh|ltd|llc|inc|co|srl|sl|bv|sa|sas|ag|plc|limited|company)\b\.?', '', company, flags=re.I).strip(' ,.-')
            if short and short.lower() not in body.lower() and short.lower() not in subject.lower():
                add('not_personal', 'info')
    return out


def blocks(findings):
    return [f for f in findings if f['level'] == 'block']
