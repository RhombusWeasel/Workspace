"""Brave Search — web search via the Brave Search API.

Called by the Workspace agent via the `run_skill` tool:

    run_skill(skill_name="brave_search", script="scripts/search.py", args=["Python async tutorial"])

The script expects a ``context`` global (provided by run_skill) with
access to ``context.vault``.  The API key must be stored in the vault
as a credential named ``brave_search`` (password field = API key).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def _get_api_key() -> str | None:
    """Retrieve the Brave Search API key from the vault."""
    try:
        vault = context.vault  # type: ignore[name-defined]  # noqa: F821
    except NameError:
        return None

    if vault is None or vault.is_locked():
        return None

    cred = vault.get_credential("brave_search")
    if cred is None:
        return None

    # cred is (username, password) — password holds the API key
    return cred[1]


def search(query: str, count: int = 10, country: str | None = None) -> str:
    """Perform a web search and return formatted plaintext results."""
    api_key = _get_api_key()
    if not api_key:
        return (
            "Brave Search API key not configured.\n"
            "Store it in the vault as credential 'brave_search' "
            "(password field = API key)."
        )

    # Build URL with proper encoding
    params: dict[str, str] = {
        "q": query,
        "count": str(count),
    }
    if country:
        params["country"] = country

    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return "Brave Search API error: invalid API key (401 Unauthorized)."
        if exc.code == 429:
            return "Brave Search API error: rate limit exceeded (429). Try again later."
        return f"Brave Search API error: HTTP {exc.code} — {exc.reason}"
    except urllib.error.URLError as exc:
        return f"Brave Search API error: {exc.reason}"
    except Exception as exc:
        return f"Brave Search API error: {exc}"

    # Parse results
    web_results = data.get("web", {}).get("results", [])
    if not web_results:
        return f"No results found for '{query}'."

    lines: list[str] = []
    for i, result in enumerate(web_results, 1):
        title = result.get("title", "Untitled")
        url_link = result.get("url", "")
        snippet = result.get("description", "")
        lines.append(f"{i}. {title}")
        lines.append(f"   URL: {url_link}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the web via Brave Search")
    parser.add_argument("query", nargs="+", help="Search query terms")
    parser.add_argument("--count", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--country", type=str, default=None, help="Country code (e.g. us, uk)")
    parsed = parser.parse_args()

    query_str = " ".join(parsed.query)
    print(search(query_str, count=parsed.count, country=parsed.country))


if __name__ == "__main__":
    main()