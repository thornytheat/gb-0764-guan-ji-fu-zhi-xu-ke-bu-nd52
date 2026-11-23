from concurrent.futures import ThreadPoolExecutor

from app.dispatch.journal import file_dispatch, file_receipt, ledger


def stamped(client):
    run = client.post('/api/volumes',json={'sample':'dirty'}).json['run_id']
    client.post(f'/api/volumes/{run}/stamp')
    return '/api/volumes/'+run


def dispatch(client, address, batch, day, lines):
    return client.post(address+'/dispatch',json={'batch':batch,'sent_on':day,'lines':lines})


def receipt(client, address, name, day, lines):
    return client.post(address+'/receipt',json={'receipt':name,'received_on':day,'lines':lines})


def order(client, address, entry):
    return next(row for row in client.get(address+'/dispatch').json['orders'] if row['entry']==entry)


def test_registration_requires_signed_voucher(client):
    run = client.post('/api/volumes',json={'sample':'dirty'}).json['run_id']
    address = '/api/volumes/'+run
    assert dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-11'}]).json['error']=='DRAFT_ONLY'
    assert receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-9'}]).json['error']=='DRAFT_ONLY'


def test_reported_short_pages_only_are_resent(client):
    address = stamped(client)
    assert dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-11'}]).status_code == 201
    sent = receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-9'}])
    assert sent.status_code == 201
    row = order(client,address,'C02')
    assert row['counts']['received']==2 and row['counts']['outstanding']==2
    assert row['text']['awaiting']=='—' and row['text']['resend']=='10–11'
    assert row['status']=='补寄'


def test_late_receipt_closes_pages_already_received(client):
    address = stamped(client)
    dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-11'}])
    receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-9'}])
    dispatch(client,address,'B2','2026-11-13',[{'entry':'C02','pages':'10-11'}])
    assert order(client,address,'C02')['status']=='等回执'
    late = receipt(client,address,'K2','2026-11-14',[{'entry':'C02','pages':'8-11'}])
    assert late.status_code == 201
    row = order(client,address,'C02')
    assert (row['settled'],row['counts']['received'],row['counts']['outstanding'])==(True,4,0)
    assert row['text']['resend']=='—' and row['text']['awaiting']=='—'


def test_in_flight_batch_waits_for_receipt_before_resend(client):
    address = stamped(client)
    dispatch(client,address,'B1','2026-11-11',[{'entry':'C03','pages':'14-19'}])
    row = order(client,address,'C03')
    assert row['counts']['awaiting']==6 and row['counts']['resend']==0
    assert row['status']=='等回执'


def test_same_page_on_two_receipts_is_received_once(client):
    address = stamped(client)
    receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-11'}])
    receipt(client,address,'K2','2026-11-13',[{'entry':'C02','pages':'8-11'}])
    row = order(client,address,'C02')
    assert (row['counts']['received'],row['counts']['outstanding'])==(4,0)
    assert client.get(address+'/dispatch').json['summary']['received']==4


def test_concurrent_duplicate_receipt_settles_once(desk):
    run = desk.test_client().post('/api/volumes',json={'sample':'dirty'}).json['run_id']
    desk.test_client().post(f'/api/volumes/{run}/stamp')
    payload = {'receipt':'K1','received_on':'2026-11-12','lines':[{'entry':'C02','pages':'8-11'}]}
    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(lambda _: file_receipt(desk.vault,run,payload),range(10)))
    assert sum(not item['reused'] for item in results)==1
    summary = ledger(desk.vault,run)['summary']
    assert summary['receipts']==1 and summary['received']==4


def test_concurrent_distinct_receipts_do_not_double_count(desk):
    run = desk.test_client().post('/api/volumes',json={'sample':'dirty'}).json['run_id']
    desk.test_client().post(f'/api/volumes/{run}/stamp')
    def record(index):
        return file_receipt(desk.vault,run,{'receipt':f'K{index}','received_on':'2026-11-12',
                                            'lines':[{'entry':'C02','pages':'8-11'}]})
    with ThreadPoolExecutor(5) as pool:
        list(pool.map(record,range(10)))
    summary = ledger(desk.vault,run)['summary']
    assert summary['receipts']==10 and summary['received']==4


def test_retrying_same_receipt_keeps_ledger_unchanged(client):
    address = stamped(client)
    first = receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-10'}])
    before = client.get(address+'/dispatch').json['summary']
    retry = receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-10'}])
    assert (retry.status_code,retry.json['reused'])==(200,True)
    assert client.get(address+'/dispatch').json['summary']==before
    assert before['received']==3


def test_same_receipt_with_new_content_is_refused(client):
    address = stamped(client)
    receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-10'}])
    clash = receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-11'}])
    assert (clash.status_code,clash.json['error'])==(409,'RECORD_COLLISION')
    assert order(client,address,'C02')['counts']['received']==3


def test_receipt_pages_beyond_signed_range_go_to_review(client):
    address = stamped(client)
    reply = receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-20'}])
    assert reply.status_code == 201
    review = client.get(address+'/dispatch').json['review']
    assert [(item['entry'],item['reason'],item['text']) for item in review]==[('C02','OUTSIDE_SIGNED','12–20')]
    row = order(client,address,'C02')
    assert (row['counts']['received'],row['settled'])==(4,True)


def test_receipt_for_unissued_identifier_is_held_for_review(client):
    address = stamped(client)
    reply = receipt(client,address,'K1','2026-11-12',[{'entry':'C99','pages':'1-2'}])
    assert reply.status_code == 201
    review = client.get(address+'/dispatch').json['review']
    assert [(item['entry'],item['reason']) for item in review]==[('C99','UNKNOWN_ENTRY')]
    assert client.get(address+'/dispatch').json['summary']['received']==0


def test_dispatch_outside_signed_pages_is_refused(client):
    address = stamped(client)
    assert dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-13'}]).json['error']=='UNSIGNED_PAGE'
    assert dispatch(client,address,'B1','2026-11-11',[{'entry':'C99','pages':'1-2'}]).json['error']=='UNKNOWN_ENTRY'
    assert client.get(address+'/dispatch').json['batches']==[]


def test_revoked_order_cannot_be_dispatched(client):
    address = stamped(client)
    assert dispatch(client,address,'B1','2026-11-11',[{'entry':'C01','pages':'3-8'}]).json['error']=='UNSIGNED_PAGE'
    assert 'C01' not in [row['entry'] for row in client.get(address+'/dispatch').json['orders']]


def test_ledger_keeps_signed_pages_balanced(client):
    address = stamped(client)
    dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-11'},{'entry':'C03','pages':'14-19'}])
    receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-9'}])
    summary = client.get(address+'/dispatch').json['summary']
    assert summary['signed']==summary['received']+summary['outstanding']==26
    assert summary['awaiting']+summary['resend']==summary['outstanding']


def test_registration_rejects_malformed_payloads(client):
    address = stamped(client)
    cases = [
        dispatch(client,address,'','2026-11-11',[{'entry':'C02','pages':'8-9'}]),
        dispatch(client,address,'B1','11/11/2026',[{'entry':'C02','pages':'8-9'}]),
        dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'9-8'}]),
        dispatch(client,address,'B1','2026-11-11',[]),
        receipt(client,address,'K1','2026-11-12',[{'entry':'C02'}]),
        client.post(address+'/receipt',json=[]),
    ]
    assert {response.json['error'] for response in cases}=={'RECORD_BAD'}
    assert client.get(address+'/dispatch').json['batches']==[]


def test_dispatch_page_is_available_after_stamping(client):
    address = stamped(client)
    receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-9'}])
    page = client.get('/folio/stamp?run='+address.rsplit('/',1)[-1]).get_data(as_text=True)
    assert '寄送与回执登记' in page and '可补寄' in page and '等回执' in page
    assert '签发后在此登记' not in page


def test_unknown_volume_page_shows_message(client):
    page = client.get('/folio/stamp?run=missing').get_data(as_text=True)
    assert '未找到许可批次' in page


def test_tampered_voucher_blocks_registration(client,desk):
    address = stamped(client)
    with desk.vault.session() as conn:
        conn.execute("UPDATE slips SET body='{}'")
    assert dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-11'}]).json['error']=='SEAL_INVALID'
    assert receipt(client,address,'K1','2026-11-12',[{'entry':'C02','pages':'8-11'}]).json['error']=='SEAL_INVALID'
    assert client.get(address+'/dispatch').json['error']=='SEAL_INVALID'


def test_registration_is_kept_per_volume(client):
    first = stamped(client)
    dispatch(client,first,'B1','2026-11-11',[{'entry':'C02','pages':'8-11'}])
    source = client.get('/api/volumes').json['volumes'][0]
    second = '/api/volumes/'+client.post('/api/volumes',json={'sample':'clean'}).json['run_id']
    client.post(second+'/stamp')
    receipt(client,second,'B1','2026-11-12',[{'entry':'C04','pages':'8-10'}])
    assert client.get(first+'/dispatch').json['summary']['batches']==1
    assert client.get(second+'/dispatch').json['summary']['receipts']==1
    assert source['run_id'] in first


def test_folio_does_not_advance_signed_state(client):
    address = stamped(client)
    before = client.get(address+'/dispatch').json['summary']
    client.get('/folio/stamp?run='+address.rsplit('/',1)[-1])
    assert client.get(address+'/dispatch').json['summary']==before


def test_page_set_algebra_shared_by_ledger():
    from app.pagination.spans import intersect, subtract, union
    assert union([[1,4]],[[3,6]])==[[1,6]]
    assert intersect([[1,5],[8,10]],[[4,9]])==[[4,5],[8,9]]
    assert subtract([[1,9]],[[3,5],[8,10]])==[[1,3],[5,8]]
    assert subtract([[1,4]],[[1,4]])==[]


def test_receipt_for_revoked_order_is_held_for_review(client):
    address = stamped(client)
    reply = receipt(client,address,'K1','2026-11-12',[{'entry':'C01','pages':'3-8'}])
    assert reply.status_code == 201
    review = client.get(address+'/dispatch').json['review']
    assert [(item['entry'],item['reason']) for item in review]==[('C01','OUTSIDE_SIGNED')]
    assert client.get(address+'/dispatch').json['summary']['received']==0


def test_same_batch_number_with_new_lines_is_refused(client):
    address = stamped(client)
    dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-9'}])
    clash = dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-10'}])
    assert (clash.status_code,clash.json['error'])==(409,'RECORD_COLLISION')
    assert order(client,address,'C02')['counts']['dispatched']==2


def test_repeated_lines_in_one_record_are_merged(client):
    address = stamped(client)
    dispatch(client,address,'B1','2026-11-11',[{'entry':'C02','pages':'8-9'},{'entry':'C02','pages':'9-11'}])
    batches = client.get(address+'/dispatch').json['batches']
    assert batches[0]['lines'][0]['pages']==[[8,12]] and batches[0]['pages']==4
