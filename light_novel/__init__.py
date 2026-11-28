"""Light novel reader: reads the text EPUBs in a MangaVibe library (light novels) as text, with the
font, size, spacing, colours and layout each reader likes. A folder plugin: this folder goes into
MangaVibe's data folder as plugins/light_novel/ (see the README). Needs Plugin API 38 (MangaVibe 3.11.0):
the reader itself is API 14, it imports only the SDK (API 22), and its buttons and choices are the UI
kit's in its new look (API 38).

MangaVibe's scan keeps a text EPUB as a book of format "epub-text" whose sections (the spine's
documents) count as its pages, so progress, Continue reading and tracker sync work as for any book.
This plugin says it reads that format (`reads`) and gives the page the reader for it.

- epub.py: chapter titles from the book's contents, and each section rebuilt as safe HTML
- api.py: its API at /api/plugins/light-novel/api/... (sections, pictures, where you are in a section)
- reader.js, reader.css: the reader (MangaVibe.registerReader)
"""
from pathlib import Path

from app.plugins import API_VERSION, Plugin

if API_VERSION < 38:
    raise RuntimeError("Light novel reader needs a newer MangaVibe (3.11.0, Plugin API 38): update MangaVibe first.")

from . import api  # noqa: E402

HERE = Path(__file__).parent


def _read(name):
    return (HERE / name).read_text(encoding="utf-8")


class LightNovelReader(Plugin):
    id = api.PLUGIN_ID
    name = "Light novel reader"
    version = "1.2.0"  # a release tagged v<version> is offered as an update (see README)
    repo = "ivokolarov0/manga-vibe-light-novel"
    category = "reader"
    description = ("Reads light novels (text EPUBs) as text: chapters, contents, font, size, spacing, "
                   "colours, and pages or scrolling. Picks up where you left off, inside the chapter too.")
    permissions = ["Reads the text EPUBs in your library; connects to nothing",
                   "Keeps where each person is inside a chapter in MangaVibe's database"]
    reads = ["epub-text"]
    router = api.router
    js = _read("reader.js")
    css = _read("reader.css")
