"""Security helpers: URL validation (SSRF), upload validation, sanitisation."""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from core.exceptions import FileTooLargeError, UnsafeURLError, UnsupportedFileTypeError

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str, *, resolve_dns: bool = True, require_resolution: bool = True) -> str:
    """Validate an outbound URL and reject anything that could hit internal hosts.

    ``resolve_dns=False`` performs only syntactic checks (used in tests and for
    URLs that will be displayed rather than fetched).
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("Empty URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError(f"Unsupported URL scheme: {parsed.scheme or 'none'}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if host in BLOCKED_HOSTNAMES or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURLError("Refusing to access a local host")
    if _is_private_ip(host):
        raise UnsafeURLError("Refusing to access a private IP address")
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as exc:
            if require_resolution:
                raise UnsafeURLError(f"Host could not be resolved: {host}") from exc
            return url.strip()
        for info in infos:
            addr = info[4][0]
            if _is_private_ip(addr):
                raise UnsafeURLError("Host resolves to a private address")
    return url.strip()


def is_safe_url(url: str, *, resolve_dns: bool = False) -> bool:
    try:
        validate_url(url, resolve_dns=resolve_dns)
        return True
    except UnsafeURLError:
        return False


def validate_upload(filename: str, size_bytes: int, max_mb: int = 10) -> str:
    """Return a lower-cased extension or raise a domain error."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or 'unknown'}'. Upload a PDF or DOCX file.",
            details={"allowed": sorted(ALLOWED_EXTENSIONS)},
        )
    if size_bytes and size_bytes > max_mb * 1024 * 1024:
        raise FileTooLargeError(f"File is too large (limit {max_mb} MB).")
    if size_bytes == 0:
        raise UnsupportedFileTypeError("The uploaded file is empty.")
    return ext


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|iframe|object|embed)[^>]*>.*?</\1>", re.I | re.S)


def sanitize_html(html: str) -> str:
    """Strip markup and executable content from untrusted HTML fragments."""
    if not html:
        return ""
    cleaned = _SCRIPT_RE.sub(" ", html)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = (
        cleaned.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    )
    return re.sub(r"[ \t\r\f\v]+", " ", cleaned).strip()


def sanitize_plain_text(text: str, max_chars: int = 120_000) -> str:
    """Normalise untrusted plain text; strips control characters."""
    if not text:
        return ""
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text[:max_chars].strip()


def safe_temp_name(filename: str, suffix: str = "") -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "upload").stem)[:60] or "upload"
    return f"{stem}{suffix or Path(filename).suffix}"


def redact_secret(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)
