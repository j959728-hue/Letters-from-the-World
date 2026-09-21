"""Publish an explicit allowlist; never upload DB, raw HTML sources, settings or secrets."""
from pathlib import Path
import json
import shutil
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from briefing.naming import edition_filename

dest=root/'test-results/artifacts'; dest.mkdir(parents=True,exist_ok=True)
for edition in (root/'data/editions').glob('*'):
    manifest=edition/'manifest.json'
    obj=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else None
    for name in ('index.html','briefing.epub'):
        p=edition/name
        if p.is_file():
            target=dest/'editions'/edition.name/(edition_filename(obj) if name=='briefing.epub' and obj else name)
            target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,target)
    if obj:
        for story in obj['stories']:
            for e in story['evidence']:
                p=(root/'data'/e['image']).resolve()
                if p.is_relative_to((root/'data/evidence').resolve()) and p.suffix=='.png':
                    target=dest/e['image']; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,target)
for p in (root/'data/jobs').glob('*.stats.json'): shutil.copy2(p,dest/p.name)
for p in (root/'data/jobs').glob('*.scores.json'): shutil.copy2(p,dest/p.name)
