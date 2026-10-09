"""Fetch PDFs from links. A link may point at a PDF, or at a web page whose
linked PDFs are discovered (same host only, up to a limit).

Every request and redirect hop is checked against internal addresses unless
``allow_private_urls`` is set, so a shared server cannot be used to reach
internal systems. Residual risk: a hostile DNS server could answer differently
between our check and the connection (DNS rebinding). Run shared deployments
behind an egress proxy if that matters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from . import __version__
from .config import Settings
from .intake import PDF_MAGIC, InputFile, safe_relpath
from .netguard import BlockedURL, check_public_url

USER_AGENT = f"pdf-remediation/{__version__} (+accessibility remediation)"
MAX_HTML_BYTES = 5 * 1024 * 1024


@dataclass
class FetchResult:
    files: list[InputFile] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.base: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and a.get("href"):
            self.base = a["href"]
        if tag in ("a", "link", "iframe", "embed", "object"):
            href = a.get("href") or a.get("src") or a.get("data")
            if href:
                self.links.append(href)


def _is_pdf_link(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(".pdf") or ".pdf?" in url.lower()


def _filename_for(url: str, response: httpx.Response) -> str:
    cd = response.headers.get("content-disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd, re.I)
    name = unquote(m.group(1)) if m else unquote(Path(urlsplit(url).path).name)
    name = safe_relpath(name).split("/")[-1] or "document.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def _get(client: httpx.Client, url: str, settings: Settings, max_bytes: int) -> tuple[str, httpx.Response, bytes]:
    for _ in range(6):
        check_public_url(url, settings.allow_private_urls)
        with client.stream("GET", url) as r:
            if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"download exceeds {max_bytes // (1024 * 1024)} MB")
                chunks.append(chunk)
            return url, r, b"".join(chunks)
    raise ValueError("too many redirects")


def fetch_inputs(urls: list[str], dest: Path, settings: Settings) -> FetchResult:
    res = FetchResult()
    dest.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_file_mb * 1024 * 1024
    used_names: set[str] = set()
    fetched: set[str] = set()

    def save(url: str, response: httpx.Response, body: bytes, label: str) -> None:
        if url in fetched:
            res.messages.append(f"{url}: already added")
            return
        fetched.add(url)
        name = _filename_for(url, response)
        rel = f"{label}/{name}" if label else name
        base, n = rel, 1
        while rel.lower() in used_names:
            n += 1
            rel = f"{Path(base).with_suffix('')}-{n}.pdf"
        used_names.add(rel.lower())
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        res.files.append(InputFile(target, rel, "url"))

    with httpx.Client(timeout=settings.url_timeout, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT}) as client:
        for raw in urls:
            url = raw.strip()
            if not url:
                continue
            if not re.match(r"^https?://", url, re.I):
                url = "https://" + url
            try:
                final, r, body = _get(client, url, settings, max(max_bytes, MAX_HTML_BYTES))
            except (BlockedURL, httpx.HTTPError, ValueError) as exc:
                res.messages.append(f"{url}: {exc}")
                continue
            ctype = r.headers.get("content-type", "").lower()
            if body[:1024].find(PDF_MAGIC) >= 0:
                if len(body) > max_bytes:
                    res.messages.append(f"{url}: larger than {settings.max_file_mb} MB")
                    continue
                save(final, r, body, "")
                continue
            if "html" not in ctype and not body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
                res.messages.append(f"{url}: not a PDF or a web page ({ctype or 'unknown type'})")
                continue
            parser = _LinkParser()
            parser.feed(body[:MAX_HTML_BYTES].decode(r.encoding or "utf-8", errors="replace"))
            base = urljoin(final, parser.base) if parser.base else final
            host = urlsplit(final).hostname
            seen, found = set(), []
            for href in parser.links:
                absolute = urljoin(base, href.strip()).split("#")[0]
                if _is_pdf_link(absolute) and urlsplit(absolute).hostname == host and absolute not in seen:
                    seen.add(absolute)
                    found.append(absolute)
            if not found:
                res.messages.append(f"{url}: no PDF links found on this page (same site only)")
                continue
            if len(found) > settings.max_discovered_pdfs:
                res.messages.append(f"{url}: {len(found)} PDFs found; only the first "
                                    f"{settings.max_discovered_pdfs} were fetched")
                found = found[: settings.max_discovered_pdfs]
            label = safe_relpath(host or "site")
            for pdf_url in found:
                if pdf_url in fetched:
                    res.messages.append(f"{pdf_url}: already added")
                    continue
                try:
                    f2, r2, b2 = _get(client, pdf_url, settings, max_bytes)
                except (BlockedURL, httpx.HTTPError, ValueError) as exc:
                    res.messages.append(f"{pdf_url}: {exc}")
                    continue
                if b2[:1024].find(PDF_MAGIC) < 0:
                    res.messages.append(f"{pdf_url}: link did not return a PDF")
                    continue
                save(f2, r2, b2, label)
            res.messages.append(f"{url}: found {len(found)} linked PDF(s)")
    return res
