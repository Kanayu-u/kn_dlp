"""yt-dlp プラグインの読み込み範囲と一覧。

プラグインは yt-dlp 公式の仕組み(yt_dlp_plugins 名前空間パッケージ)をそのまま使う。
kn_dlp 専用フォルダ(データフォルダ/plugins)と、yt-dlp 本体の既定の場所(%APPDATA%/yt-dlp/plugins 等)から読む。
読み込み範囲は GUI の設定を環境変数 KN_DLP_PLUGINS でワーカーへ渡す。yt_dlp を import するのはワーカーだけ。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .i18n import tr

MODES = ('all', 'app', 'off')   # すべて / kn_dlp のみ / オフ
ENV_KEY = 'KN_DLP_PLUGINS'
PACKAGE = 'yt_dlp_plugins'

_mode = 'all'

README = """\
kn_dlp plugins folder / プラグインフォルダ

Put yt-dlp plugins here. Each plugin is a package folder (or a .zip) laid out like this:
yt-dlp のプラグインをここに置きます。1つのプラグインは次の形のフォルダ(または .zip)です。

  plugins\\
    <any-name>\\
      yt_dlp_plugins\\
        extractor\\<name>.py        site support / サイト対応
        postprocessor\\<name>.py    post-processing / 後処理

Plugins run as Python code with your user rights. Only install plugins you trust.
プラグインはあなたの権限で動く Python コードです。信頼できるものだけを置いてください。

Docs: https://github.com/yt-dlp/yt-dlp#plugins
"""


# ---- GUI 側(プロセス全体の設定値。言語と同じく、ワーカー起動時に環境変数で渡す) ----
def set_mode(mode: str) -> str:
    global _mode
    _mode = mode if mode in MODES else 'all'
    return _mode


def current_mode() -> str:
    return _mode


def plugins_dir() -> Path:
    return paths.data_dir() / 'plugins'


def ensure_dir() -> Path | None:
    """専用フォルダと説明書きを用意する。作れなければ None。"""
    d = plugins_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        readme = d / 'README.txt'
        if not readme.exists():
            readme.write_text(README, encoding='utf-8')
    except OSError:
        return None
    return d


def search_dirs(mode: str) -> list[str]:
    """yt_dlp.globals.plugin_dirs に入れる値。'default' は yt-dlp 本体の既定の探索場所を表す。"""
    if mode == 'off':
        return []
    d = ensure_dir()
    own = [str(d)] if d else []
    return own if mode == 'app' else own + ['default']


# ---- ワーカー側 ----
_ERR_RE = re.compile(r"Error while importing module '([^']+)'")


def parse_errors(text: str) -> list[dict[str, str]]:
    """yt-dlp が stderr に書く読み込みエラーを、モジュール名と最終行(例外)に分ける。"""
    errors = []
    parts = _ERR_RE.split(text)
    for module, body in zip(parts[1::2], parts[2::2]):
        lines = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
        errors.append({'module': module, 'error': lines[-1] if lines else ''})
    return errors


def env_mode() -> str:
    mode = os.environ.get(ENV_KEY, 'all')
    return mode if mode in MODES else 'all'


def activate(mode: str | None = None) -> list[dict[str, str]]:
    """読み込み範囲を設定してプラグインを読み込み、読み込みエラーを返す。YoutubeDL を作る前に1回呼ぶ。"""
    mode = mode if mode in MODES else env_mode()
    from yt_dlp.globals import plugin_dirs
    from yt_dlp.plugins import load_all_plugins
    plugin_dirs.value = search_dirs(mode)
    if mode == 'off':
        os.environ['YTDLP_NO_PLUGINS'] = '1'    # yt-dlp 側の無効化スイッチも併用する
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        load_all_plugins()
    return parse_errors(buf.getvalue())


def _source_file(cls: type) -> str:
    try:
        return inspect.getfile(cls)
    except (TypeError, OSError):
        return getattr(sys.modules.get(cls.__module__), '__file__', '') or ''


def list_loaded() -> dict[str, Any]:
    """activate() 後に、読み込まれたプラグインと探索場所を返す。"""
    from yt_dlp.globals import plugin_ies, plugin_ies_overrides, plugin_pps
    from yt_dlp.plugins import directories
    items = []
    for kind, lookup in (('extractor', plugin_ies.value), ('postprocessor', plugin_pps.value)):
        for name, cls in sorted(lookup.items()):
            items.append({'kind': kind, 'name': getattr(cls, 'IE_NAME', None) or name,
                          'class': name, 'file': _source_file(cls)})
    for parent, overrides in plugin_ies_overrides.value.items():
        for cls in overrides:
            items.append({'kind': 'override', 'name': getattr(parent, 'IE_NAME', parent.__name__),
                          'class': cls.__name__, 'file': _source_file(cls)})
    return {'items': items, 'dirs': directories()}


def is_plugin_extractor(ie: Any) -> bool:
    """実際に使われた抽出器がプラグイン由来(上書きを含む)か。"""
    return _is_plugin_class(type(ie))


def _is_plugin_class(cls: type) -> bool:
    return cls.__module__.startswith(PACKAGE) or '+' in str(getattr(cls, 'IE_NAME', ''))


def match_url(url: str, limit: int = 5) -> list[dict[str, Any]]:
    """URL を処理する抽出器を、yt-dlp が試す順に返す(先頭が実際に使われる)。activate() 後に呼ぶ。"""
    from yt_dlp.extractor import gen_extractor_classes
    found = []
    for ie in gen_extractor_classes():
        try:
            ok = ie.suitable(url)
        except Exception:  # noqa: BLE001  (壊れたプラグインの _VALID_URL で全体を止めない)
            ok = False
        if ok:
            # 配布版の yt-dlp は遅延読み込み用の代理クラスを返す。上書きプラグインは実体側に入るので実体を見る
            real = getattr(ie, 'real_class', ie)
            found.append({'name': str(getattr(real, 'IE_NAME', real.__name__)), 'key': ie.ie_key(),
                          'plugin': _is_plugin_class(real), 'working': bool(real.working()),
                          'generic': ie.ie_key() == 'Generic'})
            if len(found) >= limit:
                break
    return found


# ---- 導入・雛形(GUI から呼ぶ。yt_dlp は import しない) ----
class InstallError(ValueError):
    """導入できない理由(利用者に見せる文言)。"""


KINDS = ('extractor', 'postprocessor')
_IDENT_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
_ARCHIVE_SUFFIX_RE = re.compile(r'-(?:[0-9a-f]{7,40}|master|main|HEAD)$')
MAX_ZIP_FILES = 2000
MAX_ZIP_BYTES = 50 * 1024 * 1024


@dataclass
class InstallPlan:
    source: Path
    target: Path          # 置き先(.zip はファイル、それ以外はパッケージのフォルダ)
    mode: str             # 'zip'(そのまま置く) / 'archive'(yt_dlp_plugins だけ展開) / 'py'
    kind: str = ''        # .py のときの種類
    members: list[str] = field(default_factory=list)   # archive で展開するメンバー

    @property
    def exists(self) -> bool:
        return self.target.exists()


def _safe_name(name: str) -> str:
    name = re.sub(r'[^A-Za-z0-9_.-]', '_', name).strip('._-')
    if not name:
        raise InstallError(tr('名前に使える文字がありません'))
    return name


def _detect_kind(code: str) -> str:
    kinds = set()
    if re.search(r'^class\s+\w+IE\s*\(', code, re.M):
        kinds.add('extractor')
    if re.search(r'^class\s+\w+PP\s*\(', code, re.M):
        kinds.add('postprocessor')
    if len(kinds) != 1:
        raise InstallError(tr('サイト対応(クラス名が IE で終わる)か後処理(PP で終わる)かを判定できません'))
    return kinds.pop()


def plan_install(src: Path | str) -> InstallPlan:
    """ファイルを調べて、どこへどう置くかを決める(まだ書き込まない)。"""
    src = Path(src)
    if not src.is_file():
        raise InstallError(tr('ファイルが見つかりません: {path}', path=src))
    base = plugins_dir()
    if src.suffix.lower() == '.py':
        module = src.stem
        if not _IDENT_RE.match(module):
            raise InstallError(tr('ファイル名は英字で始まる英数字と _ にしてください: {name}', name=src.name))
        try:
            code = src.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            raise InstallError(tr('ファイルを読めません: {e}', e=e)) from None
        kind = _detect_kind(code)
        return InstallPlan(src, base / module, 'py', kind=kind)
    if src.suffix.lower() != '.zip':
        raise InstallError(tr('プラグインとして追加できるのは .py と .zip です'))
    try:
        with zipfile.ZipFile(src) as zf:
            infos = zf.infolist()
    except (OSError, zipfile.BadZipFile) as e:
        raise InstallError(tr('zip を開けません: {e}', e=e)) from None
    if len(infos) > MAX_ZIP_FILES or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
        raise InstallError(tr('zip が大きすぎます'))
    names = [i.filename for i in infos]
    if any(n.startswith(f'{PACKAGE}/') for n in names):
        return InstallPlan(src, base / f'{_safe_name(src.stem)}.zip', 'zip')
    # GitHub の「Download ZIP」: <repo>-<ref>/yt_dlp_plugins/... の1段深い形
    tops = {n.split('/', 1)[0] for n in names}
    if len(tops) == 1:
        top = tops.pop()
        prefix = f'{top}/{PACKAGE}/'
        members = [n for n in names if n.startswith(prefix) and not n.endswith('/')]
        if members:
            return InstallPlan(src, base / _safe_name(_ARCHIVE_SUFFIX_RE.sub('', top)), 'archive', members=members)
    raise InstallError(tr('zip の中に yt_dlp_plugins フォルダがありません(yt-dlp のプラグインではない可能性があります)'))


def install(plan: InstallPlan, *, overwrite: bool = False) -> Path:
    """plan_install の結果どおりに置く。既にあれば overwrite=True のときだけ置き換える。"""
    if ensure_dir() is None:
        raise InstallError(tr('フォルダを作成できませんでした: {path}', path=plugins_dir()))
    if plan.exists and not overwrite:
        raise InstallError(tr('同じ名前のプラグインが既にあります: {path}', path=plan.target))
    tmp = plan.target.with_name(plan.target.name + '.installing')
    old = plan.target.with_name(plan.target.name + '.old')
    _remove(tmp)
    _remove(old)
    try:
        if plan.mode == 'zip':
            shutil.copyfile(plan.source, tmp)
        elif plan.mode == 'py':
            dst = tmp / PACKAGE / plan.kind / plan.source.name
            dst.parent.mkdir(parents=True)
            shutil.copyfile(plan.source, dst)
        else:
            with zipfile.ZipFile(plan.source) as zf:
                for name in plan.members:
                    rel = Path(*name.split('/')[1:])
                    if rel.is_absolute() or '..' in rel.parts or ':' in name:   # パス横断を防ぐ
                        raise InstallError(tr('zip に不正なパスがあります: {name}', name=name))
                    dst = tmp / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as fin, open(dst, 'wb') as fout:
                        shutil.copyfileobj(fin, fout)
        # 古いものは消さずに退避してから差し替える(使用中などで失敗したら元に戻す)
        if plan.target.exists():
            os.replace(plan.target, old)
        try:
            os.replace(tmp, plan.target)
        except OSError:
            if old.exists() and not plan.target.exists():
                os.replace(old, plan.target)
            raise
        _remove(old)
    except OSError as e:
        _remove(tmp)
        raise InstallError(tr('プラグインを置けませんでした: {e}', e=e)) from None
    except BaseException:
        _remove(tmp)
        raise
    return plan.target


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


_TEMPLATES = {
    'extractor': '''\
# Site-support plugin template created by kn_dlp / kn_dlp が作成したサイト対応プラグインの雛形
# Guide / 作り方: https://github.com/yt-dlp/yt-dlp/blob/master/CONTRIBUTING.md#adding-support-for-a-new-site
# Do not use relative imports. The class name must end in "IE".
from yt_dlp.extractor.common import InfoExtractor


class {name}IE(InfoExtractor):
    IE_NAME = '{module}'
    # Which URLs this plugin handles / このプラグインが受け持つ URL
    _VALID_URL = r'https?://(?:www\\.)?example\\.com/watch/(?P<id>[0-9A-Za-z_-]+)'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)
        return {{
            'id': video_id,
            'title': self._og_search_title(webpage),
            'url': self._og_search_video_url(webpage),
        }}
''',
    'postprocessor': '''\
# Post-processing plugin template created by kn_dlp / kn_dlp が作成した後処理プラグインの雛形
# Enable it with "Run" in kn_dlp's settings / kn_dlp の設定で「実行する」にすると動きます
# Do not use relative imports. The class name must end in "PP".
from yt_dlp.postprocessor.common import PostProcessor


class {name}PP(PostProcessor):
    def __init__(self, downloader=None, **kwargs):
        super().__init__(downloader)
        self._kwargs = kwargs   # arguments from the settings (all values are strings) / 設定の引数(値はすべて文字列)

    def run(self, info):
        filepath = info.get('filepath')   # None when run before the download / ダウンロード前は None
        self.to_screen(f'{{filepath}} {{self._kwargs}}')
        return [], info   # (files to delete, info) / (削除するファイル, info)
''',
}


def create_template(kind: str, name: str) -> Path:
    """雛形の .py を作ってそのパスを返す。既存のものは上書きしない。"""
    if kind not in KINDS:
        raise InstallError(tr('種類が不正です: {kind}', kind=kind))
    name = name.strip()
    if not _IDENT_RE.match(name):
        raise InstallError(tr('名前は英字で始まる英数字と _ にしてください: {name}', name=name))
    module = name.lower()
    if ensure_dir() is None:
        raise InstallError(tr('フォルダを作成できませんでした: {path}', path=plugins_dir()))
    pkg = plugins_dir() / module
    if pkg.exists():
        raise InstallError(tr('同じ名前のプラグインが既にあります: {path}', path=pkg))
    path = pkg / PACKAGE / kind / f'{module}.py'
    try:
        path.parent.mkdir(parents=True)
        path.write_text(_TEMPLATES[kind].format(name=name, module=module), encoding='utf-8')
    except OSError as e:
        raise InstallError(tr('プラグインを置けませんでした: {e}', e=e)) from None
    return path
