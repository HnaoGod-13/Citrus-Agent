"""Small dependency-free web search adapter used by project reports."""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
import re
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request
from typing import Any


def _decode_response(response) -> str:
    raw = response.read()
    charset = response.headers.get_content_charset() if getattr(response, "headers", None) else None
    candidates = [charset, "utf-8", "gb18030"]
    for encoding in candidates:
        if not encoding:
            continue
        try:
            text = raw.decode(encoding)
            if "�" not in text:
                return text
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._link = ""
        self._title = ""
        self._snippet = ""
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        classes = attrs_d.get("class", "") or ""
        if tag == "a" and "result__a" in classes:
            self._link = attrs_d.get("href", "") or ""
            self._title = ""
            self._in_title = True
        elif tag in {"a", "div"} and ("result__snippet" in classes or "result-snippet" in classes):
            self._snippet = ""
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        if self._in_snippet and tag in {"a", "div"}:
            self._in_snippet = False
            if self._link and self._title:
                self.items.append({"title": self._title.strip(), "url": self._link, "snippet": self._snippet.strip()})

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title += data
        elif self._in_snippet:
            self._snippet += data


def _ddg_search(query: str, limit: int = 6) -> list[dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "kl": "cn-zh"})
    request = urllib.request.Request(url, headers={"User-Agent": "CitrusAgent/1.0 report research"})
    with urllib.request.urlopen(request, timeout=18) as response:
        html = _decode_response(response)
    parser = _DuckDuckGoParser()
    parser.feed(html)
    found: list[dict[str, Any]] = []
    for item in parser.items[:limit]:
        link = urllib.parse.unquote(item["url"])
        # DuckDuckGo sometimes wraps the destination in a redirect parameter.
        parsed = urllib.parse.urlparse(link)
        query_params = urllib.parse.parse_qs(parsed.query)
        link = query_params.get("uddg", [link])[0]
        found.append({
            **item,
            "url": link,
            "query": query,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_type": "internet",
        })
    return found


def _tavily_search(query: str, limit: int = 6) -> list[dict[str, Any]]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        return []
    payload = json.dumps({"api_key": key, "query": query, "search_depth": "advanced", "max_results": limit}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("https://api.tavily.com/search", data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=25) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [{
        "title": str(item.get("title") or ""), "url": str(item.get("url") or ""),
        "snippet": str(item.get("content") or ""), "query": query,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source_type": "internet",
    } for item in data.get("results", []) if isinstance(item, dict) and item.get("url")]


def _bing_rss_search(query: str, limit: int = 6) -> list[dict[str, Any]]:
    url = "https://www.bing.com/search?format=rss&" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "CitrusAgent/1.0 report research"})
    with urllib.request.urlopen(request, timeout=18) as response:
        root = ET.fromstring(_decode_response(response))
    found = []
    for item in root.findall(".//item")[:limit]:
        text = lambda name: (item.findtext(name) or "").strip()
        link = text("link")
        if link:
            found.append({
                "title": text("title"), "url": link, "snippet": text("description"),
                "query": query, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_type": "internet",
            })
    return found


def search_web(queries: list[str], limit_per_query: int = 5) -> dict[str, Any]:
    """Search public web sources and return evidence plus errors for auditability."""
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for query in queries[:6]:
        results: list[dict[str, Any]] = []
        providers = []
        if os.getenv("TAVILY_API_KEY", "").strip():
            providers.append(("Tavily", _tavily_search))
        providers.extend((("DuckDuckGo", _ddg_search), ("Bing RSS", _bing_rss_search)))
        for provider_name, provider in providers:
            try:
                results = provider(query, limit_per_query)
            except Exception as exc:  # try the next public search provider
                errors.append(f"{query} / {provider_name}: {type(exc).__name__}")
                continue
            if results:
                break
        for item in results:
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            evidence.append(item)
    return {"evidence": evidence[:24], "errors": errors, "queries": queries[:6], "status": "completed" if evidence else "unavailable"}


__all__ = ["search_web"]
