from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3


class Vault:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.session(immediate=True) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS volumes (id TEXT PRIMARY KEY, manifest TEXT NOT NULL, evidence TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS slips (id TEXT PRIMARY KEY REFERENCES volumes(id), digest TEXT NOT NULL, body TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS dispatch_batches (volume TEXT NOT NULL REFERENCES volumes(id), batch TEXT NOT NULL, digest TEXT NOT NULL, sent_on TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY (volume,batch))')
            conn.execute('CREATE TABLE IF NOT EXISTS dispatch_lines (volume TEXT NOT NULL, batch TEXT NOT NULL, entry TEXT NOT NULL, pages TEXT NOT NULL, PRIMARY KEY (volume,batch,entry), FOREIGN KEY (volume,batch) REFERENCES dispatch_batches(volume,batch) ON DELETE CASCADE)')
            conn.execute('CREATE TABLE IF NOT EXISTS receipts (volume TEXT NOT NULL REFERENCES volumes(id), receipt TEXT NOT NULL, digest TEXT NOT NULL, received_on TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY (volume,receipt))')
            conn.execute('CREATE TABLE IF NOT EXISTS receipt_lines (volume TEXT NOT NULL, receipt TEXT NOT NULL, entry TEXT NOT NULL, pages TEXT NOT NULL, PRIMARY KEY (volume,receipt,entry), FOREIGN KEY (volume,receipt) REFERENCES receipts(volume,receipt) ON DELETE CASCADE)')
            conn.execute('CREATE INDEX IF NOT EXISTS dispatch_lines_volume ON dispatch_lines(volume,entry)')
            conn.execute('CREATE INDEX IF NOT EXISTS receipt_lines_volume ON receipt_lines(volume,entry)')

    @contextmanager
    def session(self, immediate=False):
        connection = sqlite3.connect(self.path,timeout=10,isolation_level=None if immediate else '')
        with closing(connection) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            if not immediate:
                with conn:
                    yield conn
                return
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield conn
                conn.execute('COMMIT')
            except BaseException:
                if conn.in_transaction:
                    conn.execute('ROLLBACK')
                raise
