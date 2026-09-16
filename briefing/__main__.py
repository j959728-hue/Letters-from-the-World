import argparse
import json
import sys

from .core import init, sources, upsert_source, Source, db, DATA

def main():
    p=argparse.ArgumentParser(description='世界来信 · Kindle Briefing')
    p.add_argument('command',choices=['serve','collect','daily','weekly','sources','import-sources'])
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--file')
    args=p.parse_args(); init()
    if args.command=='serve':
        import uvicorn
        uvicorn.run('briefing.app:app',host='127.0.0.1',port=args.port,workers=1)
    elif args.command=='sources':
        print(json.dumps(sources(),ensure_ascii=False,indent=2))
    elif args.command=='import-sources':
        if not args.file: p.error('--file 必填')
        for item in json.loads(__import__('pathlib').Path(args.file).read_text(encoding='utf-8')):
            upsert_source(Source.model_validate(item))
    else:
        from .pipeline import enqueue
        jid=enqueue(args.command)
        print(json.dumps({'job_id':jid,'note':'任务已入队；启动 serve 后自动执行。防止与常驻进程并发运行。'},ensure_ascii=False))

if __name__=='__main__': main()
