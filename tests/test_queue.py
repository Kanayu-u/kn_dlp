"""キャンセル時の途中ファイル削除(Qt の import だけ必要。イベントループ不要)。"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from kn_dlp import queue_store

from kn_dlp.i18n import tr
from kn_dlp.ui.queue import Job, QueueManager, _remove_partials


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


class SkippedTest(unittest.TestCase):
    """ダウンロード済みの記録で飛ばしたジョブは、完了でも「飛ばした」と分かるようにする。"""

    def _finish(self, skipped: int, files: list) -> Job:
        q = QueueManager(lambda: {}, 1)
        job = Job(spec={}, status='running', files=files)
        q.jobs[job.id] = job
        q.order.append(job.id)
        for _ in range(skipped):
            q._on_message(job, {'t': 'skipped', 'reason': 'archive'})
        q._on_finished(job, 0)
        return job

    def test_all_skipped(self):
        job = self._finish(1, [])
        self.assertEqual((job.status, job.stage), ('done', tr('ダウンロード済みのため飛ばしました')))

    def test_some_skipped(self):
        job = self._finish(2, [{'path': 'a.mp4'}])
        self.assertEqual(job.stage, tr('完了 ({count} 件はダウンロード済みのため飛ばしました)', count=2))

    def test_card_shows_skip_and_restore(self):
        from kn_dlp.ui.queue_page import JobCard
        job = self._finish(1, [])
        self.assertIn(tr('ダウンロード済みのため飛ばしました'), JobCard._detail(job))
        paused = Job(spec={'url': 'https://a'}, status='paused', stage=tr('前回の終了時から一時停止中'))
        self.assertIn(tr('前回の終了時から一時停止中'), JobCard._detail(paused))
        manual = Job(spec={'url': 'https://a'}, status='paused', stage=tr('一時停止'))
        self.assertNotIn(tr('一時停止') + '  ·', JobCard._detail(manual))

    def test_none_skipped(self):
        self.assertEqual(self._finish(0, [{'path': 'a.mp4'}]).stage, tr('完了'))


class PersistTest(unittest.TestCase):
    """終わっていないキューの保存と復元。"""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {'KN_DLP_DATA': tempfile.mkdtemp(prefix='kn_q_')})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_roundtrip(self):
        q = QueueManager(lambda: {}, 1)
        q._pump = lambda: None                       # テストではワーカーを起動しない
        jobs = {st: q.add({'url': f'https://example.com/{st}', 'ffmpeg_location': 'C:/ff', 'archive_file': 'a'}, title=st)
                for st in ('queued', 'running', 'paused', 'done', 'error', 'cancelled')}
        for st, job in jobs.items():
            job.status = st
        jobs['running'].partials = {'C:/dl/x.mp4'}
        future = time.time() + 3600
        sched = q.add({'url': 'https://example.com/s'}, title='s', start_at=future)
        queue_store.save(q.snapshot())

        items = queue_store.load()
        self.assertEqual([i['title'] for i in items], ['queued', 'running', 'paused', 's'])
        self.assertNotIn('ffmpeg_location', items[0]['spec'])      # 実行環境は保存しない
        q2 = QueueManager(lambda: {}, 1)
        q2._pump = lambda: None
        self.assertEqual(q2.restore(items), 4)
        restored = [q2.jobs[j] for j in q2.order]
        self.assertEqual([j.status for j in restored], ['paused', 'paused', 'paused', 'scheduled'])
        self.assertEqual(restored[1].partials, {'C:/dl/x.mp4'})
        self.assertEqual(restored[3].start_at, future)
        self.assertEqual(sched.status, 'scheduled')

    def test_load_rejects_broken(self):
        self.assertEqual(queue_store.load(), [])                    # ファイルが無い
        queue_store.path().write_text('{broken', encoding='utf-8')
        self.assertEqual(queue_store.load(), [])
        queue_store.path().write_text(json.dumps({'version': 1, 'jobs': [
            {'spec': {'url': 'https://a'}, 'status': 'queued', 'start_at': True, 'title': 5},
            {'spec': {'url': ''}, 'status': 'queued'}, {'spec': 'x', 'status': 'queued'},
            {'spec': {'url': 'https://b'}, 'status': 'done'}, 'junk']}), encoding='utf-8')
        items = queue_store.load()
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]['title'], items[0]['start_at']), ('https://a', None))
        queue_store.path().write_text(json.dumps({'version': 99, 'jobs': []}), encoding='utf-8')
        self.assertEqual(queue_store.load(), [])


if __name__ == '__main__':
    unittest.main()
