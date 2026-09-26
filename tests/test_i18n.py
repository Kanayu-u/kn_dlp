"""翻訳辞書の検査: 漏れ・余り・置換欄の食い違い。"""
import ast
import string
import unittest
from pathlib import Path

from kn_dlp import i18n
from kn_dlp.i18n import en, ko, zh_CN

ROOT = Path(__file__).resolve().parent.parent / 'kn_dlp'
TABLES = {'en': en.T, 'ko': ko.T, 'zh_CN': zh_CN.T}


def source_ids() -> set[str]:
    """コード中の tr('...') / N_('...') の原文を集める。"""
    ids = set()
    for f in ROOT.rglob('*.py'):
        if 'i18n' in f.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('tr', 'N_') and n.args \
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                ids.add(n.args[0].value)
    return ids


def fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


class I18nTest(unittest.TestCase):
    def test_tables_cover_all_ids(self):
        ids = source_ids()
        self.assertGreater(len(ids), 200)
        for code, table in TABLES.items():
            with self.subTest(code=code):
                self.assertEqual(sorted(ids - set(table)), [], 'untranslated')
                self.assertEqual(sorted(set(table) - ids), [], 'unused')

    def test_placeholders_match(self):
        for code, table in TABLES.items():
            for src, dst in table.items():
                with self.subTest(code=code, src=src):
                    self.assertEqual(fields(src), fields(dst))

    def test_tr_and_fallback(self):
        try:
            i18n.set_language('en')
            self.assertEqual(i18n.tr('キュー'), 'Queue')
            self.assertEqual(i18n.tr('[開始] {title}', title='x'), '[start] x')
            self.assertEqual(i18n.tr('未登録の文 {n}', n=1), '未登録の文 1')
        finally:
            i18n.set_language('ja')
        self.assertEqual(i18n.tr('キュー'), 'キュー')

    def test_normalize(self):
        self.assertEqual(i18n.normalize('ja_JP'), 'ja')
        self.assertEqual(i18n.normalize('zh-Hans-CN'), 'zh_CN')
        self.assertEqual(i18n.normalize('zh_TW'), 'zh_CN')
        self.assertEqual(i18n.normalize('ko-KR'), 'ko')
        self.assertEqual(i18n.normalize('fr_FR'), 'en')


if __name__ == '__main__':
    unittest.main()
