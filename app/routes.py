from flask import Blueprint, current_app, jsonify, request

from app.certificate.slip import certificate, stamp
from app.dispatch.journal import file_dispatch, file_receipt, ledger
from app.problem import DeskError
from app.source import read_request
from app.vault.record import deposit, index, volume
from app.workflow import steps

rights = Blueprint('rights',__name__)


def review(name):
    return steps(read_request(),name)[name]


@rights.route('/api/intake',methods=['GET','POST'])
def intake():
    return review('intake')


@rights.route('/api/registry',methods=['GET','POST'])
def registry():
    return review('registry')


@rights.route('/api/licenses',methods=['GET','POST'])
def choose():
    return review('licenses')


@rights.route('/api/pages',methods=['GET','POST'])
def pages():
    return review('pages')


@rights.route('/api/balance',methods=['GET','POST'])
def balance():
    return review('balance')


@rights.get('/api/volumes')
def volumes():
    return {'volumes':index(current_app.vault)}


@rights.post('/api/volumes')
def file():
    result = deposit(current_app.vault,read_request())
    return result,200 if result['reused'] else 201


@rights.get('/api/volumes/<run>')
def get_volume(run):
    return volume(current_app.vault,run)


@rights.post('/api/volumes/<run>/stamp')
def issue(run):
    return stamp(current_app.vault,run)


@rights.get('/api/volumes/<run>/dispatch')
def dispatch_ledger(run):
    return ledger(current_app.vault,run)


def record(handler, run):
    payload = request.get_json(silent=True)
    if not isinstance(payload,dict):
        raise DeskError('RECORD_BAD')
    result = handler(current_app.vault,run,payload)
    return result,200 if result['reused'] else 201


@rights.post('/api/volumes/<run>/dispatch')
def dispatch(run):
    return record(file_dispatch,run)


@rights.post('/api/volumes/<run>/receipt')
def receipt(run):
    return record(file_receipt,run)


@rights.get('/api/volumes/<run>/export')
def download(run):
    result = jsonify(certificate(current_app.vault,run))
    result.headers['Content-Disposition'] = f'attachment; filename="license-{run}.json"'
    return result
