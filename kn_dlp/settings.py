"""設定とプロファイル(G)。JSON 1ファイル、書き込みは一時ファイル経由で原子的に。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import paths
from .options import DEFAULT_TEMPLATE
from .plugins import MODES as PLUGIN_MODES
from .i18n import N_, tr

# プロファイルに保存するジョブ項目(URL・保存先・Cookie・実行環境は含めない)
PROFILE_KEYS = [
    'mode', 'quality', 'container', 'audio_codec', 'audio_quality', 'template', 'playlist',
    'precise_cut', 'subs', 'sub_langs', 'auto_subs', 'embed_subs', 'chapters', 'embed_thumbnail',
    'metadata', 'wait_live', 'live_from_start', 'rate_limit',
]

# 組み込みプロファイルは言語に依存しない ID で保存し、表示名だけ翻訳する
BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    'builtin:standard': {
        'name': N_('標準 (動画・最高画質)'),
        'job': {'mode': 'video', 'quality': 'best', 'container': 'auto', 'chapters': True, 'metadata': True}},
    'builtin:compat': {
        'name': N_('互換重視 (MP4 1080p)'),
        'job': {'mode': 'video', 'quality': '1080', 'container': 'mp4', 'chapters': True, 'metadata': True}},
    'builtin:music': {
        'name': N_('音楽 (MP3・サムネ埋め込み)'),
        'job': {'mode': 'audio', 'audio_codec': 'mp3', 'audio_quality': '0', 'embed_thumbnail': True, 'metadata': True,
                'chapters': True}},
    'builtin:archive': {
        'name': N_('アーカイブ (字幕・全部入り)'),
        'job': {'mode': 'video', 'quality': 'best', 'container': 'mkv', 'subs': True, 'auto_subs': True,
                'sub_langs': 'ja,en', 'embed_subs': True, 'chapters': True, 'embed_thumbnail': True, 'metadata': True}},
}
_BUILTIN_PREFIX = 'builtin:'
# 公開前の開発版は表示名(日本語)をそのまま保存していた
_LEGACY_NAMES = {v['name']: k for k, v in BUILTIN_PROFILES.items()}

LANGUAGES = ['', 'ja', 'en', 'ko', 'zh_CN']    # '' = OS に合わせる
THEMES = ['system', 'dark', 'light']

DEFAULTS: dict[str, Any] = {
    'download_dir': str(paths.default_download_dir()),
    'template': DEFAULT_TEMPLATE,
    'concurrency': 2,
    'ffmpeg_path': '',
    'js_runtime': '',          # '' = 自動
    'last_profile': 'builtin:standard',
    'profiles': {},            # ユーザー定義
    'check_update_on_start': True,
    'log_visible': False,
    'language': '',
    'theme': 'system',
    'plugins': 'all',          # all / app(kn_dlp のみ) / off
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.data_dir() / 'settings.json'
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return  # 無い/壊れている → 既定値で起動(壊れたファイルは次の save で置き換わる)
        if isinstance(raw, dict):
            for key, default in DEFAULTS.items():
                value = raw.get(key)
                # bool は int の派生なので、型は完全一致で比べる(concurrency に true が入る等を弾く)
                if key in raw and type(value) is type(default):
                    self.data[key] = value
            self.data['profiles'] = {str(k): v for k, v in self.data['profiles'].items()
                                     if isinstance(v, dict) and not str(k).startswith(_BUILTIN_PREFIX)}
            self.data['last_profile'] = _LEGACY_NAMES.get(self.data['last_profile'], self.data['last_profile'])
            if self.data['language'] not in LANGUAGES:
                self.data['language'] = ''
            if self.data['theme'] not in THEMES:
                self.data['theme'] = 'system'
            if self.data['plugins'] not in PLUGIN_MODES:
                self.data['plugins'] = 'all'

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix='.settings-', suffix='.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    # --- profiles ---
    def profile_ids(self) -> list[str]:
        return list(BUILTIN_PROFILES) + list(self.data['profiles'])

    def profile_label(self, pid: str) -> str:
        return tr(BUILTIN_PROFILES[pid]['name']) if pid in BUILTIN_PROFILES else pid

    def is_builtin(self, pid: str) -> bool:
        return pid in BUILTIN_PROFILES

    def get_profile(self, pid: str) -> dict[str, Any]:
        if pid in BUILTIN_PROFILES:
            return dict(BUILTIN_PROFILES[pid]['job'])
        return dict(self.data['profiles'].get(pid, {}))

    def save_profile(self, name: str, job: dict[str, Any]) -> str:
        """ユーザー定義プロファイルを保存し、その ID(=名前)を返す。"""
        name = name.strip()
        if not name:
            raise ValueError(tr('プロファイル名が空です'))
        if name.startswith(_BUILTIN_PREFIX) or name in _LEGACY_NAMES \
                or name in {self.profile_label(p) for p in BUILTIN_PROFILES}:
            raise ValueError(tr('組み込みプロファイルは上書きできません'))
        self.data['profiles'][name] = {k: job[k] for k in PROFILE_KEYS if k in job}
        self.save()
        return name

    def delete_profile(self, pid: str) -> None:
        if pid in BUILTIN_PROFILES:
            raise ValueError(tr('組み込みプロファイルは削除できません'))
        self.data['profiles'].pop(pid, None)
        self.save()
