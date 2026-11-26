"""Journal (blog) helpers: a small, safe text-to-HTML renderer + post utilities.

Article bodies are written in the admin with a few simple marks (no HTML):

    ## Heading            ### Smaller heading
    **bold**  *italic*    [link text](/products/parisian)
    - bullet              1. numbered
    > quote               ---  (divider line)
    ![alt text](image-url "optional caption")   <- a picture on its own line

Everything is HTML-escaped first, so nothing typed in the admin can inject
markup or scripts into the public page.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Optional

from markupsafe import Markup, escape

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORDS_PER_MINUTE = 220

_IMG_LINE = re.compile(r'^!\[([^\]]*)\]\(\s*([^\s)]+)(?:\s+"([^"]*)")?\s*\)$')
_LINK = re.compile(r"\[([^\]]+)\]\(\s*([^\s)]+)\s*\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])")
_OL_ITEM = re.compile(r"^\d+[.)]\s+")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:90].strip("-")


def safe_url(url: str) -> str:
    """Only allow web, site-relative, anchor and mail links. Anything else -> '#'."""
    u = (url or "").strip()
    if u.startswith(("https://", "http://", "/", "#", "mailto:")) and not u.startswith("//"):
        return u
    return "#"


def _is_external(url: str) -> bool:
    return url.startswith(("http://", "https://")) and "maisonhenius.com" not in url


def _inline(text: str) -> str:
    """Escape, then apply link / bold / italic marks."""
    out = str(escape(text))

    def link(m):
        label, url = m.group(1), safe_url(m.group(2).replace("&amp;", "&"))
        url_attr = str(escape(url))
        if _is_external(url):
            return f'<a href="{url_attr}" target="_blank" rel="noopener">{label}</a>'
        return f'<a href="{url_attr}">{label}</a>'

    out = _LINK.sub(link, out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return out


def _figure(alt: str, url: str, caption: Optional[str], resolve) -> str:
    src = resolve(safe_url(url)) if resolve else safe_url(url)
    cap = f"<figcaption>{escape(caption)}</figcaption>" if caption else ""
    return (f'<figure class="article-figure"><img src="{escape(src)}" alt="{escape(alt)}" '
            f'loading="lazy" decoding="async">{cap}</figure>')


def render_body(text: str, resolve=None) -> Markup:
    """Turn the admin's simple marks into safe HTML."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    html: list[str] = []
    para: list[str] = []
    list_kind: Optional[str] = None
    list_items: list[str] = []
    quote: list[str] = []

    def flush_para():
        if para:
            html.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()

    def flush_list():
        nonlocal list_kind
        if list_kind:
            items = "".join(f"<li>{_inline(i)}</li>" for i in list_items)
            html.append(f"<{list_kind}>{items}</{list_kind}>")
            list_items.clear()
            list_kind = None

    def flush_quote():
        if quote:
            html.append("<blockquote>" + "<br>".join(_inline(q) for q in quote) + "</blockquote>")
            quote.clear()

    def flush_all():
        flush_para(); flush_list(); flush_quote()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_all()
            continue
        m = _IMG_LINE.match(line)
        if m:
            flush_all()
            html.append(_figure(m.group(1), m.group(2), m.group(3), resolve))
            continue
        if line.startswith("### "):
            flush_all(); html.append(f"<h3>{_inline(line[4:])}</h3>"); continue
        if line.startswith("## "):
            flush_all(); html.append(f"<h2>{_inline(line[3:])}</h2>"); continue
        if line in ("---", "***"):
            flush_all(); html.append('<hr class="article-divider">'); continue
        if line.startswith("> "):
            flush_para(); flush_list(); quote.append(line[2:]); continue
        if line.startswith(("- ", "* ")):
            flush_para(); flush_quote()
            if list_kind != "ul":
                flush_list(); list_kind = "ul"
            list_items.append(line[2:]); continue
        if _OL_ITEM.match(line):
            flush_para(); flush_quote()
            if list_kind != "ol":
                flush_list(); list_kind = "ol"
            list_items.append(_OL_ITEM.sub("", line, count=1)); continue
        flush_list(); flush_quote()
        para.append(line)
    flush_all()
    return Markup("\n".join(html))


def plain_text(text: str) -> str:
    """Body text without marks — for word counts, excerpts and search snippets."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    t = _LINK.sub(r"\1", t)
    t = re.sub(r"^#{2,3}\s+|^>\s+|^[-*]\s+|^\d+[.)]\s+", "", t, flags=re.M)
    t = t.replace("**", "").replace("*", "").replace("---", " ")
    return re.sub(r"\s+", " ", t).strip()


def reading_minutes(text: str) -> int:
    words = len(plain_text(text).split())
    return max(1, math.ceil(words / WORDS_PER_MINUTE))


def parse_list(value) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        items = (value or "").split(",")
    return [str(i).strip() for i in items if str(i).strip()]


def parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_live(post: dict, now: Optional[datetime] = None) -> bool:
    """Published AND its publish date has arrived (future dates = scheduled)."""
    if (post.get("status") or "draft") != "published":
        return False
    dt = parse_dt(post.get("published_at"))
    return dt is None or dt <= (now or datetime.now(timezone.utc))


def enrich(post: dict) -> dict:
    """Add the derived fields every template uses."""
    p = dict(post)
    p["tags_list"] = parse_list(p.get("tags"))
    p["related_list"] = parse_list(p.get("related_products"))
    p["reading_minutes"] = reading_minutes(p.get("body", ""))
    dt = parse_dt(p.get("published_at"))
    p["published_dt"] = dt
    p["published_iso"] = dt.isoformat() if dt else ""
    p["published_human"] = f"{dt.day} {dt.strftime('%B %Y')}" if dt else ""
    up = parse_dt(p.get("updated_at")) or dt
    p["updated_iso"] = up.isoformat() if up else p["published_iso"]
    p["seo_title_final"] = (p.get("seo_title") or "").strip() or f"{p.get('title', '')} | Maison Henius"
    p["meta_description_final"] = ((p.get("meta_description") or "").strip()
                                   or (p.get("excerpt") or "").strip()
                                   or plain_text(p.get("body", ""))[:155])
    return p


# Fields the admin may write. Everything else in a request body is ignored.
TEXT_FIELDS = (
    "title", "slug", "excerpt", "body", "category", "author", "hero_image", "hero_alt",
    "hero_caption", "seo_title", "meta_description", "focus_keyword", "secondary_keywords",
    "og_image", "social_caption", "cta_label", "cta_url", "tags", "related_products",
)
STATUSES = {"draft", "published"}


def validate_payload(body: dict, *, creating: bool):
    """Clean an admin payload. Returns (data, error)."""
    out: dict = {}
    for f in TEXT_FIELDS:
        if f in body:
            v = body.get(f)
            if isinstance(v, list):
                v = ", ".join(str(i).strip() for i in v if str(i).strip())
            out[f] = (v or "").strip() if isinstance(v, str) else str(v or "").strip()
    if creating or "title" in out:
        if not out.get("title"):
            return None, "Title is required"
    if creating and not out.get("slug"):
        out["slug"] = slugify(out.get("title", ""))
    if "slug" in out:
        out["slug"] = slugify(out["slug"])
        if not out["slug"] or not SLUG_RE.fullmatch(out["slug"]):
            return None, "Web address must use lowercase letters, numbers and dashes"
    for url_field in ("hero_image", "og_image", "cta_url"):
        if out.get(url_field) and safe_url(out[url_field]) == "#":
            return None, f"{url_field.replace('_', ' ').title()} must start with https:// or /"
    if "status" in body or creating:
        status = (body.get("status") or "draft").strip().lower()
        if status not in STATUSES:
            return None, "Status must be draft or published"
        out["status"] = status
    if "is_featured" in body:
        out["is_featured"] = bool(body.get("is_featured"))
    if "published_at" in body:
        dt = parse_dt(body.get("published_at"))
        if body.get("published_at") and not dt:
            return None, "Publish date is not a valid date"
        out["published_at"] = dt.isoformat() if dt else None
    if out.get("status") == "published" and creating and not out.get("published_at"):
        out["published_at"] = datetime.now(timezone.utc).isoformat()
    return out, None
