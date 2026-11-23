from datetime import date

from app.pagination.spans import PAGE_SYNTAX, parse
from app.problem import DeskError
from app.intake.spec import SENTINELS


def order(line, row):
    fields = ['entry','action','received','institution']
    fields += ['issn','pages'] if row['action']=='copy' else ['target']
    if any(not row[key] or row[key] in SENTINELS for key in fields):
        raise ValueError('MISSING')
    try:
        received = date.fromisoformat(row['received']).isoformat()
        if received != row['received']:
            raise ValueError
        if row['action'] == 'copy':
            if row['target'] or len(row['pages']) > 512 or not PAGE_SYNTAX.fullmatch(row['pages']):
                raise ValueError
            try:
                parse(row['pages'])
            except DeskError as exc:
                raise ValueError from exc
        elif row['action'] != 'cancel' or row['issn'] or row['pages']:
            raise ValueError
    except ValueError as exc:
        raise ValueError('INVALID') from exc
    return dict(row, line=line)
