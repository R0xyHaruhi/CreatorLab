from creatorlab.i18n import translate

def test_translation():
    assert translate('AI mode','zh') == 'AI 模式'
    assert translate('AI mode','en') == 'AI mode'
    assert translate('unknown','zh') == 'unknown'
