import os
import subprocess
import sys

kind=os.getenv('INPUT_KIND') or ('weekly' if os.getenv('EVENT_SCHEDULE')=='0 1 * * 6' else 'daily')
args=[sys.executable,'-m','briefing.daily_brief','--kind',kind,'--persist-git']
if os.getenv('EVENT_NAME')=='workflow_dispatch':
    if os.getenv('INPUT_DRY_RUN','true')!='false': args.append('--dry-run')
    if os.getenv('INPUT_FORCE')=='true': args.append('--force')
    if os.getenv('INPUT_LIMIT'): args.extend(['--limit',os.environ['INPUT_LIMIT']])
raise SystemExit(subprocess.call(args))
