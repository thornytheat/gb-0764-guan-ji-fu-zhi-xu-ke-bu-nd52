from flask import Blueprint, current_app, render_template, request

from app.dispatch.journal import ledger
from app.problem import DeskError
from app.settings import EDITION
from app.source import bundle
from app.vault.record import index
from app.workflow import steps

desk = Blueprint('desk',__name__)
SECTIONS = {'balance':'签发请求对账','intake':'授权材料采信','registry':'刊号与机构映射','licenses':'许可版本裁决',
            'pages':'拆页与额度占用','volumes':'批次留档复跑','stamp':'许可证据签发'}


@desk.get('/')
@desk.get('/folio/<view>')
def folio(view='balance'):
    if view not in SECTIONS:
        raise DeskError('SAMPLE_UNKNOWN',404)
    sample = request.args.get('sample','dirty')
    data = steps(bundle(sample),view)
    volumes = index(current_app.vault) if view in ('volumes','stamp') else []
    active = request.args.get('run')
    shipment, shipment_error = None, None
    if view == 'stamp' and active:
        try:
            shipment = ledger(current_app.vault,active)
        except DeskError as exc:
            if exc.code not in ('DRAFT_ONLY','RUN_UNKNOWN','SEAL_INVALID'):
                raise
            shipment_error = exc
    return render_template('base.html', view=view, sections=SECTIONS, data=data, sample=sample,
                           volumes=volumes, active=active, shipment=shipment, shipment_error=shipment_error,
                           edition=EDITION)
