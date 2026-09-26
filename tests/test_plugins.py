"""プラグインの読み込み範囲・一覧・エラー表示。実際にワーカーを起動して確かめる(ネットワーク不要)。"""
import functools
import http.server
import json
import os
import threading
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kn_dlp import options, plugins
from kn_dlp.settings import Settings

ROOT = Path(__file__).resolve().parent.parent

GOOD = '''
from yt_dlp.extractor.common import InfoExtractor

class {cls}(InfoExtractor):
    IE_NAME = '{name}'
    _VALID_URL = r'https?://{name}\\.invalid/(?P<id>\\w+)'

    def _real_extract(self, url):
        return {{'id': self._match_id(url), 'title': '{name}', 'url': 'http://127.0.0.1:9/x.mp4', 'ext': 'mp4'}}
'''

GOOD_PP = '''
from yt_dlp.postprocessor.common import PostProcessor

class KnNoopPP(PostProcessor):
    def run(self, info):
        return [], info
'''


# ダウンロード後に呼ばれたことと、受け取った引数・呼ばれた順番を印ファイルに残す
MARK_PP = '''
import json, os
from yt_dlp.postprocessor.common import PostProcessor

class KnMarkPP(PostProcessor):
    def __init__(self, downloader=None, tag='none'):
        super().__init__(downloader)
        self.tag = tag

    def run(self, info):
        path = info['filepath']
        with open(path + '.mark.json', 'w') as f:
            json.dump({'tag': self.tag, 'exists': os.path.exists(path), 'pp_order': [type(p).__name__ for p in self._downloader._pps['post_process']]}, f)
        self.to_screen('marked ' + self.tag)
        return [], info
'''

LOCAL_IE = '''
from yt_dlp.extractor.common import InfoExtractor

class KnLocalIE(InfoExtractor):
    _VALID_URL = r'https?://knlocal\\.invalid/(?P<id>\\w+)'

    def _real_extract(self, url):
        return {{'id': self._match_id(url), 'title': 'local', 'url': 'http://127.0.0.1:{port}/clip.bin', 'ext': 'mp4',
                 'vcodec': 'avc1', 'acodec': 'mp4a'}}
'''


def _write_plugin(base: Path, pkg: str, kind: str, module: str, code: str) -> None:
    d = base / pkg / 'yt_dlp_plugins' / kind
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{module}.py').write_text(code, encoding='utf-8')


class PluginModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='kn_plug_')
        patcher = mock.patch.dict(os.environ, {'KN_DLP_DATA': self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_search_dirs(self):
        own = str(Path(self.tmp) / 'plugins')
        self.assertEqual(plugins.search_dirs('all'), [own, 'default'])
        self.assertEqual(plugins.search_dirs('app'), [own])
        self.assertEqual(plugins.search_dirs('off'), [])
        self.assertTrue((Path(own) / 'README.txt').is_file())

    def test_set_mode_rejects_unknown(self):
        try:
            self.assertEqual(plugins.set_mode('off'), 'off')
            self.assertEqual(plugins.set_mode('bogus'), 'all')
        finally:
            plugins.set_mode('all')

    def test_parse_errors(self):
        text = ("Error while importing module 'yt_dlp_plugins.extractor.bad'\n"
                'Traceback (most recent call last):\n  File "x", line 1\nSyntaxError: invalid syntax\n'
                "Error while importing module 'yt_dlp_plugins.postprocessor.b2'\nImportError: no module\n")
        self.assertEqual(plugins.parse_errors(text), [
            {'module': 'yt_dlp_plugins.extractor.bad', 'error': 'SyntaxError: invalid syntax'},
            {'module': 'yt_dlp_plugins.postprocessor.b2', 'error': 'ImportError: no module'}])
        self.assertEqual(plugins.parse_errors(''), [])

    def test_parse_pp_args(self):
        self.assertEqual(options.parse_pp_args('a=1; b = x=y ;'), {'a': '1', 'b': ' x=y '})
        self.assertEqual(options.parse_pp_args(''), {})
        for bad in ('novalue', 'when=before_dl', 'key=x', '1a=2', '=v'):
            with self.assertRaises(options.JobError, msg=bad):
                options.parse_pp_args(bad)

    def test_plugin_pp_spec(self):
        self.assertEqual(options.plugin_pp_spec({'name': 'FixupMtime', 'args': 'mtime_key=upload_date'}),
                         ('FixupMtime', 'post_process', {'mtime_key': 'upload_date'}))
        for bad in ({'name': 'a.b'}, {'name': 'X', 'when': 'video'}, 'X', {'name': ''}):
            with self.assertRaises(options.JobError, msg=repr(bad)):
                options.plugin_pp_spec(bad)

    def test_settings_plugin_pps(self):
        path = Path(self.tmp) / 'pp.json'
        path.write_text(json.dumps({'plugin_pps': [
            {'name': 'Good', 'when': 'after_move', 'args': 'a=1', 'enabled': True},
            {'name': 'bad name'}, 'junk', {'name': 'Off', 'enabled': 'yes'}, {'name': 'Good', 'args': 5}]}), encoding='utf-8')
        s = Settings(path)
        self.assertEqual(s['plugin_pps'], [{'name': 'Good', 'when': 'after_move', 'args': 'a=1', 'enabled': True},
                                           {'name': 'Off', 'when': 'post_process', 'args': '', 'enabled': False}])
        self.assertEqual(s.enabled_plugin_pps(), [{'name': 'Good', 'when': 'after_move', 'args': 'a=1'}])
        s.set_plugin_pp('Off', enabled=True, when='before_dl')
        s.set_plugin_pp('New', args='x=1')
        again = Settings(path)
        self.assertEqual(again.plugin_pp('Off')['when'], 'before_dl')
        self.assertEqual([p['name'] for p in again.enabled_plugin_pps()], ['Good', 'Off'])
        self.assertFalse(again.plugin_pp('New')['enabled'])

    def test_settings_validates_mode(self):
        path = Path(self.tmp) / 's.json'
        path.write_text(json.dumps({'plugins': 'everything'}), encoding='utf-8')
        self.assertEqual(Settings(path)['plugins'], 'all')
        path.write_text(json.dumps({'plugins': 'app'}), encoding='utf-8')
        self.assertEqual(Settings(path)['plugins'], 'app')


class WorkerPluginsTest(unittest.TestCase):
    """kn_dlp 専用フォルダと、yt-dlp 既定の場所(%APPDATA%/yt-dlp/plugins)にプラグインを置いて列挙させる。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='kn_plugw_'))
        cls.data = cls.tmp / 'data'
        cls.appdata = cls.tmp / 'appdata'
        own = cls.data / 'plugins'
        _write_plugin(own, 'ownpkg', 'extractor', 'own', GOOD.format(cls='KnOwnIE', name='known'))
        _write_plugin(own, 'ownpkg', 'extractor', 'broken', 'def oops(:\n')
        _write_plugin(own, 'ownpkg', 'postprocessor', 'noop', GOOD_PP)
        shared = cls.appdata / 'yt-dlp' / 'plugins'
        _write_plugin(shared, 'sharedpkg', 'extractor', 'shared', GOOD.format(cls='KnSharedIE', name='knshared'))

    def _run(self, mode: str, action: str = 'plugins', job: dict | None = None) -> dict:
        env = dict(os.environ, KN_DLP_DATA=str(self.data), APPDATA=str(self.appdata),
                   XDG_CONFIG_HOME=str(self.tmp / 'xdg'), PYTHONUTF8='1', KN_DLP_PLUGINS=mode)
        p = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--worker'],
                           input=json.dumps({'action': action, 'job': job or {}}) + '\n',
                           capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
        msgs = [json.loads(ln) for ln in p.stdout.splitlines() if ln.startswith('{')]
        res = [m for m in msgs if m.get('t') in ('result', 'error')]
        self.assertTrue(res, p.stderr[-800:])
        out = res[-1]
        out['_logs'] = [m['msg'] for m in msgs if m.get('t') == 'log']
        return out

    def _names(self, res: dict) -> set[tuple[str, str]]:
        return {(it['kind'], it['name']) for it in res['items']}

    def test_all_reads_both_locations(self):
        res = self._run('all')
        self.assertEqual(res['t'], 'result')
        self.assertEqual(res['mode'], 'all')
        self.assertTrue({('extractor', 'known'), ('extractor', 'knshared'), ('postprocessor', 'KnNoopPP')}
                        <= self._names(res), res['items'])
        self.assertEqual([e['module'] for e in res['errors']], ['yt_dlp_plugins.extractor.broken'])
        self.assertIn('SyntaxError', res['errors'][0]['error'])

    def test_app_only(self):
        names = self._names(self._run('app'))
        self.assertIn(('extractor', 'known'), names)
        self.assertNotIn(('extractor', 'knshared'), names)

    def test_off(self):
        res = self._run('off')
        self.assertEqual((res['items'], res['errors']), ([], []))

    def test_download_runs_enabled_pp_last_with_args(self):
        www = self.tmp / 'www'
        www.mkdir(exist_ok=True)
        (www / 'clip.bin').write_bytes(os.urandom(4096))
        srv = http.server.ThreadingHTTPServer(
            ('127.0.0.1', 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(www)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        own = self.data / 'plugins'
        _write_plugin(own, 'dlpkg', 'extractor', 'local', LOCAL_IE.format(port=srv.server_address[1]))
        _write_plugin(own, 'dlpkg', 'postprocessor', 'mark', MARK_PP)
        out = self.tmp / 'out'
        job = {'url': 'https://knlocal.invalid/v1', 'out_dir': str(out), 'metadata': False, 'chapters': False,
               'plugin_pps': [{'name': 'KnMark', 'when': 'post_process', 'args': 'tag=hello'},
                              {'name': 'KnMissing'}, {'name': 'KnMark', 'args': 'nope=1'}]}
        res = self._run('app', 'download', job)
        self.assertEqual(res['t'], 'result', res)
        marks = list(out.glob('*.mark.json'))
        self.assertEqual(len(marks), 1, list(out.iterdir()))
        mark = json.loads(marks[0].read_text())
        self.assertEqual((mark['tag'], mark['exists']), ('hello', True))
        self.assertEqual(mark['pp_order'][-1], 'KnMarkPP')     # 標準の後処理より後ろ
        logs = '\n'.join(res['_logs'])
        self.assertIn('KnMissing', logs)
        self.assertIn('nope', logs)                            # 未知の引数は警告して飛ばす

    def test_probe_reports_plugin_use_and_load_error(self):
        res = self._run('app', 'probe', {'url': 'https://known.invalid/abc'})
        self.assertEqual(res['t'], 'result', res)
        self.assertEqual(res['info']['title'], 'known')
        self.assertTrue(any('known' in m and ('プラグイン' in m or 'plugin' in m.lower()) for m in res['_logs']), res['_logs'])
        self.assertTrue(any('broken' in m for m in res['_logs']), res['_logs'])


if __name__ == '__main__':
    unittest.main()
