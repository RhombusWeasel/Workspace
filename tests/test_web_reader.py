"""Tests for the web_reader skill — scripts/fetch.py

All HTTP calls and trafilatura are mocked; no real network access or
installed dependencies required.
"""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
import httpx


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

SAMPLE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Test Article</title></head>
<body>
<nav>Home | About | Contact</nav>
<article>
<h1>Test Article Title</h1>
<p>By Jane Doe on 2024-01-15</p>
<p>This is the main content of the article. It has <a href="https://example.com">a link</a> inside.</p>
<p>Another paragraph with more content to make this a substantive article.</p>
</article>
<footer>Copyright 2024 | Privacy Policy</footer>
</body>
</html>
"""

SAMPLE_HTML_NO_ARTICLE = """\
<!DOCTYPE html>
<html>
<head><title>No Content</title></head>
<body>
<nav>Home | About</nav>
<div>Some sidebar stuff</div>
<footer>Copyright 2024</footer>
</body>
</html>
"""

SAMPLE_JSON_META = json.dumps({
	"title": "Test Article Title",
	"author": "Jane Doe",
	"date": "2024-01-15",
	"url": "https://example.com/article",
})


def _make_response(
	text: str = SAMPLE_HTML,
	status_code: int = 200,
	content_type: str = "text/html; charset=utf-8",
) -> MagicMock:
	"""Create a mock httpx.Response."""
	resp = MagicMock()
	resp.status_code = status_code
	resp.text = text
	resp.headers = {"content-type": content_type}
	resp.raise_for_status = MagicMock()
	if status_code >= 400:
		req = MagicMock()
		resp.raise_for_status.side_effect = httpx.HTTPStatusError(
			message=f"HTTP {status_code}",
			request=req,
			response=resp,
		)
	return resp


def _mock_trafilatura_extract(html, output_format="markdown", include_links=True, include_tables=True, url=None):
	"""Mock trafilatura.extract that returns sensible output."""
	if output_format == "json":
		return SAMPLE_JSON_META
	if not html or "Some sidebar stuff" in html:
		return None
	if output_format == "txt":
		return "Test Article Title\nThis is the main content of the article. a link inside.\nAnother paragraph with more content."
	# markdown
	if include_links:
		return "Test Article Title\nThis is the main content of the article. [a link](https://example.com) inside.\nAnother paragraph with more content."
	return "Test Article Title\nThis is the main content of the article. a link inside.\nAnother paragraph with more content."


# We need to mock the modules at import time since fetch.py imports them
# inside the function body. We inject fake modules into sys.modules
# before importing the module under test.

def _install_fake_trafilatura():
	"""Install a fake trafilatura module in sys.modules."""
	fake_mod = types.ModuleType("trafilatura")
	fake_mod.extract = _mock_trafilatura_extract
	sys.modules["trafilatura"] = fake_mod
	return fake_mod


def _remove_fake_trafilatura():
	"""Remove the fake trafilatura module from sys.modules."""
	sys.modules.pop("trafilatura", None)


@pytest.fixture(autouse=True)
def _ensure_deps():
	"""Ensure both httpx and trafilatura appear installed for every test."""
	_install_fake_trafilatura()
	yield
	_remove_fake_trafilatura()
	# Clear cached import of the module under test
	sys.modules.pop("skills.web_reader.scripts.fetch", None)


# ---------------------------------------------------------------------------
# Import helper — always re-import to pick up fresh sys.modules state
# ---------------------------------------------------------------------------

def _import_fetch():
	"""Import fetch function fresh so it uses current sys.modules state."""
	# Force re-import
	if "skills.web_reader.scripts.fetch" in sys.modules:
		del sys.modules["skills.web_reader.scripts.fetch"]
	from skills.web_reader.scripts.fetch import fetch
	return fetch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFetchBasic:
	"""Basic fetch and extract tests."""

	@patch("httpx.get")
	def test_fetch_markdown_default(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response()
		result = fetch("https://example.com/article")
		assert "Test Article Title" in result
		assert "[a link](https://example.com)" in result
		mock_get.assert_called_once()

	@patch("httpx.get")
	def test_fetch_text_format(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response()
		result = fetch("https://example.com/article", output_format="text")
		assert "Test Article Title" in result
		assert "[a link]" not in result
		mock_get.assert_called_once()

	@patch("httpx.get")
	def test_fetch_no_links(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response()
		result = fetch("https://example.com/article", include_links=False)
		assert "Test Article Title" in result
		assert "](https://example.com)" not in result

	@patch("httpx.get")
	def test_fetch_includes_metadata_header(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response()
		result = fetch("https://example.com/article")
		assert "Title: Test Article Title" in result
		assert "Author: Jane Doe" in result
		assert "Date: 2024-01-15" in result


class TestFetchErrors:
	"""Error handling tests."""

	def test_no_url(self):
		fetch = _import_fetch()
		result = fetch("")
		assert "Error" in result
		assert "no URL provided" in result

	def test_invalid_scheme(self):
		fetch = _import_fetch()
		result = fetch("ftp://example.com/file")
		assert "Error" in result
		assert "invalid URL scheme" in result

	@patch("httpx.get")
	def test_timeout(self, mock_get):
		fetch = _import_fetch()
		mock_get.side_effect = httpx.TimeoutException("timed out")
		result = fetch("https://slow.example.com")
		assert "timed out" in result
		assert "Error" in result

	@patch("httpx.get")
	def test_404(self, mock_get):
		fetch = _import_fetch()
		resp = _make_response(status_code=404)
		mock_get.return_value = resp
		result = fetch("https://example.com/missing")
		assert "404" in result
		assert "Error" in result

	@patch("httpx.get")
	def test_403(self, mock_get):
		fetch = _import_fetch()
		resp = _make_response(status_code=403)
		mock_get.return_value = resp
		result = fetch("https://example.com/forbidden")
		assert "403" in result

	@patch("httpx.get")
	def test_connect_error(self, mock_get):
		fetch = _import_fetch()
		mock_get.side_effect = httpx.ConnectError("connection refused")
		result = fetch("https://unreachable.example.com")
		assert "could not connect" in result

	@patch("httpx.get")
	def test_non_html_content_type(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response(content_type="application/pdf")
		result = fetch("https://example.com/doc.pdf")
		assert "not an HTML page" in result
		assert "application/pdf" in result

	@patch("httpx.get")
	def test_no_extractable_content(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response(text=SAMPLE_HTML_NO_ARTICLE)
		result = fetch("https://example.com/empty")
		assert "Could not extract readable content" in result

	@patch("httpx.get")
	def test_empty_response(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response(text="")
		result = fetch("https://example.com/blank")
		assert "empty response" in result


class TestTruncation:
	"""Content truncation tests."""

	@patch("httpx.get")
	def test_truncation_applied(self, mock_get):
		fetch = _import_fetch()
		long_content = "A" * 60000
		# Override fake trafilatura to return long content
		sys.modules["trafilatura"].extract = lambda *a, **kw: (
			SAMPLE_JSON_META if kw.get("output_format") == "json" else long_content
		)
		mock_get.return_value = _make_response()
		result = fetch("https://example.com/long", max_length=50000)
		assert "[Truncated at 50000 chars" in result
		assert "original length: 60000" in result

	@patch("httpx.get")
	def test_no_truncation_when_under_limit(self, mock_get):
		fetch = _import_fetch()
		mock_get.return_value = _make_response()
		result = fetch("https://example.com/article", max_length=50000)
		assert "Truncated" not in result


class TestMissingDeps:
	"""Graceful failure when dependencies are not installed."""

	def test_missing_trafilatura(self):
		# Remove fake module to simulate missing dep
		_remove_fake_trafilatura()
		# Also clear cached import
		sys.modules.pop("skills.web_reader.scripts.fetch", None)
		fetch = _import_fetch()
		result = fetch("https://example.com/article")
		assert "trafilatura" in result
		assert "pip install" in result

	@patch.dict(sys.modules, {"httpx": None})
	def test_missing_httpx(self):
		# Clear cached import so it re-imports with httpx=None
		sys.modules.pop("skills.web_reader.scripts.fetch", None)
		fetch = _import_fetch()
		result = fetch("https://example.com/article")
		assert "httpx" in result
		assert "pip install" in result