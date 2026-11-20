import pytest

from core.exceptions import FileTooLargeError, UnsupportedFileTypeError, UnsafeURLError
from core.security import sanitize_html, validate_upload, validate_url
from core.text import canonical_skill, coverage, keyword_set, similarity, slugify


@pytest.mark.parametrize("url", [
    "http://localhost/admin",
    "http://127.0.0.1/",
    "http://192.168.1.10/jobs",
    "http://10.0.0.5/",
    "file:///etc/passwd",
    "http://metadata.google.internal/",
    "http://printer.local/",
])
def test_private_and_local_urls_are_blocked(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_public_urls_are_allowed():
    assert validate_url("https://boards.greenhouse.io/acme") == "https://boards.greenhouse.io/acme"


def test_upload_validation():
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("malware.exe", 10)
    assert validate_upload("CV.PDF", 100) == ".pdf"
    with pytest.raises(FileTooLargeError):
        validate_upload("cv.pdf", 11 * 1024 * 1024, max_mb=10)


def test_sanitize_html_removes_scripts_and_handlers():
    dirty = '<p onclick="steal()">Hello</p><script>alert(1)</script><img src=x onerror="x">'
    clean = sanitize_html(dirty)
    assert "script" not in clean.lower()
    assert "onclick" not in clean.lower()
    assert "onerror" not in clean.lower()
    assert "Hello" in clean


def test_text_helpers():
    assert canonical_skill("Postgres") == canonical_skill("PostgreSQL")
    assert similarity("Backend Engineer", "Backend Engineer") == 1.0
    assert slugify("Ada Lovelace — CV") == "ada-lovelace-cv"
    matched, missing = coverage(["Python", "Go"], "I use Python daily")
    assert matched == ["Python"]
    assert missing == ["Go"]
    assert "python" in keyword_set("Python and FastAPI")
