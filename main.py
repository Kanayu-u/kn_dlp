"""kn_dlp エントリポイント。`--worker` で yt-dlp 実行用の子プロセスとして動く。"""
import sys


def run() -> int:
    if '--worker' in sys.argv[1:]:
        from kn_dlp.worker import main as worker_main
        return worker_main()
    from kn_dlp.ui.app import main as gui_main
    return gui_main()


if __name__ == '__main__':
    sys.exit(run())
