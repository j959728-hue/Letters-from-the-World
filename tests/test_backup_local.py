import json
from pathlib import Path

from scripts import backup_local


def test_sync_preserves_existing_backup(tmp_path, monkeypatch):
    destination = tmp_path / 'backups'
    destination.mkdir()
    (destination / '2026-09-21_世界来信-日报_甲.epub').write_bytes(b'original')

    def fake_gh(*args):
        if args[:2] == ('run', 'list'):
            return json.dumps([{'databaseId': 12, 'status': 'completed'},
                               {'databaseId': 13, 'status': 'in_progress'}])
        folder = Path(args[args.index('--dir') + 1]) / 'editions'
        for name,title in (('edition_1','甲'), ('edition_2','乙')):
            path = folder / name / f'2026-09-21_世界来信-日报_{title}.epub'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'new')
        return ''

    monkeypatch.setattr(backup_local, 'gh', fake_gh)
    sync_names = [p.name for p in backup_local.sync(destination)]
    assert sync_names == ['2026-09-21_世界来信-日报_乙.epub']
    assert (destination / '2026-09-21_世界来信-日报_甲.epub').read_bytes() == b'original'
    assert (destination / '2026-09-21_世界来信-日报_乙.epub').read_bytes() == b'new'
