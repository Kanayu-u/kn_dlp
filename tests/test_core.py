"""ネットワーク・Qt 不要の単体テスト。`python -m unittest discover -s tests`"""
import io
import math
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='kn_dlp_test_')
os.environ['KN_DLP_DATA'] = _TMP

from kn_dlp import bootstrap, errors, options, paths, updater  # noqa: E402
from kn_dlp.history import History  # noqa: E402
from kn_dlp.settings import Settings  # noqa: E402
from kn_dlp.timeparse import format_seconds, parse_timestamp  # noqa: E402

URL = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'


def _make_pyz(path: Path, version: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('yt_dlp/version.py', f"__version__ = '{version}'\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'#!/usr/bin/env python3\n' + buf.getvalue())


class TimeParseTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_timestamp('90'), 90)
        self.assertEqual(parse_timestamp('1:23'), 83)
        self.assertEqual(parse_timestamp('01:02:03.5'), 3723.5)
        self.assertIsNone(parse_timestamp('  '))

    def test_invalid(self):
        for bad in ('1:60', 'a:10', '1:2:3:4', '-5'):
            with self.assertRaises(ValueError, msg=bad):
                parse_timestamp(bad)

    def test_format(self):
        self.assertEqual(format_seconds(83), '1:23')
        self.assertEqual(format_seconds(3723), '1:02:03')
        self.assertEqual(format_seconds(None), '--:--')


class OptionsTest(unittest.TestCase):
    def test_video_quality_and_mp4(self):
        o = options.build_ydl_opts({'url': URL, 'quality': '1080', 'container': 'mp4'})
        self.assertIn('height<=1080', o['format'])
        self.assertEqual(o['format_sort'], ['ext:mp4:m4a'])
        self.assertEqual(o['merge_output_format'], 'mp4')
        self.assertTrue(o['noplaylist'])

    def test_audio(self):
        o = options.build_ydl_opts({'url': URL, 'mode': 'audio', 'audio_codec': 'mp3', 'embed_thumbnail': True})
        keys = [p['key'] for p in o['postprocessors']]
        self.assertEqual(keys[0], 'FFmpegThumbnailsConvertor')
        self.assertIn('FFmpegExtractAudio', keys)
        self.assertEqual(keys[-1], 'EmbedThumbnail')
        self.assertTrue(o['writethumbnail'])
        self.assertNotIn('merge_output_format', o)

    def test_range(self):
        o = options.build_ydl_opts({'url': URL, 'range_start': '0:05', 'range_end': '0:10', 'precise_cut': True})
        self.assertEqual(o['download_ranges']({'duration': 19}, None), [{'start_time': 5, 'end_time': 10}])
        self.assertTrue(o['force_keyframes_at_cuts'])
        self.assertIn('%(section_start)d', o['outtmpl']['default'])
        o = options.build_ydl_opts({'url': URL, 'range_start': '5'})
        self.assertEqual(o['download_ranges']({'duration': 19}, None)[0]['end_time'], 19)
        self.assertEqual(o['download_ranges']({}, None)[0]['end_time'], math.inf)

    def test_subs_cookies_live_js(self):
        o = options.build_ydl_opts({'url': URL, 'subs': True, 'sub_langs': 'ja, en,', 'cookies_browser': 'firefox',
                                    'wait_live': True, 'wait_retry_sec': 5,
                                    'js_runtime': {'name': 'node', 'path': 'C:/n/node.exe'}, 'rate_limit': '2M'})
        self.assertEqual(o['subtitleslangs'], ['ja', 'en'])
        self.assertIn('FFmpegEmbedSubtitle', [p['key'] for p in o['postprocessors']])
        self.assertEqual(o['cookiesfrombrowser'], ('firefox', None, None, None))
        self.assertEqual(o['wait_for_video'], (15, 15))
        self.assertEqual(o['js_runtimes'], {'node': {'path': 'C:/n/node.exe'}})
        self.assertEqual(o['ratelimit'], 2 * 1024 * 1024)

    def test_cookie_file_wins(self):
        o = options.build_ydl_opts({'url': URL, 'cookies_browser': 'firefox', 'cookies_file': 'c.txt'})
        self.assertEqual(o['cookiefile'], 'c.txt')
        self.assertNotIn('cookiesfrombrowser', o)

    def test_validation(self):
        bad = [{'url': ''}, {'url': 'file:///etc/passwd'}, {'url': URL, 'template': '../x.%(ext)s'},
               {'url': URL, 'template': 'C:/x.%(ext)s' if os.name == 'nt' else '/x.%(ext)s'},
               {'url': URL, 'range_start': '10', 'range_end': '5'}, {'url': URL, 'cookies_browser': 'ie'},
               {'url': URL, 'quality': 'custom'}, {'url': URL, 'rate_limit': 'fast'}]
        for job in bad:
            with self.assertRaises(options.JobError, msg=job):
                options.build_ydl_opts(job)

    def test_probe_strips_download_parts(self):
        o = options.build_probe_opts({'url': URL, 'subs': True, 'range_start': '1', 'wait_live': True})
        for k in ('postprocessors', 'download_ranges', 'writesubtitles', 'wait_for_video'):
            self.assertNotIn(k, o)
        self.assertEqual(o['extract_flat'], 'in_playlist')
        self.assertTrue(o['ignore_no_formats_error'])


class WorkerTest(unittest.TestCase):
    def test_pop_postprocessor(self):
        from kn_dlp.worker import _pop_postprocessor
        opts = options.build_ydl_opts({"url": URL, "mode": "audio", "audio_codec": "opus", "embed_thumbnail": True})
        args = _pop_postprocessor(opts, 'EmbedThumbnail')
        self.assertEqual(args, {'already_have_thumbnail': False})
        self.assertNotIn('EmbedThumbnail', [pp['key'] for pp in opts['postprocessors']])
        self.assertIsNone(_pop_postprocessor(opts, 'EmbedThumbnail'))


class ErrorsTest(unittest.TestCase):
    def test_known(self):
        self.assertEqual(errors.explain("ERROR: [youtube] x: Sign in to confirm you're not a bot")[0],
                         'ログイン確認を求められました')
        self.assertIn('403', errors.explain('ERROR: unable to download video data: HTTP Error 403: Forbidden')[0])

    def test_unknown_strips_prefix(self):
        self.assertEqual(errors.explain('ERROR: [generic] abc: something odd\nmore')[0], 'something odd')


class BootstrapTest(unittest.TestCase):
    def test_newest_wins(self):
        _make_pyz(paths.updated_ytdlp(), '2099.01.01')
        chosen = bootstrap.select_pyz()
        self.assertEqual(chosen[1], '2099.01.01')
        _make_pyz(paths.updated_ytdlp(), '2000.01.01')
        chosen = bootstrap.select_pyz()
        self.assertNotEqual(chosen[1], '2000.01.01')  # 同梱版の方が新しい
        paths.updated_ytdlp().unlink()

    def test_broken_pyz_ignored(self):
        paths.updated_ytdlp().parent.mkdir(parents=True, exist_ok=True)
        paths.updated_ytdlp().write_bytes(b'not a zip')
        self.assertIsNone(bootstrap.read_pyz_version(paths.updated_ytdlp()))
        paths.updated_ytdlp().unlink()

    def test_version_key(self):
        self.assertGreater(bootstrap.version_key('2026.08.19.232826'), bootstrap.version_key('2026.08.19'))
        self.assertTrue(updater.is_newer('2026.09.01', '2026.08.19'))
        self.assertFalse(updater.is_newer('2026.08.19', '2026.08.19'))


class UpdaterTest(unittest.TestCase):
    def test_parse_sums(self):
        h = 'a' * 64
        text = f'{"b" * 64}  yt-dlp.exe\n{h}  yt-dlp\n'
        self.assertEqual(updater.parse_sums(text), h)
        with self.assertRaises(updater.UpdateError):
            updater.parse_sums(text, 'nothing')

    def test_url_allowlist(self):
        updater._check_url('https://github.com/yt-dlp/yt-dlp/releases/download/x/yt-dlp')
        for bad in ('http://github.com/x', 'https://evil.example/yt-dlp', 'file:///c:/x'):
            with self.assertRaises(updater.UpdateError):
                updater._check_url(bad)

    def test_rollback(self):
        target = paths.updated_ytdlp()
        _make_pyz(target.with_suffix('.pyz.bak'), '2098.01.01')
        _make_pyz(target, '2099.01.01')
        self.assertEqual(updater.backup_version(), '2098.01.01')
        self.assertEqual(updater.rollback(), '2098.01.01')
        self.assertIsNone(updater.backup_version())
        updater.reset_to_bundled()
        self.assertFalse(target.exists())


class SettingsHistoryTest(unittest.TestCase):
    def test_settings_roundtrip_and_profiles(self):
        path = Path(_TMP) / 's.json'
        s = Settings(path)
        s['concurrency'] = 4
        s.save_profile('mine', dict(options.JOB_DEFAULTS, mode='audio', url='x', cookies_browser='firefox'))
        s2 = Settings(path)
        self.assertEqual(s2['concurrency'], 4)
        prof = s2.get_profile('mine')
        self.assertEqual(prof['mode'], 'audio')
        self.assertNotIn('url', prof)
        self.assertNotIn('cookies_browser', prof)
        with self.assertRaises(ValueError):
            s2.delete_profile(next(iter(s2.profile_ids())))
        with self.assertRaises(ValueError):   # 組み込みの表示名・ID と同じ名前は付けられない
            s2.save_profile('標準 (動画・最高画質)', {})
        with self.assertRaises(ValueError):
            s2.save_profile('builtin:x', {})
        self.assertEqual(s2.profile_ids()[-1], 'mine')

    def test_settings_migrates_legacy_profile_name(self):
        path = Path(_TMP) / 'legacy.json'
        path.write_text('{"last_profile": "音楽 (MP3・サムネ埋め込み)", "theme": "neon", "language": "xx"}', encoding='utf-8')
        s = Settings(path)
        self.assertEqual(s['last_profile'], 'builtin:music')
        self.assertEqual(s['theme'], 'system')
        self.assertEqual(s['language'], '')

    def test_settings_corrupt_or_wrong_type(self):
        path = Path(_TMP) / 'bad.json'
        path.write_text('{"concurrency": "many", "template": 5', encoding='utf-8')
        self.assertEqual(Settings(path)['concurrency'], 2)
        path.write_text('{"concurrency": "many"}', encoding='utf-8')
        self.assertEqual(Settings(path)['concurrency'], 2)
        # bool は int の派生だが受け付けない / 壊れたプロファイルは捨てる
        path.write_text('{"concurrency": true, "profiles": {"ok": {"mode": "audio"}, "bad": 3}}', encoding='utf-8')
        s = Settings(path)
        self.assertEqual(s['concurrency'], 2)
        self.assertEqual(list(s['profiles']), ['ok'])

    def test_history(self):
        h = History(Path(_TMP) / 'h.sqlite3')
        rid = h.add({'url': URL, 'mode': 'audio', 'cookies_file': 'secret.txt'}, status='done', title='100%_zoo')
        h.add({'url': 'https://example.com/b'}, status='error', title='other')
        self.assertEqual([r['id'] for r in h.search('100%')], [rid])
        self.assertEqual(len(h.search('_')), 1)
        self.assertNotIn('cookies_file', h.job_of(rid))
        h.delete([rid])
        self.assertIsNone(h.get(rid))
        h.close()


if __name__ == '__main__':
    unittest.main()
