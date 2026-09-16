"""Run once, return a real process status, and exit."""
import argparse
import json
import logging
import os
from .core import ROOT, Source, init, upsert_source, sources, secret
from .config import load_settings, load_interests
from .builder import build

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',choices=['daily','weekly'],default='daily')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--force',action='store_true')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--persist-git',action='store_true')
    parser.add_argument('--collect-only',action='store_true',help='Browser and scoring diagnostics without a model or email')
    args=parser.parse_args(argv)
    if args.limit is not None and not 1<=args.limit<=600: parser.error('--limit must be between 1 and 600')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        s=load_settings(); cfg=load_interests(); init()
        configured=[Source.model_validate(item) for item in json.loads((ROOT/'config/sources.json').read_text(encoding='utf-8'))]
        ids={item.id for item in configured}
        if len(ids)!=len(configured): raise ValueError('Duplicate source IDs')
        for item in sources():
            if item['id'] not in ids: upsert_source(Source.model_validate(dict(item,enabled=False)))
        for item in configured: upsert_source(item)
        if not args.collect_only:
            missing=[]
            if not secret('api_key'): missing.append('OPENAI_API_KEY')
            if not s.model: missing.append('OPENAI_MODEL')
            if missing:
                logging.error('[CONFIG] missing=%s',','.join(missing))
                return 1
            if not args.dry_run:
                from .mailer import mail_ready
                missing=mail_ready(s)
                if missing:
                    logging.error('[CONFIG] mail setup incomplete: %s',', '.join(missing))
                    return 1
        build(s,cfg,args.kind,dry_run=args.dry_run or args.collect_only,force=args.force,limit=args.limit,persist_git=args.persist_git,collect_only=args.collect_only)
        return 0
    except Exception as exc:
        # No exception text or traceback: HTTP and SMTP libraries can embed credentials or private URLs.
        logging.error('[FATAL] %s; check configuration, stage counts and service availability',type(exc).__name__)
        return 1

if __name__=='__main__': raise SystemExit(main())
