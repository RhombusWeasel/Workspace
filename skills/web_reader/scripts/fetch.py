"""Web Reader — fetch a webpage and extract its main content.

Called by the Workspace agent via the ``run_skill`` tool:

    run_skill(skill_name="web_reader", script="scripts/fetch.py", args=["https://example.com/article"])

Uses ``httpx`` for HTTP fetching and ``trafilatura`` for high-quality
article extraction (boilerplate removal, encoding detection, etc.).
"""

from __future__ import annotations

import argparse
import sys


def fetch(url: str, output_format: str = "markdown", include_links: bool = True, max_length: int = 50000) -> str:
	"""Fetch *url* and return extracted content as markdown or text."""
	try:
		import httpx
	except ImportError:
		return (
			"Missing dependency: httpx.\n"
			"Install with: pip install httpx"
		)

	try:
		import trafilatura
	except ImportError:
		return (
			"Missing dependency: trafilatura.\n"
			"Install with: pip install trafilatura"
		)

	if not url:
		return "Error: no URL provided. Usage: fetch.py <url> [--format markdown|text] [--no-links] [--max-length N]"

	# Validate URL scheme
	if not url.startswith(("http://", "https://")):
		return f"Error: invalid URL scheme — expected http:// or https://, got '{url}'"

	# Fetch the page
	try:
		response = httpx.get(
			url,
			follow_redirects=True,
			timeout=15,
			headers={
				"User-Agent": (
					"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
					"(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
				),
				"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
			},
		)
		response.raise_for_status()
	except httpx.TimeoutException:
		return f"Error: request timed out after 15 seconds — {url}"
	except httpx.HTTPStatusError as exc:
		status = exc.response.status_code
		if status == 403:
			return f"Error: access denied (403 Forbidden) — {url}"
		if status == 404:
			return f"Error: page not found (404) — {url}"
		if status == 429:
			return f"Error: rate limited (429) — try again later — {url}"
		return f"Error: HTTP {status} — {url}"
	except httpx.ConnectError:
		return f"Error: could not connect — {url}"
	except httpx.InvalidURL:
		return f"Error: invalid URL — {url}"
	except Exception as exc:
		return f"Error fetching URL: {exc}"

	content_type = response.headers.get("content-type", "")
	if "text/html" not in content_type and "application/xhtml" not in content_type:
		return (
			f"Error: not an HTML page (Content-Type: {content_type}) — {url}\n"
			f"Web Reader only supports HTML pages."
		)

	html = response.text
	if not html.strip():
		return f"Error: empty response — {url}"

	# Extract content
	trafilatura_format = "markdown" if output_format == "markdown" else "txt"
	try:
		content = trafilatura.extract(
			html,
			output_format=trafilatura_format,
			include_links=include_links,
			include_tables=True,
			url=url,
		)
	except Exception as exc:
		return f"Error extracting content: {exc}"

	if not content:
		return (
			f"Could not extract readable content from: {url}\n"
			f"The page may be primarily JavaScript-rendered, a forum, or have no main article content."
		)

	# Truncate if needed
	if len(content) > max_length:
		content = content[:max_length] + f"\n\n[Truncated at {max_length} chars — original length: {len(content)}]"

	# Prepend source metadata
	metadata = trafilatura.extract(html, output_format="json", url=url)
	meta_lines = []
	if metadata:
		try:
			import json
			meta = json.loads(metadata)
			if meta.get("title"):
				meta_lines.append(f"Title: {meta['title']}")
			if meta.get("author"):
				meta_lines.append(f"Author: {meta['author']}")
			if meta.get("date"):
				meta_lines.append(f"Date: {meta['date']}")
		except Exception:
			pass

	if meta_lines:
		header = "\n".join(meta_lines) + "\n\n"
		content = header + content

	return content


def main() -> None:
	parser = argparse.ArgumentParser(description="Read a webpage and extract its main content")
	parser.add_argument("url", help="URL to fetch")
	parser.add_argument(
		"--format",
		choices=["markdown", "text"],
		default="markdown",
		help="Output format (default: markdown)",
	)
	parser.add_argument(
		"--no-links",
		action="store_true",
		help="Strip hyperlinks from output",
	)
	parser.add_argument(
		"--max-length",
		type=int,
		default=50000,
		help="Max characters before truncation (default: 50000)",
	)
	parsed = parser.parse_args()

	result = fetch(
		parsed.url,
		output_format=parsed.format,
		include_links=not parsed.no_links,
		max_length=parsed.max_length,
	)
	print(result)


if __name__ == "__main__":
	main()