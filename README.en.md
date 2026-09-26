# KN DLP

[日本語](README.md) | **English**

A desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp) on Windows.
Version: **0.1.0** / License: **GPL-3.0**

## Features

| Feature | Details |
|---|---|
| URL analysis | Shows thumbnail, title, duration, subtitle languages, chapter count and number of formats. Paste a URL or drop it onto the window |
| Formats | Video: quality (best to 360p) and container (auto/MP4/MKV/WebM). Audio: MP3/M4A/Opus/FLAC/WAV. You can also pick a video and an audio format from the format list and merge them |
| Queue | 1–8 parallel downloads. Pause and resume where it stopped; cancelling deletes partial files. Shows progress, speed and time left |
| Clip a section | Download only the part between a start and end time. "Cut precisely" re-encodes for exact cuts |
| Subtitles, chapters, thumbnail | Choose subtitle languages, include auto-generated ones, embed subtitles/chapters/thumbnail/metadata |
| History | Stored in SQLite. Search, play, open folder, or download again with the same settings |
| yt-dlp updates | Fetches the latest official release, verifies SHA-256 and swaps it in. Roll back to the previous or bundled version. No app restart needed |
| Profiles | Save combinations of settings by name. Four built-in profiles |
| Live & schedule | Wait for a live stream/premiere to start and record it, or schedule a start time |
| Cookies | Use cookies from your browser or a cookies.txt file. Cookies are never stored by the app |
| Errors | Common failures are summarized with a suggested fix (the original message stays in the log) |
| Languages | Japanese, English, Korean, Simplified Chinese. Follows the OS language by default; change it in Settings (takes effect after restart) |
| Themes | System / Dark / Light, applied instantly |

## Requirements

- Windows 10 / 11 (x64)
- **ffmpeg**: needed for merging, audio conversion, clipping and embedding. Use "Download ffmpeg" in Settings to get the official yt-dlp build
- **JS runtime** (deno, Node.js or Bun): needed to solve YouTube signatures. Detected automatically

## Usage (release build)

1. Download `kn_dlp-<version>-win64.zip` from [Releases](../../releases), extract it and run `kn_dlp.exe`
2. On first launch, check in Settings that ffmpeg and a JS runtime were detected
3. Enter a URL in "New download", analyze it and add it to the queue

Data (settings, history, updated yt-dlp, ffmpeg) is stored in `%LOCALAPPDATA%\kn_dlp`.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts\fetch_ytdlp.py      # fetch vendor/yt-dlp.pyz
.\scripts\devrun.ps1                               # run
.\.venv\Scripts\python -m unittest discover -s tests
.\scripts\build.ps1                                # build exe and zip into dist/
```

### Translations

UI strings use the Japanese source text as the key, looked up with `tr('source')` (same idea as gettext).
To add a language, create `kn_dlp/i18n/<code>.py` with a dict `T`, then register it in `LANG_NAMES` and `_load`
in `kn_dlp/i18n/__init__.py` and in `LANGUAGES` in `kn_dlp/settings.py`. `tests/test_i18n.py` reports missing or
unused entries and placeholder mismatches.

### Layout

```
main.py                 entry point (--worker runs as the yt-dlp child process)
kn_dlp/
  bootstrap.py          loads the newer of the bundled / updated yt-dlp.pyz
  options.py            job spec -> YoutubeDL options (Qt-free, unit tested)
  worker.py             child process; talks to the GUI with JSON Lines
  updater.py            downloads yt-dlp / ffmpeg (SHA-256 check, URL allowlist)
  history.py settings.py errors.py tools.py timeparse.py paths.py
  i18n/                 translation tables (key = Japanese source; en / ko / zh_CN)
  ui/                   PySide6 screens (queue.py drives the queue, theme.py the colors)
```

- yt-dlp runs in **a separate process per download**. Cancelling stops the whole process tree including ffmpeg, and an updated yt-dlp is picked up by the next job
- The release build does not freeze yt-dlp into the exe; it ships the official zipapp as `_internal/vendor/yt-dlp.pyz`. Updating places a newer one in the data folder

## Known limitations

- The queue is not saved when the app exits (finished items remain in history)
- Chrome / Edge cookies may be unreadable because of newer encryption or file locks while the browser is running. Firefox or cookies.txt is recommended
- Thumbnails cannot be embedded in WebM or WAV; they are saved as a separate image file instead
- The English, Korean and Chinese translations have not been reviewed by native speakers. Suggestions are welcome
- The exe is not code-signed, so SmartScreen or antivirus software may show a warning

## License and disclaimer

This app is licensed under the GNU General Public License v3.0 (`LICENSE`). See `THIRD_PARTY_NOTICES.md` for bundled components.
You are responsible for the rights to what you download and for following each site's terms of service.
