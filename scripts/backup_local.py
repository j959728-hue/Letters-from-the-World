"""Download generated EPUBs from GitHub Actions to this computer.

Requires GitHub CLI (`gh auth login`). Files are never overwritten.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = 'j959728-hue/Letters-from-the-World'


def gh(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, check=True)
    return result.stdout


def sync(destination, repo=REPO, limit=30):
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    runs = json.loads(gh('run', 'list', '--repo', repo, '--workflow', 'daily-brief.yml',
                         '--limit', str(limit), '--json', 'databaseId,status'))
    saved = []
    for run in runs:
        if run['status'] != 'completed':
            continue
        run_id = str(run['databaseId'])
        with tempfile.TemporaryDirectory(prefix='brief-backup-') as temp:
            try:
                gh('run', 'download', run_id, '--repo', repo,
                   '--name', f'kindle-brief-{run_id}', '--dir', temp)
            except subprocess.CalledProcessError:
                # A run can fail before rendering and therefore have no EPUB artifact.
                continue
            for epub in (Path(temp) / 'editions').glob('*/briefing.epub'):
                edition_id = epub.parent.name
                if not edition_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in edition_id):
                    continue
                target = destination / f'{edition_id}.epub'
                if not target.exists():
                    shutil.copy2(epub, target)
                    saved.append(target)
    return saved


def main():
    parser = argparse.ArgumentParser(description='Back up GitHub Actions EPUBs locally')
    parser.add_argument('--dest', default=str(Path.home() / 'Documents' / 'Letters-from-the-World' / 'backups'))
    parser.add_argument('--repo', default=REPO)
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()
    try:
        for path in sync(args.dest, args.repo, args.limit):
            print(path)
    except FileNotFoundError:
        parser.exit(1, '请先安装 GitHub CLI (gh)，并运行 gh auth login。\n')
    except subprocess.CalledProcessError:
        parser.exit(1, '无法读取 GitHub Actions；请检查 gh auth status 和仓库访问权限。\n')


if __name__ == '__main__':
    main()
