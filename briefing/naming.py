"""One readable, filesystem-safe name for mail attachments and downloaded copies."""
import re
import unicodedata


def edition_filename(edition):
    day=edition.get('delivery_id','').split(':')[-1]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
        day=str(edition.get('end',''))[:10] or 'undated'
    kind='周报' if edition.get('kind')=='weekly' else '日报'
    title=edition.get('stories',[{}])[0].get('title','本期要闻') if edition.get('stories') else '本期要闻'
    title=unicodedata.normalize('NFKC',title)
    title=re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+',' ',title)
    title=re.sub(r'\s+',' ',title).strip(' ._-')[:36].rstrip(' ._-') or '本期要闻'
    return f'{day}_世界来信-{kind}_{title}.epub'
