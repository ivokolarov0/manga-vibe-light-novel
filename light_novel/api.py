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
"""
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import users
from app.api.common import ensure_inside_library
from app.api.filters import hidden_from
from app.models import Book
from app.plugins.web import plugin_ctx
from app.scanner import archives

from . import epub

PLUGIN_ID = "light-novel"
BASE = f"/api/plugins/{PLUGIN_ID}/api"
router = APIRouter()


def _book(ctx, request, book_id) -> Book:
    b = ctx.db.get(Book, book_id)
    if b is None or b.missing_since is not None:
        raise HTTPException(404, "Book not found")
    if b.format != archives.TEXT_BOOK:
        raise HTTPException(400, "This book isn't a text book")
    if hidden_from(ctx.db, request, [b.series_id]):  # e.g. a locked library
        raise HTTPException(403, "This book's library is locked")
    ensure_inside_library(ctx.db, b.path)
    return b


def _readable(fn, *args):
    try:
        return fn(*args)
    except archives.ArchiveError as e:
        raise HTTPException(409, str(e)) from None
    except FileNotFoundError:
        raise HTTPException(404, "The file is missing (moved, or the share isn't mounted?)") from None


@lru_cache(maxsize=16)
def _info(path, mtime):
    """(sections, entry names, chapter titles) of a book, read once per version of the file."""
    sections = archives.text_sections(path)
    entries = frozenset(archives.list_entries(path, archives.TEXT_BOOK))
    titles = epub.chapter_titles(lambda name: archives.read_entry(path, archives.TEXT_BOOK, name), sections)
    return sections, entries, titles


@lru_cache(maxsize=48)
def _section(book_id, path, mtime, n):
    sections, entries, titles = _info(path, mtime)
    name = sections[n]
    doc = archives.read_entry(path, archives.TEXT_BOOK, name).decode("utf-8", "replace")
    file_url = lambda entry: f"{BASE}/books/{book_id}/file?name={epub.url_quote(entry)}&v={int(mtime)}"
    return {"section": n, "title": titles[n], **epub.clean(doc, name, sections, entries, file_url)}


def _position_key(book_id):
    return f"pos:{users.current_id()}:{book_id}"


@router.get("/books/{book_id}")
def book(book_id: int, request: Request, ctx=Depends(plugin_ctx)):
    b = _book(ctx, request, book_id)
    sections, _, titles = _readable(_info, b.path, b.mtime)
    return {"sections": [{"title": t} for t in titles],
            "position": ctx.get_series_data(b.series_id, _position_key(b.id))}


@router.get("/books/{book_id}/sections/{n}")
def section(book_id: int, n: int, request: Request, ctx=Depends(plugin_ctx)):
    b = _book(ctx, request, book_id)
    if not 0 <= n < b.page_count:
        raise HTTPException(404, "No such section")
    return _readable(_section, b.id, b.path, b.mtime, n)


@router.get("/books/{book_id}/file")
def file(book_id: int, name: str, request: Request, ctx=Depends(plugin_ctx)):
    b = _book(ctx, request, book_id)
    _, entries, _ = _readable(_info, b.path, b.mtime)
    mime = epub.file_mime(name)
    if name not in entries or not mime:  # only the book's own pictures
        raise HTTPException(404, "No such picture in this book")
    data = _readable(archives.read_entry, b.path, archives.TEXT_BOOK, name)
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
