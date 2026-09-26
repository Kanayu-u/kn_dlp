"""SponsorBlock とダウンロード済みの記録のオプション組み立て(ネットワーク不要)。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kn_dlp import archive, options, updater

URL = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'


def opts(**job):
    return options.build_ydl_opts({'url': URL, 'out_dir': '.', **job})


def keys(o):
    return [p['key'] for p in o['postprocessors']]


class SponsorBlockTest(unittest.TestCase):
    def test_off_by_default(self):
        self.assertNotIn('SponsorBlock', keys(opts()))

    def test_mark(self):
        o = opts(sponsorblock='mark', sponsorblock_cats='sponsor,poi_highlight', chapters=False, metadata=False)
        k = keys(o)
        self.assertEqual(k[0], 'SponsorBlock')
        self.assertLess(k.index('ModifyChapters'), k.index('FFmpegMetadata'))
        sb = o['postprocessors'][0]
        self.assertEqual((sb['categories'], sb['when']), (['sponsor', 'poi_highlight'], 'after_filter'))
        mc = o['postprocessors'][k.index('ModifyChapters')]
        self.assertEqual(mc['remove_sponsor_segments'], [])
        meta = o['postprocessors'][k.index('FFmpegMetadata')]
        self.assertTrue(meta['add_chapters'])            # 印はチャプターとして書き込む
        self.assertFalse(meta['add_metadata'])

    def test_remove_after_embed_subs_before_metadata(self):
        o = opts(sponsorblock='remove', sponsorblock_cats='sponsor,selfpromo', subs=True, embed_subs=True, precise_cut=True)
        k = keys(o)
        self.assertLess(k.index('FFmpegEmbedSubtitle'), k.index('ModifyChapters'))
        mc = o['postprocessors'][k.index('ModifyChapters')]
        self.assertEqual((mc['remove_sponsor_segments'], mc['force_keyframes']), (['sponsor', 'selfpromo'], True))

    def test_invalid(self):
        for job in ({'sponsorblock': 'skip'}, {'sponsorblock': 'mark', 'sponsorblock_cats': 'ads'},
                    {'sponsorblock': 'remove', 'sponsorblock_cats': 'poi_highlight'},
                    {'sponsorblock': 'mark', 'sponsorblock_cats': ' , '}):
            with self.assertRaises(options.JobError, msg=job):
                opts(**job)


class ArchiveTest(unittest.TestCase):
    def test_opts(self):
        self.assertNotIn('download_archive', opts(use_archive=True))            # 場所が無い
        self.assertNotIn('download_archive', opts(archive_file='a.txt'))        # 使わない
        self.assertEqual(opts(use_archive=True, archive_file='a.txt')['download_archive'], 'a.txt')
        self.assertNotIn('download_archive', opts(use_archive=True, archive_file='a.txt', range_end='10'))

    def test_count_and_clear(self):
        with mock.patch.dict(os.environ, {'KN_DLP_DATA': tempfile.mkdtemp(prefix='kn_arc_')}):
            self.assertEqual(archive.count(), 0)
            archive.clear()                                                     # 無くても落ちない
            archive.path().write_text('youtube a\n\nyoutube b\n', encoding='utf-8')
            self.assertEqual(archive.count(), 2)
            archive.clear()
            self.assertEqual(archive.count(), 0)
            self.assertTrue(Path(str(archive.path()) + '.bak').is_file())


class AppUpdateTest(unittest.TestCase):
    def _fetch(self, payload: dict) -> dict:
        with mock.patch.object(updater, '_get', return_value=json.dumps(payload).encode()):
            return updater.fetch_app_latest()

    def test_parse(self):
        rel = self._fetch({'tag_name': 'v0.3.0', 'published_at': '2026-10-01T00:00:00Z',
                           'html_url': 'https://github.com/Kanayu-u/kn_dlp/releases/tag/v0.3.0'})
        self.assertEqual((rel['version'], rel['html_url']), ('0.3.0', 'https://github.com/Kanayu-u/kn_dlp/releases/tag/v0.3.0'))

    def test_foreign_page_is_not_used(self):
        rel = self._fetch({'tag_name': 'v0.3.0', 'html_url': 'https://evil.example/releases/'})
        self.assertEqual(rel['html_url'], 'https://github.com/Kanayu-u/kn_dlp/releases/latest')

    def test_bad_tag(self):
        for tag in ('nightly', '', 'v1'):
            with self.assertRaises(updater.UpdateError, msg=tag):
                self._fetch({'tag_name': tag})

    def test_compare(self):
        self.assertTrue(updater.is_newer('0.10.0', '0.2.0'))
        self.assertFalse(updater.is_newer('0.2.0', '0.2.0'))
        self.assertFalse(updater.is_newer('0.1.0', '0.2.0'))


if __name__ == '__main__':
    unittest.main()
