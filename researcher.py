"""
Multi-Platform Deep Researcher - Core Engine
Aggregates research from: Web Search, Wikipedia, arXiv, Open Library, CrossRef
"""

import asyncio
import aiohttp
import re
import time
import json as _json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
import urllib.parse

# Shared browser-like headers — required by Wikipedia & DuckDuckGo
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_wikipedia(session: aiohttp.ClientSession, query: str) -> dict:
    """Search Wikipedia using REST summary API (avoids mime-type errors)."""
    try:
        results = []
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query", "list": "search",
            "srsearch": query, "format": "json",
            "srlimit": 3, "utf8": 1,
        }
        async with session.get(search_url, params=params, headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=12)) as resp:
            text = await resp.text()
            data = _json.loads(text)
            hits = data.get("query", {}).get("search", [])

        for hit in hits[:3]:
            title = hit["title"]
            safe_title = urllib.parse.quote(title.replace(" ", "_"))
            summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_title}"
            try:
                async with session.get(summary_url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=10)) as r2:
                    s = await r2.json(content_type=None)
                    extract = re.sub(r"<[^>]+>", "", s.get("extract", hit.get("snippet", "")))[:900]
                    results.append({
                        "title":   s.get("title", title),
                        "snippet": extract,
                        "url":     s.get("content_urls", {}).get("desktop", {}).get(
                                       "page", f"https://en.wikipedia.org/wiki/{safe_title}"),
                    })
            except Exception:
                snippet = re.sub(r"<[^>]+>", "", hit.get("snippet", ""))
                results.append({
                    "title":   title,
                    "snippet": snippet,
                    "url":     f"https://en.wikipedia.org/wiki/{safe_title}",
                })

        return {"platform": "Wikipedia", "icon": "📚", "status": "success", "results": results}
    except Exception as e:
        return {"platform": "Wikipedia", "icon": "📚", "status": "error", "error": str(e), "results": []}


async def fetch_arxiv(session: aiohttp.ClientSession, query: str) -> dict:
    """Search arXiv for academic papers — with retry and fallback URL."""
    arxiv_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VortexResearcher/1.0)",
        "Accept": "application/atom+xml, application/xml, text/xml, */*",
    }

    def parse_xml(text):
        root    = ET.fromstring(text)
        ns      = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        results = []
        for entry in entries[:4]:
            title     = entry.find("atom:title", ns)
            summary   = entry.find("atom:summary", ns)
            link      = entry.find("atom:id", ns)
            published = entry.find("atom:published", ns)
            authors   = entry.findall("atom:author", ns)
            author_names = [a.find("atom:name", ns).text for a in authors[:3]
                            if a.find("atom:name", ns) is not None]
            results.append({
                "title":     title.text.strip() if title is not None else "N/A",
                "snippet":   (summary.text.strip()[:600] + "...") if summary is not None else "",
                "url":       link.text.strip() if link is not None else "",
                "published": published.text[:10] if published is not None else "",
                "authors":   ", ".join(author_names),
            })
        return results

    encoded = urllib.parse.quote(query)

    # Two URLs to try — export.arxiv.org is sometimes slow, arxiv.org/search is the fallback
    urls = [
        f"https://export.arxiv.org/api/query?search_query=all:{encoded}&start=0&max_results=5&sortBy=relevance",
        f"https://arxiv.org/search/?query={encoded}&searchtype=all&start=0",
    ]

    for attempt, url in enumerate(urls):
        try:
            timeout = aiohttp.ClientTimeout(total=5, connect=3)
            async with session.get(url, headers=arxiv_headers, timeout=timeout) as resp:
                if resp.status != 200:
                    continue
                text = await resp.text()

            # If it's XML (primary URL)
            if "<?xml" in text or "<feed" in text:
                results = parse_xml(text)
                if results:
                    return {"platform": "arXiv", "icon": "🎓", "status": "success", "results": results}

        except Exception:
            if attempt == len(urls) - 1:
                pass
            await asyncio.sleep(0.3)
            continue

    return {"platform": "arXiv", "icon": "🎓", "status": "error", "error": "arXiv is currently unreachable. Try again in a moment.", "results": []}


async def fetch_duckduckgo(session: aiohttp.ClientSession, query: str) -> dict:
    """Web search: DDG Instant Answer API with HTML scrape fallback."""
    results = []
    try:
        params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
        async with session.get("https://api.duckduckgo.com/", params=params, headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json(content_type=None)

        if not data or not isinstance(data, dict):
            data = {}

        if data.get("Abstract"):
            results.append({
                "title":   data.get("Heading", query),
                "snippet": data["Abstract"][:800],
                "url":     data.get("AbstractURL", ""),
                "source":  data.get("AbstractSource", "Web"),
            })
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title":   topic["Text"][:100],
                    "snippet": topic["Text"][:500],
                    "url":     topic.get("FirstURL", ""),
                    "source":  "DuckDuckGo",
                })

        if not results:
            encoded  = urllib.parse.quote_plus(query)
            html_url = f"https://html.duckduckgo.com/html/?q={encoded}"
            async with session.get(html_url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=14)) as resp2:
                html = await resp2.text()

            def clean(s):
                return re.sub(r"<[^>]+>", "", s).strip()

            titles   = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            raw_urls = re.findall(r'uddg=([^&"\'>\s]+)', html)

            for i in range(min(5, len(titles), len(snippets))):
                url = urllib.parse.unquote(raw_urls[i]) if i < len(raw_urls) else ""
                results.append({
                    "title":   clean(titles[i]),
                    "snippet": clean(snippets[i]),
                    "url":     url,
                    "source":  "DuckDuckGo",
                })

        return {"platform": "Web Search", "icon": "🌐", "status": "success", "results": results}
    except Exception as e:
        return {"platform": "Web Search", "icon": "🌐", "status": "error", "error": str(e), "results": []}


async def fetch_openlibrary(session: aiohttp.ClientSession, query: str) -> dict:
    """Search Open Library for books."""
    try:
        params = {"q": query, "limit": 5, "fields": "title,author_name,first_publish_year,subject,isbn"}
        async with session.get("https://openlibrary.org/search.json", params=params, headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=12)) as resp:
            data = await resp.json(content_type=None)

        results = []
        for doc in data.get("docs", [])[:4]:
            title   = doc.get("title", "Unknown")
            authors = doc.get("author_name", ["Unknown"])[:2]
            year    = doc.get("first_publish_year", "")
            subjs   = doc.get("subject", [])[:3]
            results.append({
                "title":   title,
                "snippet": f"By {', '.join(authors)} ({year}). Topics: {', '.join(subjs)}",
                "url":     f"https://openlibrary.org/search?q={urllib.parse.quote(title)}",
                "year":    str(year),
                "authors": ", ".join(authors),
            })

        return {"platform": "Open Library", "icon": "📖", "status": "success", "results": results}
    except Exception as e:
        return {"platform": "Open Library", "icon": "📖", "status": "error", "error": str(e), "results": []}


async def fetch_crossref(session: aiohttp.ClientSession, query: str) -> dict:
    """Search CrossRef for academic publications and DOIs."""
    try:
        params     = {"query": query, "rows": 5, "sort": "relevance"}
        cr_headers = {**HEADERS, "User-Agent": "Vortex/1.0 (research tool; mailto:research@vortex.app)"}
        async with session.get("https://api.crossref.org/works", params=params, headers=cr_headers,
                               timeout=aiohttp.ClientTimeout(total=14)) as resp:
            data = await resp.json(content_type=None)

        results = []
        for item in data.get("message", {}).get("items", [])[:4]:
            title_list = item.get("title", ["No Title"])
            title      = title_list[0] if title_list else "No Title"
            authors    = item.get("author", [])
            author_str = ", ".join([a.get("family", "") for a in authors[:3]])
            doi        = item.get("DOI", "")
            year       = item.get("published", {}).get("date-parts", [[""]])[0][0]
            publisher  = item.get("publisher", "")
            abstract   = re.sub(r"<[^>]+>", "", item.get("abstract", ""))[:500]
            results.append({
                "title":   title,
                "snippet": abstract or f"Published by {publisher} ({year})",
                "url":     f"https://doi.org/{doi}" if doi else "",
                "doi":     doi,
                "year":    str(year),
                "authors": author_str,
            })

        return {"platform": "CrossRef", "icon": "🔬", "status": "success", "results": results}
    except Exception as e:
        return {"platform": "CrossRef", "icon": "🔬", "status": "error", "error": str(e), "results": []}


# ─────────────────────────────────────────────
# MAIN RESEARCH ORCHESTRATOR
# ─────────────────────────────────────────────

async def deep_research(query: str, platforms: Optional[list] = None) -> dict:
    """Run research across all platforms concurrently."""
    all_platforms = {
        "wikipedia": fetch_wikipedia,
        "arxiv":     fetch_arxiv,
        "web":       fetch_duckduckgo,
        "books":     fetch_openlibrary,
        "crossref":  fetch_crossref,
    }

    selected   = platforms if platforms else list(all_platforms.keys())
    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = {
            name: asyncio.create_task(fn(session, query))
            for name, fn in all_platforms.items()
            if name in selected
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        platform_results = {}
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                platform_results[name] = {
                    "platform": name.title(),
                    "status":   "error",
                    "error":    str(result),
                    "results":  [],
                }
            else:
                platform_results[name] = result

    elapsed       = round(time.time() - start_time, 2)
    total_results = sum(len(v.get("results", [])) for v in platform_results.values())

    return {
        "query":           query,
        "timestamp":       datetime.now().isoformat(),
        "elapsed_seconds": elapsed,
        "total_results":   total_results,
        "platforms":       platform_results,
    }