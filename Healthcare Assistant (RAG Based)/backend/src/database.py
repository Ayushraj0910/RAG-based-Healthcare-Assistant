import sqlite3
from pathlib import Path
import pandas as pd
class PatientDatabase:
    def __init__(self,csv_path:Path,db_path:Path):
        self.csv_path,self.db_path=csv_path,db_path
        self._ensure_db()
    def _ensure_db(self):
        if not self.db_path.exists():
            df=pd.read_csv(self.csv_path)
            df.columns=[c.lower().replace(' ','_') for c in df.columns]
            con=sqlite3.connect(self.db_path); df.to_sql('patients',con,index=False,if_exists='replace'); con.close()
    def execute(self,sql):
        sql=sql.strip().rstrip(';'); low=sql.lower()
        if not low.startswith('select'): raise ValueError('Only SELECT statements are allowed.')
        if any(x in low for x in ['insert ','update ','delete ','drop ','alter ','attach ','pragma ','replace ']): raise ValueError('Unsafe SQL operation blocked.')
        con=sqlite3.connect(self.db_path); con.row_factory=sqlite3.Row
        try: return [dict(r) for r in con.execute(sql).fetchall()]
        finally: con.close()
    def stats(self):
        con=sqlite3.connect(self.db_path); n=con.execute('SELECT COUNT(*) FROM patients').fetchone()[0]; con.close(); return n
