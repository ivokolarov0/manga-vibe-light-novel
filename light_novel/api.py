"""The reader's API, at /api/plugins/light-novel/api/...

- books/<id>: the book's sections (their chapter titles) and where this person is inside one
- books/<id>/sections/<n>: section n as safe HTML (epub.clean)
- books/<id>/file?name=...: a picture of the book
- books/<id>/position (PUT): where this person is inside the section being read

The section itself is the book's progress in MangaVibe (page n = section n), which the reader saves
through the app (ctl.save in reader.js). How far into that section it is (0 to 1) is saved here, per
person, in the plugin's series data.

Every route checks the book the way MangaVibe's own book routes do: it must exist, be a text book in
a library folder, and the person must be allowed to see its series (a locked library refuses).

It uses only MangaVibe's SDK (docs/PLUGINS.md, The SDK): app.plugins.sdk, app.plugins.web, app.users
and the ctx, so a new MangaVibe doesn't break it by moving its insides around.
"""
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import users
from app.plugins.sdk import TEXT_BOOK, Book, Library, Series, visible_series
from app.plugins.web import plugin_ctx

from . import epub

PLUGIN_ID = "light-novel"
BASE = f"/api/plugins/{PLUGIN_ID}/api"
router = APIRouter()


def _book(ctx, request, book_id) -> Book:
    b = ctx.db.get(Book, book_id)
    if b is None or b.missing_since is not None:
        raise HTTPException(404, "Book not found")
    if b.format != TEXT_BOOK:
        raise HTTPException(400, "This book isn't a text book")
    conds = visible_series(ctx.db, request)  # e.g. not in a locked library
    if conds and ctx.db.query(Series.id).filter(Series.id == b.series_id, *conds).first() is None:
        raise HTTPException(403, "This book's library is locked")
    _inside_library(ctx.db, b.path)
    return b


def _inside_library(db, path):
    """Refuse a file outside the library folders (a book row is the app's, but its path is read here)."""
    p = Path(path).resolve()
    for (root,) in db.query(Library.root_path):
        r = Path(root).resolve()
        if p == r or r in p.parents:
            return
    raise HTTPException(403, "File is outside the library folders")


def _read(fn, *args):
    """A read of the book's file through ctx (text_sections, list_entries, read_entry), its failure as an
    HTTP error. Only file reads go through here, so whatever they raise is about the file (the SDK has
    no name for the app's archive error): a damaged or odd EPUB. KeyError (no such entry) is left to
    the caller, which may expect it (epub.toc_entries does)."""
    try:
        return fn(*args)
    except (HTTPException, KeyError):
        raise
    except FileNotFoundError:
        raise HTTPException(404, "The file is missing (moved, or the share isn't mounted?)") from None
    except Exception as e:  # noqa: BLE001 (see above)
        raise HTTPException(409, str(e) or type(e).__name__) from None


class _Cache:
    """A small least-recently-used cache: what was worked out for a version of a book's file."""

    def __init__(self, size):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key, make):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        value = make()
        with self.lock:
            self.items[key] = value
            while len(self.items) > self.size:
                self.items.popitem(last=False)
        return value


_infos, _sections = _Cache(16), _Cache(48)


def _info(ctx, b):
    """(sections, entry names, chapter titles) of a book, read once per version of the file."""
    def make():
        sections = _read(ctx.text_sections, b)
        entries = frozenset(_read(ctx.list_entries, b))
        titles = epub.chapter_titles(lambda name: _read(ctx.read_entry, b, name), sections)
        return sections, entries, titles
    return _infos.get((b.path, b.mtime), make)


def _section(ctx, b, n):
    def make():
        sections, entries, titles = _info(ctx, b)
        name = sections[n]
        doc = _read(ctx.read_entry, b, name).decode("utf-8", "replace")
        file_url = lambda entry: f"{BASE}/books/{b.id}/file?name={epub.url_quote(entry)}&v={int(b.mtime)}"
        return {"section": n, "title": titles[n], **epub.clean(doc, name, sections, entries, file_url)}
    return _sections.get((b.id, b.path, b.mtime, n), make)


def _position_key(book_id):
    return f"pos:{users.current_id()}:{book_id}"


@router.get("/books/{book_id}")
def book(book_id: int, request: Request, ctx=Depends(plugin_ctx)):
    b = _book(ctx, request, book_id)
    _, _, titles = _info(ctx, b)
    return {"sections": [{"title": t} for t in titles],
            "position": ctx.get_series_data(b.series_id, _position_key(b.id))}


@router.get("/books/{book_id}/sections/{n}")
def section(book_id: int, n: int, request: Request, ctx=Depends(plugin_ctx)):
    b = _book(ctx, request, book_id)
    if not 0 <= n < b.page_count:
        raise HTTPException(404, "No such section")
    return _section(ctx, b, n)


@router.get("/books/{book_id}/file")
def file(book_id: int, name: str, request: Request, ctx=Depends(plugin_ctx)):
    b = _book(ctx, request, book_id)
    _, entries, _ = _info(ctx, b)
    mime = epub.file_mime(name)
    if name not in entries or not mime:  # only the book's own pictures
        raise HTTPException(404, "No such picture in this book")
    data = _read(ctx.read_entry, b, name)
    return Response(data, media_type=mime, headers={
        "Cache-Control": "private, max-age=31536000, immutable",  # the URL carries ?v=<mtime>
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})


class Position(BaseModel):
    section: int = Field(ge=0)
    at: float = Field(ge=0, le=1)  # how far into the section: 0 its start, 1 its end


@router.put("/books/{book_id}/position")
def save_position(book_id: int, body: Position, request: Request, ctx=Depends(plugin_ctx)):
    b = _book(ctx, request, book_id)
    if body.section >= b.page_count:
        raise HTTPException(400, "No such section")
    ctx.set_series_data(b.series_id, _position_key(b.id), {"section": body.section, "at": round(body.at, 4)})
    ctx.db.commit()
    return {"ok": True}
