"""Natural-language search constraint tests."""
from local_chat import search_plan


def test_persian_language_constraint_is_not_misread_as_single_site():
    plan = search_plan.parse_search_request("قیمت RTX 5070 فقط سایت‌های فارسی")
    assert plan["constraints"]["language"] == "fa"
    assert plan["strict_domains"] is False
    assert plan["query"] == "قیمت RTX 5070"


def test_named_iranian_site_becomes_strict_domain_scope():
    plan = search_plan.parse_search_request("قیمت RTX 5070 فقط سایت دیجی‌کالا")
    assert plan["constraints"]["allowed_domains"] == ["digikala.com"]
    assert plan["strict_domains"] is True
    assert plan["query"] == "قیمت RTX 5070"


def test_explicit_domain_allow_and_deny_lists():
    allowed = search_plan.parse_search_request("benchmark RTX 5070 فقط سایت example.com")
    assert allowed["constraints"]["allowed_domains"] == ["example.com"]
    assert search_plan.host_allowed("shop.example.com", allowed["constraints"])
    assert not search_plan.host_allowed("other.com", allowed["constraints"])

    excluded = search_plan.parse_search_request("benchmark RTX 5070 به جز example.com")
    assert not search_plan.host_allowed("shop.example.com", excluded["constraints"])
    assert search_plan.host_allowed("other.com", excluded["constraints"])


def test_file_type_is_extracted_without_llm():
    plan = search_plan.parse_search_request("مقاله یادگیری ماشین فایل PDF")
    assert "pdf" in plan["constraints"]["content_types"]
    assert "filetype:pdf" in plan["query"] or plan["query"] == "مقاله یادگیری ماشین فایل PDF"


def test_model_supplied_search_plan_is_sanitized():
    plan = search_plan.parse_search_request(
        "بحث درباره مدل‌ها",
        {"allowed_domains": ["https://example.com/path", "javascript:alert(1)"],
         "language": "fa", "content_types": ["pdf", "exe"]},
    )
    assert plan["constraints"]["allowed_domains"] == ["example.com"]
    assert plan["constraints"]["content_types"] == ["pdf"]
