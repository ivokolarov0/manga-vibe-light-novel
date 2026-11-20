"""What the reader needs from a text EPUB: chapter titles, and each section as safe HTML.

MangaVibe's scan already found the sections (ctx.text_sections(): the spine's documents in reading
order); section n is page n of the book's progress. This module only reads the book, through ctx.

An EPUB's XHTML can hold anything a web page can: scripts, styles, forms, links to other sites, pictures
from the internet. None of it reaches the page as it is. clean() rebuilds each section from a short list
of text elements (paragraphs, headings, emphasis, ruby, lists, tables, pictures), writing every tag and
attribute itself: scripts and styles are dropped with their content, unknown tags are dropped but their
text kept, and pictures and links inside the book point to this plugin's API.
"""
import html
import posixpath
import re
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

# SVG pictures are left out: served from the app's own address, one could run scripts when opened
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
              ".webp": "image/webp", ".avif": "image/avif", ".bmp": "image/bmp"}

# kept as they are (attributes: see _attrs)
ALLOWED = {"p", "div", "span", "section", "article", "aside", "header", "footer", "main", "nav",
           "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "hr", "br", "wbr",
           "em", "strong", "i", "b", "u", "s", "small", "sub", "sup", "mark", "cite", "q", "abbr",
           "ruby", "rb", "rt", "rp", "rtc", "ul", "ol", "li", "dl", "dt", "dd", "figure", "figcaption",
           "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "a", "img"}
VOID = {"br", "hr", "img", "wbr"}
# dropped together with everything inside them
DROP = {"script", "style", "head", "title", "iframe", "object", "embed", "noscript", "template",
        "form", "button", "input", "select", "textarea", "audio", "video", "canvas", "math", "link", "meta",
        "base"}
NO_END = {"link", "meta", "base", "input"}  # dropped tags that never have an end tag
BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li", "figure", "td", "th"}
_ALIGN = re.compile(r"text-align\s*:\s*(center|right|end)", re.I)
_DIGITS = re.compile(r"^\d{1,3}$")


def is_image(name):
    return posixpath.splitext(name.lower())[1] in IMAGE_EXT


def join(base_dir, href):
    """An href inside the book as an entry name ("OEBPS/images/1.jpg"), without its #fragment."""
    return posixpath.normpath(posixpath.join(base_dir, unquote(href.split("#", 1)[0])))


class _Cleaner(HTMLParser):
    def __init__(self, section, sections, entries, file_url):
        super().__init__(convert_charrefs=True)
        self.dir = posixpath.dirname(section)
        self.index = {s: i for i, s in enumerate(sections)}
        self.current = self.index.get(section, 0)
        self.entries = entries
        self.file_url = file_url
        self.out, self.stack, self.skip = [], [], 0
        self.text_len, self.pictures = 0, 0

    # --- tags -------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP:
            if tag not in NO_END:
                self.skip += 1  # until its end tag (one inside another counts too)
            return
        if self.skip:
            return
        attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "image":  # a picture inside <svg>, as many light novels show their illustrations
            tag, attrs = "img", {"src": attrs.get("xlink:href") or attrs.get("href") or ""}
        if tag not in ALLOWED:
            return  # its text is kept, the tag isn't
        written = self._attrs(tag, attrs)
        if written is None:
            return
        if tag == "a" and written == "":
            self.stack.append("#a")  # a link that goes nowhere: its text stays, without the <a>
            return
        self.out.append(f"<{tag}{written}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP:
            return  # <script/>: nothing to drop, and no end tag will come
        self.handle_starttag(tag, attrs)
        if tag not in VOID and tag not in DROP and self.stack and self.stack[-1] in (tag, "#a"):
            self.handle_endtag(tag)  # <p/> in XHTML: open and closed at once

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        want = "#a" if tag == "a" and "#a" in self.stack and "a" not in self.stack else tag
        if want not in self.stack:
            return  # never opened (or not kept): ignore
        while self.stack:  # close what was left open inside it
            top = self.stack.pop()
            if top != "#a":
                self.out.append(f"</{top}>")
            if top == want:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))
            self.text_len += len(data.strip())

    # --- attributes ---------------------------------------------------------
    def _attrs(self, tag, a):
        """The attributes to write, as text (" id=..."), "" for a link that leads nowhere, or None to
        leave the element out (a picture that isn't in the book)."""
        out = {}
        if a.get("id"):
            out["id"] = "ln-" + a["id"]  # ids are prefixed, so they can't collide with the app's
        lang = a.get("xml:lang") or a.get("lang")
        if lang and len(lang) < 20:
            out["lang"] = lang
        if a.get("dir") in ("ltr", "rtl", "auto"):
            out["dir"] = a["dir"]
        if tag in BLOCKS:
            m = _ALIGN.search(a.get("style", ""))
            cls = a.get("class", "").lower()
            if (m and m[1].lower() == "center") or "center" in cls:
                out["class"] = "ln-center"
            elif m or "right" in cls:
                out["class"] = "ln-right"
        if tag in ("td", "th"):
            for k in ("colspan", "rowspan"):
                if _DIGITS.match(a.get(k, "")):
                    out[k] = a[k]
        if tag == "ol" and _DIGITS.match(a.get("start", "")):
            out["start"] = a["start"]
        if tag == "img":
            src = a.get("src", "")
            if not src or urlsplit(src).scheme:
                return None  # pictures from the internet are never loaded
            name = join(self.dir, src)
            if name not in self.entries or not is_image(name):
                return None
            out["src"] = self.file_url(name)
            out["alt"] = a.get("alt", "")[:300]
            out["loading"] = "lazy"
            self.pictures += 1
        if tag == "a":
            href = a.get("href", "").strip()
            link = self._link(href)
            if link is None:
                return ""
            out.update(link)
        return "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in out.items())

    def _link(self, href):
        if not href:
            return None
        parts = urlsplit(href)
        if parts.scheme in ("http", "https"):
            return {"href": href, "target": "_blank", "rel": "noopener noreferrer"}
        if parts.scheme or parts.netloc:
            return None  # javascript:, data:, mailto:...: not followed
        frag = unquote(parts.fragment)
        if not parts.path:
            section = self.current
        else:
            section = self.index.get(join(self.dir, href))
            if section is None:
                return None
        # the reader follows it (reader.js): another section, and the place in it
        return {"href": "#", "data-section": str(section), "data-anchor": ("ln-" + frag) if frag else ""}

    def result(self):
        while self.stack:
            top = self.stack.pop()
            if top != "#a":
                self.out.append(f"</{top}>")
        return "".join(self.out)


def clean(doc: str, section: str, sections: list, entries: set, file_url) -> dict:
    """{"html": the section's body as safe HTML, "text": how many letters it has, "pictures": how many}.
    file_url(entry name) is the address the page loads a picture of the book from."""
    p = _Cleaner(section, sections, entries, file_url)
    body = re.search(r"<body\b[^>]*>(.*)</body>", doc, re.I | re.S)
    p.feed(body.group(1) if body else doc)
    p.close()
    return {"html": p.result(), "text": p.text_len, "pictures": p.pictures}


# ---------------------------------------------------------------- the table of contents

def _package(read):
    container = ElementTree.fromstring(read("META-INF/container.xml"))
    opf_path = container.find(".//{*}rootfile").get("full-path")
    opf = ElementTree.fromstring(read(opf_path))
    return opf_path, opf


class _NavParser(HTMLParser):
    """The links of an EPUB 3 nav document's <nav epub:type="toc">, in order: [(href, title)]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.href, self.text, self.links = 0, None, [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "nav":
            if self.depth or "toc" in (a.get("epub:type") or "").split():
                self.depth += 1
        elif self.depth and tag == "a":
            self.href, self.text = a.get("href"), []

    def handle_endtag(self, tag):
        if tag == "nav" and self.depth:
            self.depth -= 1
        elif tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join("".join(self.text).split())))
            self.href = None

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)


def toc_entries(read) -> list:
    """[(entry name of the section, title)] from the book's table of contents, in its order: the EPUB 3
    nav document, else the EPUB 2 NCX. [] when it has neither or they can't be read.
    read(name) gives the bytes of an entry."""
    try:
        opf_path, opf = _package(read)
    except (KeyError, AttributeError, ElementTree.ParseError):
        return []
    base = posixpath.dirname(opf_path)
    items = {i.get("id"): i for i in opf.findall(".//{*}manifest/{*}item")}
    nav = next((i for i in items.values() if "nav" in (i.get("properties") or "").split()), None)
    if nav is not None:
        href = join(base, nav.get("href") or "")
        try:
            p = _NavParser()
            p.feed(read(href).decode("utf-8", "replace"))
            found = [(join(posixpath.dirname(href), h), t) for h, t in p.links if h]
            if found:
                return found
        except KeyError:
            pass
    spine = opf.find(".//{*}spine")
    ncx = items.get(spine.get("toc")) if spine is not None else None
    if ncx is None:
        ncx = next((i for i in items.values() if i.get("media-type") == "application/x-dtbncx+xml"), None)
    if ncx is None:
        return []
    href = join(base, ncx.get("href") or "")
    try:
        root = ElementTree.fromstring(read(href))
    except (KeyError, ElementTree.ParseError):
        return []
    out = []
    for point in root.iter("{*}navPoint"):
        label = point.find("{*}navLabel/{*}text")
        content = point.find("{*}content")
        if content is not None and content.get("src"):
            title = " ".join((label.text or "").split()) if label is not None else ""
            out.append((join(posixpath.dirname(href), content.get("src")), title))
    return out


def chapter_titles(read, sections: list) -> list:
    """A title for every section ("" when the contents don't name it): the contents' first entry that
    points into it, and the sections after it without one of their own are part of that chapter."""
    index = {s: i for i, s in enumerate(sections)}
    titles = [""] * len(sections)
    for name, title in toc_entries(read):
        i = index.get(name)
        if i is not None and title and not titles[i]:
            titles[i] = title
    return titles


def file_mime(name):
    return IMAGE_MIME.get(posixpath.splitext(name.lower())[1])


def url_quote(name):
    return quote(name, safe="")
