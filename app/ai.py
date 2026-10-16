"""AI: Claude through the Anthropic Messages API (plain HTTPS, no extra packages).
Two models: a fast cheap one for checking leads and sorting replies, a better one for writing emails and replies.
Every call is counted (tokens) for the cost estimate. Without an API key, callers fall back to rules and templates."""
import json, os, re, ssl, time, urllib.request, urllib.error, datetime as dt
from . import db

API_BASE = os.environ.get('RAX_ANTHROPIC_BASE', 'https://api.anthropic.com')


class NoAI(Exception):
    pass


class AIError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def available():
    return bool((db.get('anthropic_api_key') or '').strip())


def calls_today():
    start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return db.q("SELECT COUNT(*) n FROM usage WHERE kind='ai' AND at>=?", (start,), one=True)['n']


def _error_code(status, detail):
    d = detail.lower()
    if status == 401 or 'invalid x-api-key' in d or 'authentication' in d:
        return 'ai_bad_key'
    if 'credit balance' in d or 'billing' in d:
        return 'ai_no_credit'
    if status == 404 or 'model' in d and 'not' in d and 'found' in d:
        return 'ai_model'
    if status == 429:
        return 'ai_rate'
    if status in (500, 502, 503, 529):
        return 'ai_busy'
    return 'ai_error'


def chat(system, user, writer=False, max_tokens=900):
    key = (db.get('anthropic_api_key') or '').strip()
    if not key:
        raise NoAI('No AI key set')
    if calls_today() >= db.get_int('ai_daily_call_limit', 400):
        raise NoAI('Daily AI call limit reached (Settings, AI). Using templates until tomorrow.')
    model = db.get('ai_model_writer' if writer else 'ai_model_fast')
    body = json.dumps({'model': model, 'max_tokens': max_tokens, 'system': system,
                       'messages': [{'role': 'user', 'content': user}]}).encode()
    data = None
    for attempt in range(2):
        req = urllib.request.Request(API_BASE.rstrip('/') + '/v1/messages', data=body, method='POST', headers={
            'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=90, context=ssl.create_default_context()) as r:
                data = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')[:400]
            code = _error_code(e.code, detail)
            if code in ('ai_rate', 'ai_busy') and attempt == 0:
                time.sleep(4)
                continue
            raise AIError(code, f'AI error {e.code}: {detail}')
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise AIError('network', f'Could not reach the AI service: {e}')
    u = data.get('usage') or {}
    db.x('INSERT INTO usage(at, kind, model, input_tokens, output_tokens) VALUES (?,?,?,?,?)',
         (db.now(), 'ai', model, int(u.get('input_tokens') or 0), int(u.get('output_tokens') or 0)))
    return ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text').strip()


def chat_json(system, user, writer=False, max_tokens=900):
    text = chat(system + '\nReply with one JSON object only, no other text.', user, writer, max_tokens)
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        raise AIError('ai_format', 'AI did not return JSON: ' + text[:200])
    try:
        return json.loads(m.group(0))
    except ValueError:
        raise AIError('ai_format', 'AI returned broken JSON: ' + text[:200])


FACTS = [('fact_catalogue_link', 'Catalogue link'), ('fact_moq', 'Minimum order'), ('fact_lead_time', 'Production / delivery time'),
         ('fact_payment_terms', 'Payment terms'), ('fact_certifications', 'Certificates'), ('fact_samples', 'Samples'),
         ('fact_shipping', 'Shipping'), ('fact_other', 'Other facts')]


def facts_text():
    lines = [f'- {label}: {db.get(k).strip()}' for k, label in FACTS if (db.get(k) or '').strip()]
    return ('Facts you may use (only these; if something is not listed here, do not state it as a fact):\n' + '\n'.join(lines)) if lines \
        else 'No extra facts are given: do not state prices, minimum orders, delivery times, certificates or payment terms.'


def _profile():
    return (f"Seller: {db.get('company_name')}\nAddress: {db.get('company_address')}\n"
            f"Website: {db.get('company_website') or '(not given)'}\nWhat we do: {db.get('company_profile')}\n"
            f"Ideal customer: {db.get('ideal_customer')}\n{facts_text()}")


# ---------- checking a lead ----------
CATEGORIES = ['distributor', 'importer', 'wholesaler', 'hospital_supplier', 'dental_supplier', 'beauty_supplier',
              'veterinary_supplier', 'private_label_brand', 'hospital_or_clinic', 'retailer', 'manufacturer', 'other']


def qualify(lead):
    system = ('You check whether a company is a good B2B sales lead for the seller below. Judge only from the given '
              'information; if the website text is missing or unclear, say "maybe" and explain.\n\n' + _profile())
    user = (f"Company: {lead.get('company')}\nCountry: {lead.get('country') or '?'}  City: {lead.get('city') or '?'}\n"
            f"Website: {lead.get('website') or '(none)'}\n\nText from their website:\n{(lead.get('site_text') or '(none)')[:6000]}\n\n"
            'Return JSON: {"fit": "good"|"maybe"|"no", "score": 0-100, "category": one of '
            + json.dumps(CATEGORIES) + ', "reason": "one short sentence", '
            '"language": "two-letter code of the language their website is written in", '
            '"contact_name": "full name of a buyer/owner/manager if clearly shown, else empty"}')
    r = chat_json(system, user, writer=False, max_tokens=400)
    fit = r.get('fit') if r.get('fit') in ('good', 'maybe', 'no') else 'maybe'
    try:
        score = max(0, min(100, int(r.get('score', 50))))
    except (TypeError, ValueError):
        score = 50
    if not (lead.get('site_text') or '').strip() and fit == 'good':
        fit, score = 'maybe', min(score, 60)      # nothing to judge from: never "good" on the name alone
    return {'fit': fit, 'score': score, 'category': str(r.get('category') or 'other')[:40],
            'ai_reason': str(r.get('reason') or '')[:400], 'language': str(r.get('language') or 'en')[:5].lower(),
            'contact_name': str(r.get('contact_name') or '')[:80]}


KEYWORDS_GOOD = ['surgical', 'surgery', 'medical supplies', 'medical equipment', 'instrument', 'dental', 'hospital supply',
                 'distributor', 'wholesale', 'importer', 'veterinary', 'beauty supply', 'manicure', 'pedicure', 'podiatry',
                 'chirurg', 'medizin', 'dentaire', 'médical', 'quirúrg', 'chirurgic', 'medisch', 'großhandel', 'grossiste', 'mayorista']
KEYWORDS_BAD = ['sialkot', 'manufacturer from pakistan', 'made in pakistan']


def qualify_rules(lead):
    """Simple keyword check used when no AI key is set."""
    t = ((lead.get('site_text') or '') + ' ' + (lead.get('company') or '')).lower()
    hits = sum(1 for k in KEYWORDS_GOOD if k in t)
    bad = any(k in t for k in KEYWORDS_BAD)
    if bad:
        return {'fit': 'no', 'score': 10, 'category': 'manufacturer', 'ai_reason': 'Looks like another Pakistani manufacturer (keyword check).'}
    if not lead.get('site_text'):
        return {'fit': 'maybe', 'score': 40, 'category': 'other', 'ai_reason': 'No website text to check (keyword check).'}
    score = min(90, 30 + hits * 12)
    return {'fit': 'good' if hits >= 3 else 'maybe' if hits >= 1 else 'no', 'score': score, 'category': 'other',
            'ai_reason': f'{hits} matching words on their website (keyword check, no AI).'}


# ---------- writing emails ----------
def write_email(lead, campaign, step_index, step, history):
    """history: earlier sent emails in this thread [{subject, body}]. Returns {subject, body} (body without signature)."""
    lang = lead.get('language') if campaign.get('write_in_their_language') and lead.get('language') else 'en'
    first = step_index == 0
    system = ('You write short B2B sales emails for the seller below. Rules: plain text; under 120 words; friendly and '
              'direct, no hype words, no exclamation marks; never invent facts, prices, certificates, delivery times or '
              'customers that are not in the seller profile or campaign notes; mention one specific, true detail about the '
              'recipient taken from their website text if there is one; one clear, easy question at the end; no signature, '
              'no placeholders like [Name]. Greeting: use the contact name if given, otherwise a neutral greeting.\n\n'
              + _profile() + f"\n\nCampaign pitch: {campaign.get('pitch') or ''}\nCampaign notes: {campaign.get('instructions') or ''}")
    hist = '\n\n'.join(f"--- Email {i + 1} (already sent) ---\nSubject: {h['subject']}\n{h['body']}" for i, h in enumerate(history))
    user = (f"Recipient company: {lead.get('company')}\nCountry: {lead.get('country') or '?'}\n"
            f"Contact name: {lead.get('contact_name') or '(unknown)'}\nType: {lead.get('category') or '?'}\n"
            f"Their website text:\n{(lead.get('site_text') or '(none)')[:4000]}\n\n"
            + (f"Earlier emails in this thread (they have not replied):\n{hist}\n\n" if hist else '')
            + f"Write {'the first email' if first else 'follow-up number ' + str(step_index)} in language '{lang}'. "
            + (f"Extra instruction for this email: {step.get('instructions')}\n" if step.get('instructions') else '')
            + ('' if first else 'A follow-up is shorter (under 70 words), adds something new (one product, custom or '
               'private-label option, or a simple offer like sending the catalogue) and does not guilt-trip.\n')
            + 'Return JSON: {"subject": "short subject, no clickbait", "body": "email text"}')
    r = chat_json(system, user, writer=True, max_tokens=900)
    subject, body = str(r.get('subject') or '').strip(), str(r.get('body') or '').strip()
    if not body:
        raise AIError('ai_format', 'AI returned an empty email')
    return {'subject': subject[:150], 'body': body}


def fill_template(text, lead, sender_name=''):
    first = (lead.get('contact_name') or '').split(' ')[0]
    vals = {'company': lead.get('company') or '', 'first_name': first, 'contact_name': lead.get('contact_name') or '',
            'country': lead.get('country') or '', 'city': lead.get('city') or '', 'my_name': sender_name,
            'my_company': db.get('company_name') or '', 'catalogue_link': db.get('fact_catalogue_link') or ''}
    out = text or ''
    for k, v in vals.items():
        out = out.replace('{' + k + '}', v)
    out = re.sub(r'(Hi|Hello|Dear) ,', r'\1,', out)          # "Hi {first_name}," with no name -> "Hi,"
    return re.sub(r'(Hi|Hello|Dear)  +', r'\1 ', out)


# ---------- answering replies ----------
def draft_reply(lead, thread, note=''):
    """thread: [{'who': 'us'|'them', 'subject', 'body', 'at'}] oldest first; the last 'them' item is answered."""
    system = ('You write the seller\'s answer to an email from a possible B2B buyer. Rules: plain text; under 160 words; '
              'friendly, clear and professional; answer each question using only the seller facts below; if they ask for '
              'something that is not in the facts (a price, an exact delivery date, a certificate), do not invent it: say '
              'it will follow shortly, and ask for the details needed (items, sizes, quantities, finish, branding); if they '
              'ask for the catalogue and a catalogue link is listed, give the link; end with one clear next step; write in '
              'the same language as their last email; no signature (it is added automatically); no placeholders.\n\n' + _profile())
    convo = '\n\n'.join(f"--- {'We wrote' if t['who'] == 'us' else 'They wrote'} ({t.get('at', '')[:10]}) ---\nSubject: {t.get('subject', '')}\n{t.get('body', '')[:3000]}"
                        for t in thread[-8:])
    user = (f"Buyer company: {lead.get('company')}\nCountry: {lead.get('country') or '?'}\nContact: {lead.get('contact_name') or '(unknown)'}\n\n"
            f"Conversation so far, oldest first:\n{convo}\n\n"
            + (f"Instruction from the seller for this answer: {note}\n" if note else '')
            + 'Return JSON: {"body": "the answer"}')
    r = chat_json(system, user, writer=True, max_tokens=1000)
    body = str(r.get('body') or '').strip()
    if not body:
        raise AIError('ai_format', 'AI returned an empty answer')
    return body


def reply_template(lead):
    name = (lead.get('contact_name') or '').split(' ')[0]
    link = (db.get('fact_catalogue_link') or '').strip()
    return (f"Hello{' ' + name if name else ''},\n\nThank you for your reply.\n\n"
            + (f"Our catalogue: {link}\n\n" if link else '')
            + "Could you tell me which items, sizes and quantities you need? I will then send you our offer.")


# ---------- search ideas ----------
def suggest_queries(country, focus):
    system = ('You help an exporter of surgical, dental, beauty and veterinary instruments find B2B buyers on Google Maps. '
              'Suggest short Google Maps search phrases that local businesses use to describe themselves.')
    user = (f"Country or city: {country}\nProduct focus: {focus or 'surgical and medical instruments'}\n"
            'Give 8 search phrases, mostly in the local language of that place (and 2 in English), for importers, '
            'wholesalers, distributors and supply shops. No place names inside the phrases. '
            'Return JSON: {"queries": ["...", "..."]}')
    r = chat_json(system, user, writer=False, max_tokens=400)
    return [str(x).strip()[:80] for x in (r.get('queries') or []) if str(x).strip()][:10]


# ---------- reading replies ----------
def classify_reply(subject, body):
    system = 'You sort replies to a B2B sales email for a surgical instruments exporter.'
    user = (f"Subject: {subject}\n\n{body[:4000]}\n\nReturn JSON: {{\"kind\": one of [\"interested\", \"question\", "
            '"not_interested", "unsubscribe", "out_of_office", "wrong_person", "other"], "summary": "one sentence in simple English: '
            'what they want and what we should do next"}')
    r = chat_json(system, user, writer=False, max_tokens=250)
    kind = r.get('kind') if r.get('kind') in ('interested', 'question', 'not_interested', 'unsubscribe', 'out_of_office', 'wrong_person', 'other') else 'other'
    return {'kind': kind, 'summary': str(r.get('summary') or '')[:400]}


def classify_reply_rules(subject, body):
    t = (subject + ' ' + body).lower()
    if re.search(r'\b(unsubscribe|remove me|stop emailing|do not contact|abmelden)\b', t):
        return {'kind': 'unsubscribe', 'summary': 'Asked not to be emailed again.'}
    if re.search(r'out of (the )?office|abwesen|auto.?reply|automatic reply|on leave|vacation', t):
        return {'kind': 'out_of_office', 'summary': 'Automatic out-of-office reply.'}
    if re.search(r'not interested|no thank|no need|kein interesse', t):
        return {'kind': 'not_interested', 'summary': 'Not interested.'}
    if re.search(r'price|quote|catalog|sample|send|interested|moq|minimum', t):
        return {'kind': 'interested', 'summary': 'Asks about prices, catalogue or samples.'}
    return {'kind': 'other', 'summary': 'Read and reply by hand.'}


def usage_summary(since_iso):
    rows = db.q("SELECT model, COUNT(*) calls, SUM(input_tokens) i, SUM(output_tokens) o FROM usage WHERE kind='ai' AND at>=? GROUP BY model", (since_iso,))
    fast, writer = db.get('ai_model_fast'), db.get('ai_model_writer')
    cost = 0.0
    calls = 0
    for r in rows:
        calls += r['calls']
        pre = 'price_writer' if r['model'] == writer else 'price_fast'
        cost += (r['i'] or 0) / 1e6 * db.get_float(pre + '_in') + (r['o'] or 0) / 1e6 * db.get_float(pre + '_out')
    places = db.q("SELECT COUNT(*) n FROM usage WHERE kind='places' AND at>=?", (since_iso,), one=True)['n']
    return {'ai_calls': calls, 'ai_cost': round(cost, 2), 'places_requests': places,
            'tokens_in': sum((r['i'] or 0) for r in rows), 'tokens_out': sum((r['o'] or 0) for r in rows)}
