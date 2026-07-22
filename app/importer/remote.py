from __future__ import annotations

import html
import json
import logging
import re
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

REMOTE_PREFIX = "remote:\n"
_ALLOWED_HOST_SUFFIX = ".mlazemna.com"
_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36 "
    "SixthResultsBot/1.1"
)
_PDF_RE = re.compile(r"(?i)(?:https?://[^\s\"'<>]+|[^\s\"'<>]+)\.pdf(?:\?[^\s\"'<>]*)?")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "link", "script"}:
            return
        attrs_dict = dict(attrs)
        value = attrs_dict.get("href") or attrs_dict.get("src")
        if value:
            self.links.append(value)


def encode_remote_source(urls: Iterable[str]) -> str:
    cleaned = validate_source_urls(urls)
    return REMOTE_PREFIX + "\n".join(cleaned)


def decode_remote_source(value: str) -> list[str]:
    if not value.startswith("remote:"):
        return []
    payload = value[len("remote:") :].strip()
    return validate_source_urls(payload.splitlines())


def validate_source_urls(urls: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        raw = raw.strip()
        if not raw:
            continue
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != "https":
            raise ValueError("يجب أن يبدأ رابط المصدر بـ https://")
        if not _host_allowed(parsed.hostname):
            raise ValueError("يسمح فقط بروابط موقع ملازمنا mlazemna.com")
        normalized = urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))
        if not normalized.lower().endswith(".pdf") and not parsed.query:
            normalized = normalized.rstrip("/") + "/"
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    if not result:
        raise ValueError("ألصق رابط مجلد واحد على الأقل من مركز نتائجنا")
    if len(result) > 20:
        raise ValueError("الحد الأعلى 20 رابطًا في عملية استيراد واحدة")
    return result


def _host_allowed(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower().rstrip(".")
    return host == "mlazemna.com" or host.endswith(_ALLOWED_HOST_SUFFIX)


def _request(url: str, timeout: int, *, accept_json: bool = False):
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json,text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8"
        if accept_json
        else "application/pdf,text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar,en-US;q=0.8,en;q=0.6",
        "Cache-Control": "no-cache",
    }
    return urlopen(Request(url, headers=headers), timeout=timeout)


def _absolute_candidate(base_url: str, candidate: str) -> str | None:
    value = html.unescape(candidate).strip().replace("\\/", "/")
    if not value or value.startswith(("#", "javascript:", "data:", "mailto:")):
        return None
    absolute = urljoin(base_url, value)
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() != "https" or not _host_allowed(parsed.hostname):
        return None
    # Keep useful query strings on files, but remove fragments everywhere.
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


def _is_pdf(url: str) -> bool:
    return unquote(urlsplit(url).path).lower().endswith(".pdf")


def _is_directory(url: str) -> bool:
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    return path.endswith("/") and "_h5ai" not in path


def _within_root(url: str, root_url: str) -> bool:
    parsed = urlsplit(url)
    root = urlsplit(root_url)
    if parsed.hostname != root.hostname:
        return False
    path = unquote(parsed.path)
    root_path = unquote(root.path)
    if _is_pdf(root_url):
        return path == root_path
    root_path = root_path.rstrip("/") + "/"
    return path.startswith(root_path)


def _walk_json_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        # H5AI versions differ, but href/name/path/url are the useful fields.
        for key in ("href", "url", "path", "name", "src"):
            field = value.get(key)
            if isinstance(field, str):
                yield field
        for child in value.values():
            yield from _walk_json_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_strings(child)


def _extract_from_json(base_url: str, payload: Any) -> set[str]:
    found: set[str] = set()
    for value in _walk_json_strings(payload):
        candidate = _absolute_candidate(base_url, value)
        if candidate and (_is_pdf(candidate) or _is_directory(candidate)):
            found.add(candidate)
    return found


def _extract_from_html(base_url: str, text: str) -> set[str]:
    parser = _LinkParser()
    try:
        parser.feed(text)
    except Exception:
        logger.debug("HTML parser failed for %s", base_url, exc_info=True)

    values = list(parser.links)
    values.extend(match.group(0) for match in _PDF_RE.finditer(html.unescape(text)))
    found: set[str] = set()
    for value in values:
        candidate = _absolute_candidate(base_url, value)
        if candidate and (_is_pdf(candidate) or _is_directory(candidate)):
            found.add(candidate)
    return found


def _h5ai_api_candidates(folder_url: str) -> Iterable[str]:
    parsed = urlsplit(folder_url)
    href = unquote(parsed.path)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    endpoints = [origin + "/_h5ai/public/index.php", folder_url]
    # Different H5AI builds request different field masks. Trying several is harmless.
    for endpoint in endpoints:
        for what in (1, 3, 7, 15, 31, 255):
            params = {
                "action": "get",
                "items": "1",
                "items.href": href,
                "items.what": str(what),
            }
            query = urlencode(params)
            yield endpoint + ("&" if "?" in endpoint else "?") + query


def _fetch_listing(folder_url: str, timeout: int) -> set[str]:
    # First ask H5AI's own JSON endpoint. This avoids needing JavaScript rendering.
    for api_url in _h5ai_api_candidates(folder_url):
        try:
            with _request(api_url, timeout, accept_json=True) as response:
                content_type = (response.headers.get("Content-Type") or "").lower()
                data = response.read(12 * 1024 * 1024)
            if "json" in content_type or data.lstrip().startswith((b"{", b"[")):
                payload = json.loads(data.decode("utf-8", "replace"))
                found = _extract_from_json(folder_url, payload)
                if found:
                    return found
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError):
            continue

    # Fallback for ordinary Apache indexes and H5AI static/fallback markup.
    with _request(folder_url, timeout) as response:
        final_url = response.geturl()
        if not _host_allowed(urlsplit(final_url).hostname):
            raise ValueError("الموقع أعاد التوجيه إلى نطاق غير مسموح")
        content_type = (response.headers.get("Content-Type") or "").lower()
        data = response.read(20 * 1024 * 1024)
    if "pdf" in content_type or data.startswith(b"%PDF"):
        return {final_url}
    text = data.decode("utf-8", "replace")
    if "json" in content_type or data.lstrip().startswith((b"{", b"[")):
        try:
            return _extract_from_json(folder_url, json.loads(text))
        except json.JSONDecodeError:
            pass
    return _extract_from_html(folder_url, text)


def discover_pdf_urls(
    source_urls: Iterable[str],
    *,
    timeout: int = 60,
    max_pdfs: int = 5000,
    max_depth: int = 3,
) -> list[str]:
    roots = validate_source_urls(source_urls)
    pdfs: set[str] = set()
    visited: set[str] = set()
    queue: deque[tuple[str, str, int]] = deque()

    for root in roots:
        if _is_pdf(root):
            pdfs.add(root)
        else:
            queue.append((root, root, 0))

    while queue:
        current, root, depth = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        links = _fetch_listing(current, timeout)
        for link in links:
            if not _within_root(link, root):
                continue
            if _is_pdf(link):
                pdfs.add(link)
                if len(pdfs) > max_pdfs:
                    raise ValueError(f"عدد ملفات PDF تجاوز الحد المسموح ({max_pdfs})")
            elif _is_directory(link) and depth < max_depth and link not in visited:
                queue.append((link, root, depth + 1))

    if not pdfs:
        raise ValueError(
            "لم أجد ملفات PDF في الرابط. افتح مجلد المحافظة ثم الفرع في مركز نتائجنا "
            "وانسخ رابط المجلد الظاهر في المتصفح."
        )
    return sorted(pdfs)


def download_pdf(
    url: str,
    destination: Path,
    *,
    timeout: int = 60,
    max_bytes: int = 50 * 1024 * 1024,
    retries: int = 3,
) -> None:
    if not _is_pdf(url) or not _host_allowed(urlsplit(url).hostname):
        raise ValueError("رابط PDF غير مسموح")
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        destination.unlink(missing_ok=True)
        try:
            with _request(url, timeout) as response, destination.open("wb") as output:
                final_url = response.geturl()
                if not _host_allowed(urlsplit(final_url).hostname):
                    raise ValueError("تم تحويل ملف PDF إلى نطاق غير مسموح")
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("حجم ملف PDF الواحد تجاوز 50MB")
                    output.write(chunk)
            with destination.open("rb") as check:
                if check.read(4) != b"%PDF":
                    raise ValueError("الرابط لم يرجع ملف PDF صالحًا")
            return
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(attempt * 1.5)

    raise RuntimeError(f"تعذر تنزيل الملف بعد {retries} محاولات: {last_error}")
