from briefing.naming import edition_filename


def test_readable_safe_name():
    edition={'delivery_id':'weekly:2026-09-19','kind':'weekly','stories':[{'title':'美／伊：冲突？回顾/观察'}]}
    name=edition_filename(edition)
    assert name.startswith('2026-09-19_世界来信-周报_')
    assert '/' not in name and ':' not in name and name.endswith('.epub')
