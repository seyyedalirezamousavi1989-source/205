"""Translate natural-language search constraints into a deterministic search plan.

The parser is intentionally lightweight: it does not call the local LLM and never invents
URLs. The user's natural-language request remains the source of truth.
"""
import re
from urllib.parse import urlsplit

_PERSIAN = re.compile(r"[\\u0600-\\u06FF]")
_DOMAIN = re.compile(r"(?i)(?:https?://)?(?:[a-z0-9-]+\\.)+[a-z]{2,}(?:/[\\w./%-]*)?")
_ALIASES = {
    "دیجی کالا": "digikala.com",
    "دیجی‌کالا": "digikala.com",
    "ترب": "torob.com",
    "ایمالز": "emalls.ir",
    "تکنولایف": "technolife.ir",
    "لیون کامپیوتر": "lioncomputer.com",
    "آپارات": "aparat.com",
    "یوتیوب": "youtube.com",
    "ذره بین": "zarebin.ir",
    "ذره‌بین": "zarebin.ir",
    "گردو": "gerdoo.me",
}
_FILE_EXTENSIONS = {
    "pdf": "pdf", "پی دی اف": "pdf", "پی‌دی‌اف": "pdf",
    "docx": "docx", "word": "docx", "ورد": "docx",
    "xlsx": "xlsx", "excel": "xlsx", "اکسل": "xlsx",
    "pptx": "pptx", "powerpoint": "pptx",
    "zip": "zip", "فایل": None, "فایل ها": None, "فایل‌ها": None,
}


def _norm(value):
    value = str(value or "").replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"\\s+", " ", value).strip()


def _domain(value):
    value = str(value or "").strip().lower().rstrip(".,؛،)")
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    host = (urlsplit(value).hostname or "").lower().rstrip(".")
    if not host or "." not in host or len(host) > 253:
        return ""
    if not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host:
        return ""
    return host


def _extract_domains(text):
    found = []
    for raw in _DOMAIN.findall(text):
        host = _domain(raw)
        if host and host not in found:
            found.append(host)
    lowered = _norm(text).casefold()
    for alias, host in _ALIASES.items():
        if alias.casefold() in lowered and host not in found:
            found.append(host)
    return found


def parse_search_request(raw_query, supplied=None):
    """Return {query, constraints, strict_domains, strategy}; accepts optional model plan."""
    original = _norm(raw_query)[:1000]
    supplied = supplied if isinstance(supplied, dict) else {}
    lower = original.casefold()

    allowed = supplied.get("allowed_domains")
    excluded = supplied.get("excluded_domains")
    allowed = [_domain(x) for x in allowed] if isinstance(allowed, list) else []
    excluded = [_domain(x) for x in excluded] if isinstance(excluded, list) else []

    only_site = bool(re.search(r"(?:فقط|صرفا|صرفاً)\\s*(?:در\\s*)?(?:سایت|دامنه|وبسایت|وب\\s*سایت)|only\\s+(?:the\\s+)?(?:site|domain|website)", lower))
    exclude_site = bool(re.search(r"(?:به\\s*جز|به\\s*غیر\\s*از|غیر\\s*از|به\\s*استثنای)|(?:except|excluding|exclude)", lower))
    mentioned_domains = _extract_domains(original)
    if only_site and not allowed and mentioned_domains:
        allowed = mentioned_domains
    if exclude_site and not excluded and mentioned_domains:
        excluded = mentioned_domains

    fa_only = bool(re.search(
        r"(?:فقط|صرفا|صرفاً)\\s*(?:سایت(?:های|\\s*های)?|منابع?)\\s*فارسی|"
        r"(?:سایت(?:های|\\s*های)?|منابع?)\\s*فارسی\\s*(?:فقط|باشه|باشد)|"
        r"only\\s+persian\\s+(?:sites|sources)", lower))
    iran_only = bool(re.search(
        r"(?:فقط|صرفا|صرفاً)\\s*(?:سایت(?:های|\\s*های)?|فروشگاه(?:های|\\s*های)?|منابع?)\\s*ایرانی|"
        r"(?:سایت(?:های|\\s*های)?|فروشگاه(?:های|\\s*های)?|منابع?)\\s*ایرانی\\s*(?:فقط|باشه|باشد)|"
        r"iranian\\s+(?:sites|stores|sources)\\s+only", lower))

    content_types = supplied.get("content_types")
    if not isinstance(content_types, list):
        content_types = []
    else:
        content_types = [str(x).lower() for x in content_types if str(x).lower() in {"pdf", "docx", "xlsx", "pptx", "zip"}]
    for term, kind in _FILE_EXTENSIONS.items():
        if term in lower:
            if kind and kind not in content_types:
                content_types.append(kind)
    if re.search(r"\\b(?:filetype:)?(?:pdf|docx|xlsx|pptx|zip)\\b", lower):
        for ext in ("pdf", "docx", "xlsx", "pptx", "zip"):
            if re.search(r"\\b" + ext + r"\\b", lower) and ext not in content_types:
                content_types.append(ext)

    # Remove only recognized constraint clauses; preserve the subject and quoted phrases.
    query = original
    patterns = [
        r"(?:فقط|صرفا|صرفاً)\\s*(?:سایت(?:های|\\s*های)?|منابع?)\\s*(?:فارسی|ایرانی)",
        r"(?:فقط|صرفا|صرفاً)\\s*(?:فروشگاه(?:های|\\s*های)?|سایت(?:های|\\s*های)?|منابع?)\\s*ایرانی",
        r"(?:فقط|صرفا|صرفاً)\\s*(?:در\\s*)?(?:سایت|دامنه|وبسایت|وب\\s*سایت)\\s+[\\w.-]+",
        r"(?:به\\s*جز|به\\s*غیر\\s*از|غیر\\s*از|به\\s*استثنای)\\s+(?:سایت\\s+)?[\\w.-]+",
        r"only\\s+persian\\s+(?:sites|sources)",
        r"iranian\\s+(?:sites|stores|sources)\\s+only",
        r"only\\s+(?:the\\s+)?(?:site|domain|website)\\s+[\\w.-]+",
        r"(?:except|excluding|exclude)\\s+[\\w.-]+",
    ]
    for pattern in patterns:
        query = re.sub(pattern, " ", query, flags=re.I)
    for raw in _DOMAIN.findall(original):
        query = query.replace(raw, " ")
    for alias in _ALIASES:
        query = re.sub(re.escape(alias), " ", query, flags=re.I)
    query = re.sub(r"[،,;؛]+", " ", query)
    query = re.sub(r"\\s+", " ", query).strip(" -:")
    if len(query) < 2:
        query = original

    if not allowed and isinstance(supplied.get("allowed_domains"), list):
        allowed = [_domain(x) for x in supplied["allowed_domains"]]
    allowed = list(dict.fromkeys(x for x in allowed if x))
    excluded = list(dict.fromkeys(x for x in excluded if x and x not in allowed))

    return {
        "query": query[:500],
        "constraints": {
            "language": "fa" if fa_only else supplied.get("language"),
            "region": "IR" if iran_only else supplied.get("region"),
            "allowed_domains": allowed,
            "excluded_domains": excluded,
            "content_types": content_types,
        },
        "strict_domains": bool(only_site or supplied.get("strict_domains")),
        "strategy": str(supplied.get("strategy") or "auto"),
    }


def host_allowed(host, constraints):
    """Apply explicit domain allow/deny constraints without fuzzy substring matching."""
    host = str(host or "").lower().rstrip(".")
    allowed = constraints.get("allowed_domains") or []
    excluded = constraints.get("excluded_domains") or []
    if allowed and not any(host == d or host.endswith("." + d) for d in allowed):
        return False
    if any(host == d or host.endswith("." + d) for d in excluded):
        return False
    return True


def result_matches_constraints(item, constraints):
    host = _domain(item.get("url", ""))
    if not host_allowed(host, constraints):
        return False
    language = constraints.get("language")
    if language == "fa":
        sample = " ".join((item.get("title") or "", item.get("snippet") or "", item.get("content") or ""))
        letters = [c for c in sample if c.isalpha()]
        if letters and sum(1 for c in letters if "\\u0600" <= c <= "\\u06ff") / len(letters) < 0.12:
            return False
    region = constraints.get("region")
    if region == "IR":
        iranian_hosts = ("digikala.com", "torob.com", "emalls.ir", "technolife.ir", "lioncomputer.com",
                         "meghdadit.com", "shahrcomputer.com", "zarebin.ir", "gerdoo.me")
        if not (host.endswith(".ir") or any(host == d or host.endswith("." + d) for d in iranian_hosts)):
            return False
    types = constraints.get("content_types") or []
    if types:
        path = urlsplit(item.get("url", "")).path.lower()
        if not any(path.endswith("." + ext) or ("filetype:" + ext) in (item.get("query") or "") for ext in types):
            # Search snippets sometimes link to landing pages rather than files; keep them if the provider labels the type.
            if str(item.get("mime_type") or "").lower() not in {"application/pdf", "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "application/zip"}:
                return False
    return True
