"""Multi-provider, intent-aware web search for LocalChat.

The local model never invents result URLs. Providers supply URLs; this module normalizes,
deduplicates, ranks and labels them. Product and video searches expand into domain-targeted
queries, especially for Persian/Iranian commerce and Aparat.
"""
import concurrent.futures
import ipaddress
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from . import search_providers

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 LocalChat/2.1"
)
TIMEOUT = 12
MAX_RESULTS = 8
MAX_QUERIES = 6
MAX_BYTES = 2 * 1024 * 1024
CACHE_TTL = 180
_CACHE = {}
_CACHE_LIMIT = 96

_PRODUCT = re.compile(
    r"(?:کارت\s*گرافیک|گرافیک|پردازنده|سی\s*پی\s*یو|مادربرد|رم|حافظه|اس\s*اس\s*دی|"
    r"مانیتور|لپ\s*تاپ|موس|کیبورد|پاور|کیس|محصول|product|gpu|cpu|"
    r"rtx\s*\d{3,4}|gtx\s*\d{3,4}|rx\s*\d{3,4})", re.I
)
_VIDEO = re.compile(r"(?:آپارات|ویدیو|ویدئو|کلیپ|فیلم|تریلر|aparat|youtube|video|watch)", re.I)
_PERSIAN = re.compile(r"[\u0600-\u06FF]")
_IRAN_STORES = (
    "digikala.com/product",
    "torob.com/p",
    "emalls.ir",
    "technolife.ir",
    "lioncomputer.com",
)
_VIDEO_SITES = ("aparat.com/v", "youtube.com/watch", "namasha.com", "tamasha.com")


class SearchError(RuntimeError):
    pass


def _normal(text):
    text = str(text or "").replace("\u200c", " ").replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
    return re.sub(r"\s+", " ", text).strip()


def classify(query):
    q = _normal(query)
    if _PRODUCT.search(q):
        return "product"
    if _VIDEO.search(q):
        return "video"
    return "web"


def _safe_url(value):
    try:
        raw = str(value or "")
        p = urlsplit(raw)
        host = (p.hostname or "").lower().rstrip(".")
        if p.scheme not in ("http", "https") or not host or len(raw) > 2048:
            return False
        if p.username is not None or p.password is not None:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False


def _normalize_item(item, provider, query, kind):
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or item.get("link") or "").strip()
    if not _safe_url(url):
        return None
    p = urlsplit(url)
    host = (p.hostname or "").lower().rstrip(".")
    title = " ".join(str(item.get("title") or "").split())[:300]
    snippet = " ".join(str(item.get("snippet") or item.get("description") or "").split())[:1000]
    if not title:
        title = host
    product_path = bool(re.search(r"/(?:product|products|p|item|dp|prd|کالا)(?:/|-|_|\?|$)", p.path, re.I))
    video_url = (
        ("aparat.com" in host and re.search(r"/(?:v|video)/", p.path, re.I))
        or ("youtube.com" in host and p.path == "/watch" and "v=" in p.query)
        or ("youtu.be" in host and len(p.path.strip("/")) >= 6)
    )
    title_match = _token_overlap(query, title + " " + snippet)
    score = 0.25 + min(title_match, 0.45)
    if kind == "product":
        if any(host == d or host.endswith("." + d) for d in (
            "digikala.com", "torob.com", "emalls.ir", "technolife.ir",
            "lioncomputer.com", "meghdadit.com", "shahrcomputer.com"
        )):
            score += 0.16
        if product_path:
            score += 0.22
        if not product_path and any(x in p.path.lower() for x in ("/search", "/category", "/brand")):
            score -= 0.08
    elif kind == "video":
        if video_url:
            score += 0.28
        if "aparat.com" in host:
            score += 0.18
    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "content": "",
        "source": provider,
        "provider": provider,
        "search_kind": kind,
        "match_score": round(min(1.0, score), 3),
        "link_type": "product" if kind == "product" and product_path else (
            "video" if kind == "video" and video_url else "webpage"
        ),
        "verified": False,
    }


def _token_overlap(query, text):
    def tokens(value):
        return {x.casefold() for x in re.findall(r"[a-zA-Z0-9\u0600-\u06FF]+", value) if len(x) > 1}
    a, b = tokens(query), tokens(text)
    if not a:
        return 0.0
    return len(a & b) / len(a)


def _dedupe(items):
    out, seen = [], set()
    for item in items:
        p = urlsplit(item["url"])
        key = (p.hostname.lower(), p.path.rstrip("/"), p.query)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def search_brave(query, api_key, limit=8):
    """Brave's independent index; API key is optional and stored only server-side."""
    if not api_key:
        raise search_providers.SearchProviderError("کلید Brave Search تنظیم نشده است.")
    params = {
        "q": query, "count": min(20, max(1, limit)),
        "safesearch": "moderate",
        "search_lang": "fa" if _PERSIAN.search(query) else "en",
        "country": "IR" if _PERSIAN.search(query) else "US",
    }
    request = Request(
        "https://api.search.brave.com/res/v1/web/search?" + urlencode(params),
        headers={"Accept": "application/json", "X-Subscription-Token": api_key, "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES)
    except HTTPError as exc:
        raise search_providers.SearchProviderError(
            "Brave Search خطا داد (HTTP %d)." % exc.code
        ) from None
    except (URLError, TimeoutError, OSError):
        raise search_providers.SearchProviderError("اتصال به Brave Search برقرار نشد.") from None
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        raise search_providers.SearchProviderError("پاسخ Brave Search معتبر نیست.") from None
    web = data.get("web") if isinstance(data, dict) else None
    rows = web.get("results", []) if isinstance(web, dict) else []
    return [
        {"title": row.get("title"), "url": row.get("url"), "snippet": row.get("description")}
        for row in rows if isinstance(row, dict)
    ]


def _provider_calls(query, config, ddg_search):
    calls = []
    engine = config.get("engine", "auto")
    if engine in ("auto", "google"):
        if config.get("serper_api_key"):
            calls.append(("Google / Serper", lambda q=query: search_providers.search_serper(q, config["serper_api_key"])))
        if config.get("google_api_key") and config.get("google_cx"):
            calls.append(("Google CSE", lambda q=query: search_providers.search_google_cse(
                q, config["google_api_key"], config["google_cx"])))
    if engine in ("auto", "google", "brave") and config.get("brave_api_key"):
        calls.append(("Brave Search", lambda q=query: search_brave(q, config["brave_api_key"])))
    calls.append(("DuckDuckGo", lambda q=query: ddg_search(q)))
    return calls


def _query_plan(query, kind):
    q = _normal(query)
    queries = [q]
    if kind == "product":
        # Exact product pages on known Iranian retailers, not generic store home pages.
        queries.extend(f"site:{domain} {q}" for domain in _IRAN_STORES)
    elif kind == "video":
        queries.extend(f"site:{domain} {q}" for domain in _VIDEO_SITES)
    return queries[:MAX_QUERIES]


def _run_query(calls):
    """Run available providers concurrently; failures are isolated and never abort a search."""
    results = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(calls) or 1)) as pool:
        future_map = {pool.submit(call): name for name, call in calls}
        for future in concurrent.futures.as_completed(future_map):
            name = future_map[future]
            try:
                rows = future.result() or []
                for row in rows:
                    results.append((name, row))
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:180]}")
    return results, errors


def search(query, config, ddg_search, page_fetch=None, max_results=MAX_RESULTS):
    """Search and return a stable API payload. Only provider-returned URLs are emitted."""
    query = _normal(query)[:500]
    if not query:
        raise SearchError("عبارت جست‌وجو خالی است.")
    kind = classify(query)
    cache_key = (query.casefold(), kind, config.get("engine", "auto"), str(config.get("serper_api_key") or "")[-4:], str(config.get("brave_api_key") or "")[-4:], str(config.get("google_api_key") or "")[-4:], str(config.get("google_cx") or ""))
    cached = _CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        payload = dict(cached[1])
        payload["results"] = [dict(x) for x in cached[1]["results"]]
        payload["cached"] = True
        return payload

    all_rows, errors = [], []
    query_plan = _query_plan(query, kind)
    # Base query fans out to all configured providers. Targeted site queries use the
    # best available provider first, then DuckDuckGo; this limits API cost and latency.
    base_calls = _provider_calls(query_plan[0], config, ddg_search)
    base_rows, base_errors = _run_query(base_calls)
    all_rows.extend(base_rows)
    errors.extend(base_errors)

    targeted_provider = next((name for name in ("Google / Serper", "Brave Search", "Google CSE", "DuckDuckGo")
                              if any(row_provider == name for row_provider, _ in base_rows)), "DuckDuckGo")
    if len(query_plan) > 1:
        targeted_calls = []
        for targeted_query in query_plan[1:]:
            def call_targeted(q=targeted_query, provider=targeted_provider):
                if provider == "Google / Serper":
                    return search_providers.search_serper(q, config["serper_api_key"])
                if provider == "Brave Search":
                    return search_brave(q, config["brave_api_key"])
                if provider == "Google CSE":
                    return search_providers.search_google_cse(q, config["google_api_key"], config["google_cx"])
                return ddg_search(q)
            targeted_calls.append((targeted_provider, call_targeted))
        targeted_rows, targeted_errors = _run_query(targeted_calls)
        all_rows.extend(targeted_rows)
        errors.extend(targeted_errors)

    normalized = []
    for provider, row in all_rows:
        item = _normalize_item(row, provider, query, kind)
        if item:
            normalized.append(item)
    results = _dedupe(normalized)
    results.sort(key=lambda item: item["match_score"], reverse=True)
    results = results[:max(1, min(12, int(max_results)))]

    # Fetch page text only for a few top results. The caller supplies the existing SSRF-safe
    # page reader; a failed fetch never causes an invented or rewritten URL.
    if callable(page_fetch) and results:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            future_map = {pool.submit(page_fetch, item["url"]): item for item in results[:3]}
            for future, item in future_map.items():
                try:
                    item["content"] = future.result() or ""
                    item["verified"] = bool(item["content"])
                except Exception:
                    item["content"] = ""
                    item["verified"] = False

    provider_names = list(dict.fromkeys(item["provider"] for item in results))
    payload = {
        "results": results,
        "engine": "multi" if len(provider_names) > 1 else (provider_names[0] if provider_names else "none"),
        "provider": ", ".join(provider_names) if provider_names else "none",
        "fallback": bool(provider_names and "DuckDuckGo" in provider_names and len(provider_names) == 1),
        "notice": (
            "پیوندها از نتایج واقعی موتور جست‌وجو آمده‌اند؛ لینک محصول فقط وقتی «صفحه محصول» برچسب دارد که مسیر آن شبیه صفحه محصول باشد. "
            "تأیید دسترسی یعنی متن صفحه دریافت شده، نه تضمین موجودی یا قیمت."
        ),
        "intent": {"kind": kind, "topic": query},
        "errors": errors[:4],
        "cached": False,
    }
    if errors:
        payload["fallback"] = True
        payload["notice"] += " خطاهای منابع: " + "؛ ".join(errors[:2])
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[cache_key] = (time.monotonic(), payload)
    return payload
