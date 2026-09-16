"""Optional syntax check for the retained local UI; Node is not a cloud runtime dependency."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

node=shutil.which('node')
if not node: raise SystemExit('Node not installed; optional local UI syntax check unavailable')
html=(Path(__file__).resolve().parents[1]/'web/index.html').read_text(encoding='utf-8')
scripts=re.findall(r'<script[^>]*>([\s\S]*?)</script>',html)
with tempfile.TemporaryDirectory(prefix='brief-js-') as directory:
    for index,script in enumerate(scripts):
        path=Path(directory)/f'inline-{index}.js'; path.write_text(script,encoding='utf-8')
        subprocess.run([node,'--check',str(path)],check=True)
print(f'{len(scripts)} inline scripts passed node --check')
