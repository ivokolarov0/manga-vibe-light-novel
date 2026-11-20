# Light novel reader for MangaVibe

A [MangaVibe](https://github.com/ivokolarov0/manga-vibe) plugin that reads **light novels**: EPUBs
that are text, not pictures. MangaVibe finds them in your library and counts each chapter of the book
like a page, so progress, Continue reading, Read/Unread and tracker sync (AniList, MyAnimeList) work
as for manga. This plugin is the reader that shows them.

- **Chapters and contents**: the book's own table of contents, a button for the next chapter, and the
  next volume at the end of the book. Links inside the book (notes, references) work.
- **Text the way you like it**: size, serif or sans, line spacing, width, justified or not, and four
  colour themes (Dark, Black, Sepia, Light). Saved on each device.
- **Scroll or pages**: one long scroll per chapter, or pages that turn with a tap on the sides, a
  swipe, the arrow keys or the Android app's volume keys.
- **Picks up where you left off**, inside the chapter too, on any device, for each person.
- **Illustrations** from the book, and furigana (ruby) for Japanese.
- **Safe**: the book's text is rebuilt from a short list of text elements before it reaches the page.
  Scripts, styles, forms and anything from the internet inside an EPUB are dropped.

## What you need

- **A MangaVibe release newer than 2.20.1** (Plugin API 14). Older versions list light novels under
  **Settings → Needs attention → Not supported** and refuse to load this plugin (Settings → Plugins
  says why). Until the next release, use a checkout of MangaVibe's `main`.

## Install

The plugin is the `light_novel/` folder. Copy it into MangaVibe's data folder as `plugins/light_novel/`:

1. Download this repo (**Code → Download ZIP**, or the newest release's source zip) and unpack it.
2. Copy the `light_novel` folder into the `plugins` folder of your data folder:
   `docker/mangavibe/plugins/light_novel` on a Synology, or `plugins/light_novel` inside the folder
   you mounted as `/data` (create `plugins` if it isn't there). For a local checkout:
   `<DATA_DIR>/plugins/light_novel/` (for `preview.py`, `dev-data/plugins/light_novel/`).
3. In MangaVibe: **Settings → Plugins → Reload plugins** (or restart the app).

Light novels already in your library open in it straight away: no new scan is needed. A series whose
books are mostly light novels is matched to the novel on AniList, not to its manga adaptation.

For development on Windows, a directory junction saves copying after each change:

```
mklink /J D:\projects\manga-vibe\dev-data\plugins\light_novel D:\projects\manga-vibe-light-novel\light_novel
```

## Use

Open a light novel like any book. Tap the middle of the text to show or hide the bars.

| | |
|---|---|
| ☰ (top) | Contents |
| Sliders (top) | Text and layout |
| ‹ › (bottom) | Previous / next chapter |
| → ← Space PageDown PageUp | Next / previous screen or page, on to the next chapter at the end |
| Esc | Close a panel, then leave the book |
| F | Fullscreen |

Reaching the end of the last chapter marks the book read.

## Updates

**Settings → Plugins → Light novel reader → Updates** (Check for updates, Update to vX). It installs
the `light_novel/` folder from the newest release's source zip. Your reading places are kept.

- **To publish a version:** raise `version` in `light_novel/__init__.py`, push it, then create a
  release tagged `v<version>` (e.g. `gh release create v1.1.0 --generate-notes`). Nothing is offered
  before the release.
- An installed copy that is a link to a checkout (the junction above) isn't updated this way: update
  the checkout with git.

## How it works

- `light_novel/__init__.py`: the plugin. `reads = ["epub-text"]` tells MangaVibe it reads text books.
- `light_novel/epub.py`: chapter titles from the book's contents (EPUB 3 nav, or EPUB 2 NCX), and each
  section rebuilt as safe HTML.
- `light_novel/api.py`: its API at `/api/plugins/light-novel/api/...`. Every route checks the book the
  way MangaVibe's own book routes do, so a locked library stays locked.
- `light_novel/reader.js`, `reader.css`: the reader, given to MangaVibe with `MangaVibe.registerReader()`.

See MangaVibe's `docs/PLUGINS.md`, "A reader of its own".

## Development

The tests run the MangaVibe app (a checkout next to this repo, `../manga-vibe`, or `MANGAVIBE_DIR`)
with the plugin installed, using the app's own Python:

```
..\manga-vibe\.venv\Scripts\python -m pytest        (Windows)
../manga-vibe/.venv/bin/python -m pytest            (Linux/macOS)
```

## Licence

MIT. See [LICENSE](LICENSE).
