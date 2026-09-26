"""yt-dlp 本体の更新(F)。

公式リリースの zipapp(`yt-dlp`)と SHA2-256SUMS を取得し、ハッシュが一致したものだけを
データフォルダの yt-dlp.pyz に置く。直前の版は .bak として残し、1 回分戻せる。
ネットワーク処理は同期関数なので、GUI からはワーカースレッドで呼ぶこと。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import __version__, bootstrap, paths
from .i18n import tr

REPO = 'yt-dlp/yt-dlp'
API_LATEST = f'https://api.github.com/repos/{REPO}/releases/latest'
ASSET_NAME = 'yt-dlp'
SUMS_NAME = 'SHA2-256SUMS'
MAX_ASSET_BYTES = 64 * 1024 * 1024
_ALLOWED_HOSTS = {'github.com', 'api.github.com', 'objects.githubusercontent.com',
                  'release-assets.githubusercontent.com'}
USER_AGENT = f'kn_dlp/{__version__} (+https://github.com/{REPO})'


class UpdateError(RuntimeError):
    pass


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def _check_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme != 'https' or u.hostname not in _ALLOWED_HOSTS:
        raise UpdateError(tr('想定外の取得先です: {url}', url=url))


def _get(url: str, timeout: float = 30) -> bytes:
    _check_url(url)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with _opener.open(req, timeout=timeout) as resp:
        return resp.read(MAX_ASSET_BYTES + 1)


def current_version() -> tuple[str, str]:
    """(版, 出所)。出所は 'updated' | 'bundled' | 'site-packages' | 'none'。"""
    chosen = bootstrap.select_pyz()
    if chosen:
        pyz, ver = chosen
        return ver, 'updated' if pyz == paths.updated_ytdlp() else 'bundled'
    try:
        from importlib.metadata import version
        return version('yt-dlp'), 'site-packages'
    except Exception:
        return '', 'none'


def fetch_latest() -> dict:
    """{'version', 'published_at', 'asset_url', 'sums_url', 'html_url'}"""
    try:
        data = json.loads(_get(API_LATEST, timeout=15))
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(tr('最新版の確認に失敗しました: {e}', e=e)) from e
    assets = {a.get('name'): a.get('browser_download_url') for a in data.get('assets', [])}
    if ASSET_NAME not in assets or SUMS_NAME not in assets:
        raise UpdateError(tr('リリースに必要なファイルが見つかりません'))
    return {
        'version': str(data.get('tag_name', '')),
        'published_at': str(data.get('published_at', '')),
        'asset_url': assets[ASSET_NAME],
        'sums_url': assets[SUMS_NAME],
        'html_url': str(data.get('html_url', '')),
    }


APP_REPO = 'Kanayu-u/kn_dlp'
APP_API_LATEST = f'https://api.github.com/repos/{APP_REPO}/releases/latest'
APP_RELEASES_URL = f'https://github.com/{APP_REPO}/releases/'


def fetch_app_latest() -> dict:
    """本アプリの最新リリース {'version', 'published_at', 'html_url'}。

    自動で置き換えはしない(未署名の exe が自分自身を書き換えるのは危険が大きい)。リリースページを開くだけ。
    """
    try:
        data = json.loads(_get(APP_API_LATEST, timeout=15))
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(tr('最新版の確認に失敗しました: {e}', e=e)) from e
    version = str(data.get('tag_name', '')).lstrip('vV')
    html_url = str(data.get('html_url', ''))
    if not re.fullmatch(r'\d+(\.\d+){1,3}', version):
        raise UpdateError(tr('リリースの版番号を読めません: {tag}', tag=data.get('tag_name')))
    if not html_url.startswith(APP_RELEASES_URL):
        html_url = APP_RELEASES_URL + 'latest'
    return {'version': version, 'published_at': str(data.get('published_at', '')), 'html_url': html_url}


def is_newer(latest: str, current: str) -> bool:
    if not current:
        return True
    return bootstrap.version_key(latest) > bootstrap.version_key(current)


def parse_sums(text: str, name: str = ASSET_NAME) -> str:
    for line in text.splitlines():
        m = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(\S+)', line.strip())
        if m and m.group(2) == name:
            return m.group(1).lower()
    raise UpdateError(tr('{sums} に {name} の記載がありません', sums=SUMS_NAME, name=name))


def _download(url: str, dest: Path, expected_sha256: str, max_bytes: int,
              progress: Callable[[int, int], None] | None = None) -> None:
    """SHA-256 が一致したときだけ dest を残す。不一致・失敗時は消す。"""
    _check_url(url)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    digest = hashlib.sha256()
    received = 0
    try:
        with _opener.open(req, timeout=60) as resp, open(dest, 'wb') as f:
            total = int(resp.headers.get('Content-Length') or 0)
            if total > max_bytes:
                raise UpdateError(tr('ファイルが大きすぎます'))
            while chunk := resp.read(256 * 1024):
                received += len(chunk)
                if received > max_bytes:
                    raise UpdateError(tr('ファイルが大きすぎます'))
                digest.update(chunk)
                f.write(chunk)
                if progress:
                    progress(received, total)
        if digest.hexdigest() != expected_sha256:
            raise UpdateError(tr('SHA-256 が一致しません。ファイルを破棄しました'))
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise UpdateError(tr('ダウンロードに失敗しました: {e}', e=e)) from e


def install(release: dict, progress: Callable[[int, int], None] | None = None) -> str:
    """検証済みの zipapp を配置し、その版を返す。"""
    expected = parse_sums(_get(release['sums_url']).decode('utf-8', 'replace'))
    target = paths.updated_ytdlp()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.download')
    _download(release['asset_url'], tmp, expected, MAX_ASSET_BYTES, progress)
    version = bootstrap.read_pyz_version(tmp)
    if not version:
        tmp.unlink(missing_ok=True)
        raise UpdateError(tr('取得したファイルが yt-dlp として読めません'))
    if target.exists():
        os.replace(target, target.with_suffix('.pyz.bak'))
    os.replace(tmp, target)
    return version


def backup_version() -> str | None:
    bak = paths.updated_ytdlp().with_suffix('.pyz.bak')
    return bootstrap.read_pyz_version(bak) if bak.is_file() else None


def rollback() -> str:
    """直前の版へ戻す。戻した版を返す。"""
    target = paths.updated_ytdlp()
    bak = target.with_suffix('.pyz.bak')
    if not bak.is_file():
        raise UpdateError(tr('戻せる版がありません'))
    os.replace(bak, target)
    return bootstrap.read_pyz_version(target) or '?'


def reset_to_bundled() -> None:
    """更新版を消して同梱版に戻す。"""
    target = paths.updated_ytdlp()
    for p in (target, target.with_suffix('.pyz.bak')):
        Path(p).unlink(missing_ok=True)


# --- ffmpeg (yt-dlp 公式の FFmpeg-Builds。yt-dlp 向けのパッチ入り) ---
FFMPEG_BASE = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/'
FFMPEG_ASSET = 'ffmpeg-master-latest-win64-gpl-shared.zip'
FFMPEG_SUMS = 'checksums.sha256'
MAX_FFMPEG_BYTES = 300 * 1024 * 1024


def install_ffmpeg(progress: Callable[[int, int], None] | None = None) -> Path:
    """データフォルダの ffmpeg/bin に展開し、ffmpeg.exe のパスを返す(Windows 専用)。"""
    import shutil
    import zipfile
    if os.name != 'nt':
        raise UpdateError(tr('自動取得は Windows のみ対応です'))
    expected = parse_sums(_get(FFMPEG_BASE + FFMPEG_SUMS).decode('utf-8', 'replace'), FFMPEG_ASSET)
    root = paths.data_dir() / 'ffmpeg'
    root.mkdir(parents=True, exist_ok=True)
    archive = root / 'ffmpeg.zip.download'
    _download(FFMPEG_BASE + FFMPEG_ASSET, archive, expected, MAX_FFMPEG_BYTES, progress)
    staging = root / 'bin.new'
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                parts = member.filename.replace('\\', '/').split('/')
                # <top>/bin/<file> だけを平坦に取り出す(パス横断を防ぐため名前だけ使う)
                if len(parts) == 3 and parts[1] == 'bin' and parts[2] and not member.is_dir():
                    with zf.open(member) as src, open(staging / parts[2], 'wb') as dst:
                        shutil.copyfileobj(src, dst)
        if not (staging / 'ffmpeg.exe').is_file() or not (staging / 'ffprobe.exe').is_file():
            raise UpdateError(tr('アーカイブに ffmpeg.exe / ffprobe.exe がありません'))
        final = root / 'bin'
        old = root / 'bin.old'
        shutil.rmtree(old, ignore_errors=True)
        if final.exists():
            # 実行中の ffmpeg があると消せない。中途半端に消して壊さないよう、先に丸ごと退避する
            try:
                os.replace(final, old)
            except OSError as e:
                raise UpdateError(tr('ffmpeg が使用中のため置き換えられません。ダウンロードの完了後に再実行してください')) from e
        os.replace(staging, final)
        shutil.rmtree(old, ignore_errors=True)
        return final / 'ffmpeg.exe'
    except zipfile.BadZipFile as e:
        raise UpdateError(tr('アーカイブが壊れています: {e}', e=e)) from e
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
