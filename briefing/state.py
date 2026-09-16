"""Bounded metadata history and fail-closed delivery reservations."""
import json
import logging
import subprocess
from datetime import timedelta
from pathlib import Path
from .core import DATA, ROOT, atomic_json, iso, now, parse_time

class State:
    def __init__(self,path=None,days=14,max_events=700,persist_git=False):
        self.path=Path(path or DATA/'state.json'); self.days=days; self.max_events=max_events; self.persist_git=persist_git
        self.body=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'version':1,'history':[],'deliveries':{}}
        if self.body.get('version')!=1 or not isinstance(self.body.get('history'),list) or not isinstance(self.body.get('deliveries'),dict):
            raise ValueError('Invalid state schema; refusing to reset delivery history')

    @property
    def history(self): return self.body['history']

    def blocked(self,key): return key in self.body['deliveries']

    def prune(self,end=None):
        cutoff=(end or now())-timedelta(days=self.days)
        self.body['history']=[h for h in self.history if parse_time(h['sent_at'])>=cutoff][-self.max_events:]
        self.body['deliveries']={k:v for k,v in self.body['deliveries'].items() if parse_time(v['updated'])>=cutoff}

    def save(self):
        self.prune(); atomic_json(self.path,self.body)
        if self.persist_git: self.commit()

    def commit(self):
        if self.path.resolve()!= (ROOT/'data/state.json').resolve(): raise ValueError('Git state path must be data/state.json')
        def git(*args):
            p=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True,timeout=90)
            if p.returncode: raise RuntimeError('State Git operation failed: '+args[0])
            return p.stdout.strip()
        if Path(git('rev-parse','--show-toplevel')).resolve()!=ROOT.resolve(): raise ValueError('State must use its own repository root')
        git('add','--','data/state.json')
        # Refuse to accidentally commit another staged file.
        changed=git('diff','--cached','--name-only').splitlines()
        if any(p!='data/state.json' for p in changed): raise ValueError('Unexpected staged files; refusing state commit')
        if changed:
            git('-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit','-m','chore: update daily brief state')
        # Push also retries a previously committed but unpushed reservation.
        git('push','origin','HEAD')
        logging.info('[STATE] durable checkpoint saved')

    def reserve(self,key,force=False):
        if self.blocked(key) and not force: raise ValueError('Delivery already reserved or accepted; use --force only after checking')
        old=self.body['deliveries'].get(key,{})
        self.body['deliveries'][key]={'status':'sending','updated':iso(),'attempt':old.get('attempt',0)+1}
        self.save()  # MUST complete remote push before SMTP DATA can be sent.

    def finish(self,key,status,records=()):
        self.body['deliveries'][key]['status']=status
        self.body['deliveries'][key]['updated']=iso()
        replacements={(h.get('delivery_id'),h['fingerprint']) for h in records}
        self.body['history']=[h for h in self.history if (h.get('delivery_id'),h.get('fingerprint')) not in replacements]+list(records)
        self.save()
