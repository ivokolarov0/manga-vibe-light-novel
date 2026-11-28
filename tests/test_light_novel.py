"""The plugin installed in a running MangaVibe: it reads text books, its API serves safe HTML, the
book's pictures and where each person is inside a section."""
import shutil
import zipfile

import pytest

from tests.conftest import TMP

API = "/api/plugins/light-novel/api"
CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
WORDS = "The lantern swung in the wind while the old ferryman counted the coins again. " * 12
NAV = """<html xmlns:epub="http://www.idpf.org/2007/ops"><body>
  <nav epub:type="landmarks"><ol><li><a href="c0.xhtml">Start</a></li></ol></nav>
  <nav epub:type="toc"><ol>
    <li><a href="c0.xhtml">Prologue</a></li>
    <li><a href="c1.xhtml#top">Chapter 1: The River</a><ol><li><a href="c2.xhtml">Part two</a></li></ol></li>
  </ol></nav></body></html>"""


def chapter(i):
    if i == 1:  # what an EPUB may hold that must never reach the page
        return f"""<h1 id="top" style="text-align:center">Chapter {i}</h1>
          <script>alert(1)</script><style>body {{ display: none }}</style>
          <p onclick="steal()">{WORDS}<a href="javascript:alert(2)">bad</a> <a href="c2.xhtml#n1">note</a>
          <a href="https://example.org/x">site</a></p>
          <svg><image xlink:href="images/pic.png"/></svg><img src="https://tracker.example/p.gif"/>
          <img src="images/missing.png"/><img src="../../outside.png"/><iframe src="https://evil.example"></iframe>
          <p><ruby>漢字<rt>かんじ</rt></ruby><br/></p><p/>"""
    return f'<h2>Part {i}</h2><p id="n1">{WORDS}</p>'


def make_novel(path, chapters=3):
    items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(chapters))
    items += '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    items += '<item id="pic" href="images/pic.png" media-type="image/png"/>'
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(chapters))
    path.parent.mkdir(parents=True, exist_ok=True)
    from tests.conftest import png
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", f"""<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"
          version="3.0"><manifest>{items}</manifest><spine>{spine}</spine></package>""")
        z.writestr("OEBPS/nav.xhtml", NAV)
        z.writestr("OEBPS/images/pic.png", png("red"))
        z.writestr("OEBPS/images/page.svg", "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
        for i in range(chapters):
            z.writestr(f"OEBPS/c{i}.xhtml", f"<html><head><title>t</title></head><body>{chapter(i)}</body></html>")


@pytest.fixture(scope="module")
def novel(client):
    from app.scanner import walker
    make_novel(TMP / "manga" / "Ferryman" / "Ferryman v01.epub")
    walker.scan_all()
    sid = client.get("/api/series?q=Ferryman").json()["items"][0]["id"]
    book = client.get(f"/api/series/{sid}/books").json()[0]
    yield book
    shutil.rmtree(TMP / "manga" / "Ferryman")
    walker.scan_all()


def test_plugin_is_installed_and_reads_text_books(client, novel):
    from app.plugins import manager
    assert manager.get("light-novel") is not None, manager.errors if hasattr(manager, "errors") else ""
    assert client.get(f"/api/books/{novel['id']}").json()["reader"] == "light-novel"
    assert novel["format"] == "epub-text" and novel["page_count"] == 3
    # the page loads the reader's script, which registers itself for the format
    assert '<script src="/plugins/light-novel.js">' in client.get("/").text
    assert 'MangaVibe.registerReader(ID, "epub-text"' in client.get("/plugins/light-novel.js").text


def test_contents_names_the_chapters(client, novel):
    info = client.get(f"{API}/books/{novel['id']}").json()
    assert [s["title"] for s in info["sections"]] == ["Prologue", "Chapter 1: The River", "Part two"]
    assert info["position"] is None


def test_sections_are_made_safe(client, novel):
    sec = client.get(f"{API}/books/{novel['id']}/sections/1").json()
    h = sec["html"]
    for bad in ("<script", "alert(1)", "<style", "display: none", "onclick", "javascript:", "<iframe",
                "evil.example", "tracker.example", "missing.png", "outside.png", "<svg"):
        assert bad not in h, bad
    assert '<h1 id="ln-top" class="ln-center">' in h
    assert f'src="{API}/books/{novel["id"]}/file?name=OEBPS%2Fimages%2Fpic.png' in h  # the svg's picture
    assert 'data-section="2" data-anchor="ln-n1"' in h  # a link to another section
    assert 'href="https://example.org/x" target="_blank" rel="noopener noreferrer"' in h
    assert "<ruby>漢字<rt>かんじ</rt></ruby>" in h
    assert ">bad<" not in h and "bad" in h  # the javascript: link's text stays, without the link
    assert sec["title"] == "Chapter 1: The River" and sec["pictures"] == 1
    assert client.get(f"{API}/books/{novel['id']}/sections/3").status_code == 404


def test_only_the_books_own_pictures(client, novel):
    url = f"{API}/books/{novel['id']}/file"
    r = client.get(url, params={"name": "OEBPS/images/pic.png"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["content-security-policy"] == "default-src 'none'"
    for name in ("OEBPS/images/page.svg", "OEBPS/c1.xhtml", "OEBPS/../../etc/passwd", "nope.png"):
        assert client.get(url, params={"name": name}).status_code == 404, name


def test_position_inside_a_section(client, novel):
    url = f"{API}/books/{novel['id']}/position"
    assert client.put(url, json={"section": 1, "at": 0.42}).json() == {"ok": True}
    assert client.get(f"{API}/books/{novel['id']}").json()["position"] == {"section": 1, "at": 0.42}
    assert client.put(url, json={"section": 9, "at": 0.5}).status_code == 400
    assert client.put(url, json={"section": 1, "at": 2}).status_code == 422


def test_comics_are_refused(client):
    from app.db import SessionLocal
    from app.models import Book
    with SessionLocal() as db:
        comic = db.query(Book).filter(Book.format == "zip").first()
    assert client.get(f"{API}/books/{comic.id}").status_code == 400
    assert client.get(f"{API}/books/999999").status_code == 404


def test_a_locked_library_stays_locked(client, novel):
    from app.db import SessionLocal
    from app.plugins.builtin.libraries import core as shelves
    L = "/api/plugins/libraries/api"
    sid = client.get(f"/api/books/{novel['id']}").json()["series_id"]
    shelf = client.post(f"{L}/shelves", json={"name": "Novels"}).json()["id"]
    try:
        assert client.put(f"{L}/series/{sid}", json={"shelf_id": shelf}).status_code == 200
        assert client.put(f"{L}/shelves/{shelf}/password", json={"password": "secret"}).status_code == 200
        client.post(f"{L}/shelves/{shelf}/lock")
        book = f"{API}/books/{novel['id']}"
        for r in (client.get(book), client.get(f"{book}/sections/0"),
                  client.get(f"{book}/file", params={"name": "OEBPS/images/pic.png"}),
                  client.put(f"{book}/position", json={"section": 0, "at": 0.5})):
            assert r.status_code == 403, r.request.url
        assert client.post(f"{L}/shelves/{shelf}/unlock", json={"password": "secret"}).status_code == 200
        assert client.get(book).status_code == 200
    finally:
        client.cookies.clear()
        with SessionLocal() as db:
            shelves.clear_passwords(db, "all")
        client.put(f"{L}/series/{sid}", json={"shelf_id": 0})
        client.delete(f"{L}/shelves/{shelf}")


def test_imports_only_the_sdk():
    """MangaVibe's SDK (docs/PLUGINS.md, The SDK): anything else in `app` may change in any version."""
    import ast
    from pathlib import Path
    sdk = {"app.plugins", "app.plugins.web", "app.plugins.query", "app.plugins.sdk", "app.users"}
    wrong = []
    for path in (Path(__file__).resolve().parent.parent / "light_novel").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                # from app import users: the module app.users
                mods = [f"app.{a.name}" for a in node.names] if node.module == "app" else [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            else:
                continue
            wrong += [f"{path.name}:{node.lineno} {m}" for m in mods
                      if (m == "app" or m.startswith("app.")) and m not in sdk]
    assert not wrong, wrong


def test_clean_keeps_text_after_odd_markup():
    epub = _local_epub()
    out = epub.clean("<body><p>a<script/>b</p><style/><p>c<meta charset='x'>d</p></body>", "x.xhtml", ["x.xhtml"], set(),
                     lambda n: n)
    assert out["html"] == "<p>ab</p><p>cd</p>"
    out = epub.clean("<body><div><p>open<b>bold</div>after</body>", "x.xhtml", ["x.xhtml"], set(), lambda n: n)
    assert out["html"] == "<div><p>open<b>bold</b></p></div>after"


def _local_epub():
    import importlib.util
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent / "light_novel" / "epub.py"
    spec = importlib.util.spec_from_file_location("ln_epub", here)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
