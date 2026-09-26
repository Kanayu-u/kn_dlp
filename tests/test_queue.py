"""キャンセル時の途中ファイル削除(Qt の import だけ必要。イベントループ不要)。"""
import os
import tempfile
import unittest
from pathlib import Path

from kn_dlp.ui.queue import Job, _remove_partials


class RemovePartialsTest(unittest.TestCase):
    def test_only_reported_paths_under_out_dir(self):
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as other:
            base = Path(out, 'v.f396.mp4')
            for suffix in ('.part', '.ytdl', '.part-Frag3'):
                Path(str(base) + suffix).write_bytes(b'x')
            base.write_bytes(b'x')                          # 結合前の中間ファイル
            final = Path(out, 'v.mp4')
            final.write_bytes(b'x')
            keep = Path(out, 'unrelated.mp4')
            keep.write_bytes(b'x')
            outside = Path(other, 'o.mp4')
            Path(str(outside) + '.part').write_bytes(b'x')
            job = Job(spec={'out_dir': out}, files=[{'path': str(final)}])
            job.partials = {str(base), str(final), str(outside)}
            _remove_partials(job)
            self.assertEqual(sorted(os.listdir(out)), ['unrelated.mp4', 'v.mp4'])
            self.assertTrue(Path(str(outside) + '.part').exists())
            self.assertFalse(job.partials)


if __name__ == '__main__':
    unittest.main()
