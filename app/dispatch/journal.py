from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json

from app.certificate.slip import certificate
from app.pagination.spans import intersect, merge, pages_in, parse, subtract, union
from app.problem import DeskError
from app.vault.record import encode

MAX_ID = 64
MAX_LINES = 2000
NOTES = {'OUTSIDE_SIGNED':'越出实签页界，待馆员核查', 'UNKNOWN_ENTRY':'订单不在签发范围内，待馆员核查'}


def text(spans):
    if not spans:
        return '—'
    return '、'.join(str(start) if end-start == 1 else f'{start}–{end-1}' for start,end in spans)


def _identity(value):
    if not isinstance(value,str):
        raise DeskError('RECORD_BAD')
    value = value.strip()
    if not 1 <= len(value) <= MAX_ID or any(ord(character) < 32 for character in value):
        raise DeskError('RECORD_BAD')
    return value


def _day(value):
    if not isinstance(value,str):
        raise DeskError('RECORD_BAD')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DeskError('RECORD_BAD') from exc
    if parsed.isoformat() != value:
        raise DeskError('RECORD_BAD')
    return value


def _lines(value):
    if not isinstance(value,list) or not 1 <= len(value) <= MAX_LINES:
        raise DeskError('RECORD_BAD')
    merged = {}
    for line in value:
        if not isinstance(line,dict) or not isinstance(line.get('entry'),str):
            raise DeskError('RECORD_BAD')
        entry = _identity(line['entry'])
        try:
            spans = parse(line.get('pages'))
        except DeskError as exc:
            raise DeskError('RECORD_BAD') from exc
        merged[entry] = union(merged.get(entry,[]),spans)
    return {entry:merge(spans) for entry,spans in sorted(merged.items())}


def signed(vault, run):
    cert = certificate(vault,run)
    if not cert['verified']:
        raise DeskError('SEAL_INVALID',409)
    document = cert['document']
    revoked = {row['target'] for row in document.get('revocations',[]) if row.get('restored')}
    pages = {}
    for row in document.get('requests',[]):
        granted = [] if row['entry'] in revoked else [list(span) for span in row.get('granted',[])]
        pages[row['entry']] = merge(granted)
    return cert, pages


def _digest(kind, identity, day, lines):
    content = {kind:identity,'day':day,'lines':[{'entry':entry,'pages':spans} for entry,spans in lines.items()]}
    return sha256(encode(content).encode()).hexdigest()


def _record(kind, vault, run, identity, day, lines):
    digest = _digest(kind,identity,day,lines)
    if kind == 'batch':
        table, key, line_table, column = 'dispatch_batches', 'batch', 'dispatch_lines', 'sent_on'
    else:
        table, key, line_table, column = 'receipts', 'receipt', 'receipt_lines', 'received_on'
    with vault.session(immediate=True) as conn:
        existing = conn.execute(f'SELECT digest,{column},recorded_at FROM {table} WHERE volume=? AND {key}=?',
                                (run,identity)).fetchone()
        if existing:
            if existing[0] != digest:
                raise DeskError('RECORD_COLLISION',409)
            return {key:identity,'digest':existing[0],column:existing[1],'recorded_at':existing[2]}, True
        stamp = datetime.now(timezone.utc).isoformat()
        conn.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',(run,identity,digest,day,stamp))
        for entry,spans in lines.items():
            conn.execute(f'INSERT INTO {line_table} VALUES (?,?,?,?)',(run,identity,entry,json.dumps(spans)))
    return {key:identity,'digest':digest,column:day,'recorded_at':stamp}, False


def file_dispatch(vault, run, payload):
    if not isinstance(payload,dict):
        raise DeskError('RECORD_BAD')
    batch = _identity(payload.get('batch'))
    sent_on = _day(payload.get('sent_on'))
    lines = _lines(payload.get('lines'))
    _, pages = signed(vault,run)
    for entry,spans in lines.items():
        if entry not in pages:
            raise DeskError('UNKNOWN_ENTRY')
        if subtract(spans,pages[entry]):
            raise DeskError('UNSIGNED_PAGE')
    record, reused = _record('batch',vault,run,batch,sent_on,lines)
    return dict(record,run_id=run,reused=reused,summary=ledger(vault,run)['summary'])


def file_receipt(vault, run, payload):
    if not isinstance(payload,dict):
        raise DeskError('RECORD_BAD')
    receipt = _identity(payload.get('receipt'))
    received_on = _day(payload.get('received_on'))
    lines = _lines(payload.get('lines'))
    signed(vault,run)
    record, reused = _record('receipt',vault,run,receipt,received_on,lines)
    return dict(record,run_id=run,reused=reused,summary=ledger(vault,run)['summary'])


def _load(vault, run, table, key, line_table, date_column):
    with vault.session() as conn:
        records = conn.execute(f'SELECT {key},digest,{date_column},recorded_at FROM {table} '
                               f'WHERE volume=? ORDER BY {date_column},{key}',(run,)).fetchall()
        lines = conn.execute(f'SELECT {key},entry,pages FROM {line_table} WHERE volume=? ORDER BY {key},entry',
                             (run,)).fetchall()
    grouped = defaultdict(list)
    for record_id,entry,spans in lines:
        grouped[record_id].append({'entry':entry,'pages':json.loads(spans)})
    return records, grouped


def ledger(vault, run):
    cert, pages = signed(vault,run)
    batch_rows, batch_lines = _load(vault,run,'dispatch_batches','batch','dispatch_lines','sent_on')
    receipt_rows, receipt_lines = _load(vault,run,'receipts','receipt','receipt_lines','received_on')

    dispatched = defaultdict(list)
    batches = []
    for batch,digest,sent_on,recorded_at in batch_rows:
        lines = batch_lines.get(batch,[])
        entries = {}
        for line in lines:
            entries[line['entry']] = line['pages']
            dispatched[line['entry']] = union(dispatched[line['entry']],line['pages'])
        batches.append({'batch':batch,'digest':digest,'sent_on':sent_on,'recorded_at':recorded_at,
                        'lines':lines,'entries':entries,
                        'pages':sum(pages_in(line['pages']) for line in lines)})

    received = defaultdict(list)
    responses = {}
    receipts = []
    review = []
    for receipt,digest,received_on,recorded_at in receipt_rows:
        lines, accepted, outside_pages = [], 0, 0
        for line in receipt_lines.get(receipt,[]):
            entry, spans = line['entry'], line['pages']
            responses[entry] = max(responses.get(entry,received_on),received_on)
            if entry not in pages:
                review.append({'receipt':receipt,'entry':entry,'pages':spans,'text':text(spans),
                               'count':pages_in(spans),'reason':'UNKNOWN_ENTRY','note':NOTES['UNKNOWN_ENTRY']})
                outside_pages += pages_in(spans)
                continue
            outside = subtract(spans,pages[entry])
            if outside:
                review.append({'receipt':receipt,'entry':entry,'pages':outside,'text':text(outside),
                               'count':pages_in(outside),'reason':'OUTSIDE_SIGNED','note':NOTES['OUTSIDE_SIGNED']})
                outside_pages += pages_in(outside)
            inside = intersect(spans,pages[entry])
            received[entry] = union(received.get(entry,[]),inside)
            accepted += pages_in(inside)
            lines.append({'entry':entry,'pages':spans,'text':text(spans),'accepted':pages_in(inside),
                          'outside':pages_in(outside)})
        receipts.append({'receipt':receipt,'digest':digest,'received_on':received_on,'recorded_at':recorded_at,
                         'lines':lines,'accepted':accepted,'outside':outside_pages})

    orders = []
    for entry,signed_spans in pages.items():
        if not signed_spans:
            continue
        sent = intersect(dispatched.get(entry,[]),signed_spans)
        got = intersect(received.get(entry,[]),signed_spans)
        outstanding = subtract(signed_spans,got)
        response = responses.get(entry)
        transit = []
        for batch in batches:
            if entry in batch['entries'] and (response is None or batch['sent_on'] >= response):
                transit = union(transit,batch['entries'][entry])
        awaiting = intersect(transit,outstanding)
        resend = subtract(outstanding,awaiting)
        row = {'entry':entry,'last_receipt':response,'settled':not outstanding,
               'signed':signed_spans,'dispatched':sent,'received':got,'outstanding':outstanding,
               'awaiting':awaiting,'resend':resend}
        row['counts'] = {key:pages_in(row[key]) for key in
                         ('signed','dispatched','received','outstanding','awaiting','resend')}
        row['text'] = {key:text(row[key]) for key in
                       ('signed','dispatched','received','outstanding','awaiting','resend')}
        if row['settled']:
            row['status'] = '已结清'
        elif row['counts']['resend'] and not row['counts']['dispatched']:
            row['status'] = '未寄'
        elif row['counts']['resend']:
            row['status'] = '补寄'
        else:
            row['status'] = '等回执'
        orders.append(row)

    summary = {'signed':sum(row['counts']['signed'] for row in orders),
               'dispatched':sum(row['counts']['dispatched'] for row in orders),
               'received':sum(row['counts']['received'] for row in orders),
               'outstanding':sum(row['counts']['outstanding'] for row in orders),
               'awaiting':sum(row['counts']['awaiting'] for row in orders),
               'resend':sum(row['counts']['resend'] for row in orders),
               'review':sum(item['count'] for item in review),
               'orders':len(orders),'settled':sum(row['settled'] for row in orders),
               'batches':len(batches),'receipts':len(receipts)}
    summary['complete'] = summary['outstanding'] == 0
    return {'run_id':run,'imprint':cert['imprint'],'batches':batches,'receipts':receipts,
            'orders':orders,'review':review,'summary':summary}
