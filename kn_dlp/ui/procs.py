"""ワーカー子プロセスの起動・停止と、背景スレッド処理の小道具。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from .. import i18n, paths
from ..i18n import tr

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def worker_command() -> list[str]:
    if paths.is_frozen():
        exe = Path(sys.executable)
        worker = exe.with_name('kn_dlp_worker.exe')
        return [str(worker if worker.is_file() else exe), '--worker']
    return [sys.executable, str(paths.app_root() / 'main.py'), '--worker']


def kill_tree(pid: int) -> None:
    """ffmpeg など孫プロセスごと止める。"""
    if not pid:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True,
                       creationflags=_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except (ProcessLookupError, PermissionError):
            pass


class WorkerProcess(QObject):
    """1 リクエスト = 1 子プロセス。"""
    message = Signal(dict)
    finished = Signal(int)          # 終了コード(強制終了時は -1)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUTF8', '1')
        env.insert('PYTHONIOENCODING', 'utf-8')
        env.insert('KN_DLP_LANG', i18n.current())     # ワーカーのメッセージも同じ言語にする
        self.proc.setProcessEnvironment(env)
        if os.name == 'nt' and hasattr(self.proc, 'setCreateProcessArgumentsModifier'):
            def _modifier(args):
                args.flags |= _NO_WINDOW
            self.proc.setCreateProcessArgumentsModifier(_modifier)
        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(self._on_finished)
        self.proc.errorOccurred.connect(self._on_error)
        self._buf = b''
        self.stderr_tail: deque[str] = deque(maxlen=40)
        self.killed = False
        self._done = False

    def start(self, action: str, job: dict | None = None) -> None:
        cmd = worker_command()
        self.proc.start(cmd[0], cmd[1:])
        payload = json.dumps({'action': action, 'job': job or {}}, ensure_ascii=False) + '\n'
        self.proc.write(payload.encode('utf-8'))
        self.proc.closeWriteChannel()

    def kill(self) -> None:
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.killed = True
            kill_tree(int(self.proc.processId()))
            self.proc.kill()

    def is_running(self) -> bool:
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def _on_stdout(self) -> None:
        self._buf += bytes(self.proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b'\n')
        for raw in lines:
            if not raw.strip():
                continue
            try:
                msg = json.loads(raw.decode('utf-8', 'replace'))
            except ValueError:
                self.stderr_tail.append(raw.decode('utf-8', 'replace'))
                continue
            if isinstance(msg, dict):
                self.message.emit(msg)

    def _on_stderr(self) -> None:
        text = bytes(self.proc.readAllStandardError()).decode('utf-8', 'replace')
        for line in text.splitlines():
            if line.strip():
                self.stderr_tail.append(line)

    def _on_finished(self, code: int, _status) -> None:
        if self._done:
            return
        self._done = True
        self._on_stdout()
        self.finished.emit(-1 if self.killed else int(code))

    def _on_error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart and not self._done:
            self._done = True
            self.message.emit({'t': 'error', 'msg': tr('ワーカーを起動できません: {error}', error=self.proc.errorString()),
                               'kind': 'internal'})
            self.finished.emit(2)


class BgTask(QObject):
    """関数をスレッドで実行し、結果を GUI スレッドへシグナルで返す。"""
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    _alive: set['BgTask'] = set()

    def __init__(self, fn: Callable[..., Any], *, with_progress: bool = False):
        super().__init__()
        self.fn = fn
        self.with_progress = with_progress

    def start(self) -> 'BgTask':
        BgTask._alive.add(self)
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self) -> None:
        try:
            result = self.fn(self.progress.emit) if self.with_progress else self.fn()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
        else:
            self.done.emit(result)
        finally:
            BgTask._alive.discard(self)
