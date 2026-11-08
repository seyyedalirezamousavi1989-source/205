"""Regression tests for the multi-provider search engine."""
import pytest

from local_chat import search_engine


def test_search_intent_and_domain_query_plans():
    product = "قیمت کارت گرافیک RTX 3060"
    video = "ویدیو آموزش پایتون در آپارات پیدا کن"
    assert search_engine.classify(product) == "product"
    assert search_engine.classify(video) == "video"
    assert any("digikala.com/product" in q for q in search_engine._query_plan(product, "product"))
    assert any("torob.com/p" in q for q in search_engine._query_plan(product, "product"))
    assert any("aparat.com/v" in q for q in search_engine._query_plan(video, "video"))


def test_normalizer_only_accepts_real_http_links_and_marks_product_pages():
    assert search_engine._normalize_item({"title": "GPU", "url": "javascript:alert(1)"}, "fake", "GPU", "product") is None
    assert search_engine._normalize_item({"title": "GPU", "url": "https://user:pass@example.com/x"}, "fake", "GPU", "product") is None
    item = search_engine._normalize_item(
        {"title": "کارت گرافیک RTX 3060", "url": "https://www.digikala.com/product/dkp-123/"},
        "DuckDuckGo", "کارت گرافیک RTX 3060", "product")
    assert item["link_type"] == "product"
    assert item["verified"] is False


def test_product_search_uses_targeted_queries_and_never_invents_urls(monkeypatch):
    search_engine._CACHE.clear()
    seen = []
    actual_url = "https://www.digikala.com/product/dkp-123/"
    def ddg(query):
        seen.append(query)
        if "site:digikala.com/product" in query:
            return [{"title": "کارت گرافیک RTX 3060", "url": actual_url, "snippet": "صفحه محصول"}]
        return []
    result = search_engine.search(
        "قیمت کارت گرافیک RTX 3060", {"engine": "auto"}, ddg,
        page_fetch=lambda url: "مشخصات محصول", max_results=8)
    assert len(seen) >= 2
    assert any("site:digikala.com/product" in q for q in seen)
    assert [item["url"] for item in result["results"]] == [actual_url]
    assert result["results"][0]["link_type"] == "product"
    assert result["results"][0]["verified"] is True


def test_video_search_expands_to_aparat_and_preserves_provider_url():
    search_engine._CACHE.clear()
    seen = []
    actual_url = "https://www.aparat.com/v/abc123"
    def ddg(query):
        seen.append(query)
        if "site:aparat.com/v" in query:
            return [{"title": "آموزش پایتون", "url": actual_url, "snippet": "ویدیو در آپارات"}]
        return []
    result = search_engine.search("ویدیو آموزش پایتون در آپارات پیدا کن", {"engine": "auto"}, ddg)
    assert any("site:aparat.com/v" in q for q in seen)
    assert result["results"][0]["url"] == actual_url
    assert result["results"][0]["link_type"] == "video"


def test_empty_search_does_not_call_provider():
    with pytest.raises(search_engine.SearchError):
        search_engine.search("   ", {"engine": "auto"}, lambda _q: pytest.fail("must not search"))
