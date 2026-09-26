"""ファイル名テンプレートの雛形とプレビュー(ワーカーの filename 要求。ネットワーク不要)。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kn_dlp import options

ROOT = Path(__file__).resolve().parent.parent
INFO = {'id': 'jNQXAC9IVRw', 'title': 'Me at the zoo', 'uploader': 'jawed', 'upload_date': '20050424', 'duration': 19,
        'ext': 'webm'}


def preview(job: dict) -> dict:
    env = dict(os.environ, KN_DLP_DATA=tempfile.mkdtemp(prefix='kn_fn_'), KN_DLP_PLUGINS='off', PYTHONUTF8='1')
    p = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--worker'],
                       input=json.dumps({'action': 'filename', 'job': {'out_dir': 'C:/dl' if os.name == 'nt' else '/dl', **job}}) + '\n',
                       capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
    res = [json.loads(ln) for ln in p.stdout.splitlines() if ln.startswith('{')]
    return [m for m in res if m.get('t') in ('result', 'error')][-1]


class PresetTest(unittest.TestCase):
    def test_presets_are_valid(self):
        self.assertEqual(options.TEMPLATE_PRESETS[0][1], options.DEFAULT_TEMPLATE)
        for _name, tmpl in options.TEMPLATE_PRESETS:
            options.validate_job({**options.JOB_DEFAULTS, 'url': 'https://example.com/', 'template': tmpl})

    def test_final_ext(self):
        self.assertEqual(options.final_ext({'mode': 'audio', 'audio_codec': 'mp3'}, 'webm'), 'mp3')
        self.assertEqual(options.final_ext({'mode': 'audio', 'audio_codec': 'best'}, 'webm'), 'webm')
        self.assertEqual(options.final_ext({'mode': 'video', 'container': 'mkv'}, 'webm'), 'mkv')
        self.assertEqual(options.final_ext({'mode': 'video', 'container': 'auto'}, 'mp4'), 'mp4')


class PreviewTest(unittest.TestCase):
    def test_real_info(self):
        res = preview({'preview_info': INFO, 'container': 'mp4'})
        self.assertEqual((res['t'], res['name'], res['sample']), ('result', 'Me at the zoo [jNQXAC9IVRw].mp4', False))

    def test_presets_with_real_info(self):
        names = {tmpl: preview({'preview_info': INFO, 'template': tmpl, 'mode': 'audio', 'audio_codec': 'mp3'})['name']
                 for _n, tmpl in options.TEMPLATE_PRESETS}
        self.assertEqual(names[options.TEMPLATE_PRESETS[2][1]], '2005-04-24 Me at the zoo [jNQXAC9IVRw].mp3')
        self.assertEqual(Path(names[options.TEMPLATE_PRESETS[3][1]]).parts, ('jawed', 'Me at the zoo [jNQXAC9IVRw].mp3'))
        self.assertEqual(Path(names[options.TEMPLATE_PRESETS[4][1]]).parts, ('NA', 'NA Me at the zoo.mp3'))

    def test_sample_and_range(self):
        res = preview({'range_start': '1:00', 'range_end': '1:30'})
        self.assertTrue(res['sample'])
        self.assertTrue(res['name'].endswith('[dQw4w9WgXcQ] [60-90].webm'), res['name'])

    def test_invalid_template(self):
        self.assertEqual(preview({'template': '../x.%(ext)s'})['t'], 'error')

    def test_windows_unsafe_title(self):
        res = preview({'preview_info': {**INFO, 'title': 'a/b:c?'}})
        self.assertNotIn(':', res['name'])
        self.assertNotIn('?', res['name'])


if __name__ == '__main__':
    unittest.main()
