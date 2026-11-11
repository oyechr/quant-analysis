"""report.md rendering (src/reporting/markdown.py)."""

import json
from pathlib import Path
from typing import Any, Dict

from src.reporting.markdown import render_report_markdown


def _report(**sections: Any) -> Dict[str, Any]:
    return {"info": {}, "generated_at": "2026-11-11T09:00", **sections}


def _sample(sample_data_dir: Path, name: str, ticker: str = "AAPL") -> str:
    return (sample_data_dir / ticker / "reports" / name).read_text(encoding="utf-8")


def test_sample_report_renders_analyst_holders_and_news(sample_data_dir):
    report = _sample(sample_data_dir, "report.md")

    assert "## Analyst Consensus" in report
    assert "**28 Buy** | 10 Hold | 1 Sell (from 39 analysts)" in report
    # The date comes from yfinance's GradeDate index on a fresh fetch
    assert "| 2026-08-01 | Broker A | Upgrade | Hold → Buy | $250.00 |" in report
    assert "| 2026-10-01 | Broker C | Downgrade | Buy → Hold | — |" in report

    assert "## Top Institutional Holders" in report
    assert "| Fund 1 | 8.00% |" in report

    assert "## Recent News" in report
    assert "- 2026-10-02 [Results beat estimates](https://example.com/results) — *Wire*" in report


def test_sample_report_json_keeps_rating_change_dates(sample_data_dir):
    data = json.loads(_sample(sample_data_dir, "full_report.json"))
    changes = data["analyst_ratings"]["recent_changes"]
    assert [c["GradeDate"][:10] for c in changes] == ["2026-08-01", "2026-09-01", "2026-10-01"]
    assert changes[2]["currentPriceTarget"] is None  # NaN → None


def test_cached_report_shape_renders_the_same(sample_data_dir):
    """A report.md rebuilt from the saved JSON (the cached path) matches the original."""
    data = json.loads(_sample(sample_data_dir, "full_report.json"))
    rebuilt = render_report_markdown("AAPL", data)
    for line in (
        "| 2026-08-01 | Broker A | Upgrade | Hold → Buy | $250.00 |",
        "| Fund 1 | 8.00% |",
        "[Results beat estimates](https://example.com/results)",
    ):
        assert line in rebuilt


def test_debt_to_equity_and_yield_are_yahoo_percents():
    # Yahoo: debtToEquity 150 means 1.5x; dividendYield 0.31 means 0.31%
    info = {"debt_to_equity": 150.0, "dividend_yield": 0.31, "currency": "USD"}
    report = render_report_markdown("T", _report(info=info))
    assert "| Debt/Equity | 1.50x | Leverage is elevated |" in report
    assert "| Dividend Yield | 0.31% |" in report

    info = {"debt_to_equity": 40.0, "dividend_yield": 6.12}
    report = render_report_markdown("T", _report(info=info))
    assert "| Debt/Equity | 0.40x | Leverage is conservative |" in report
    assert "| Dividend Yield | 6.12% |" in report


def test_market_cap_uses_the_listing_currency():
    info = {"market_cap": 935.11e9, "currency": "NOK"}
    report = render_report_markdown("T", _report(info=info))
    assert "**Market Cap:** kr935.11B" in report


def test_yahoo_text_cannot_break_tables_or_links():
    ratings = {
        "recent_changes": [
            {"GradeDate": "2026-11-01", "Firm": "Smith | Jones", "Action": "init", "ToGrade": "Buy"}
        ]
    }
    holders = {"top_institutional": [{"Holder": "A|B\nFund", "pctHeld": 0.05}]}
    news = {
        "recent_articles": [
            {
                "content": {
                    "title": "Shares [up] 5%",
                    "provider": {"displayName": "Wire"},
                    "canonicalUrl": {"url": "https://example.com/a (b)"},
                }
            }
        ]
    }
    report = render_report_markdown(
        "T", _report(analyst_ratings=ratings, holders=holders, news=news)
    )
    assert "| 2026-11-01 | Smith \\| Jones | Initiates | Buy | — |" in report
    assert "| A\\|B Fund | 5.00% |" in report
    assert "- [Shares \\[up\\] 5%](https://example.com/a%20%28b%29) — *Wire*" in report


def test_old_flat_news_shape_still_renders():
    news = {"recent_articles": [{"title": "Old shape", "publisher": "Wire", "link": "https://x.y"}]}
    report = render_report_markdown("T", _report(news=news))
    assert "- [Old shape](https://x.y) — *Wire*" in report


def test_empty_sections_are_left_out():
    ratings = {"recent_recommendations": [{"strongBuy": 0, "buy": 0, "hold": 0}]}
    news = {"recent_articles": [{"content": {"title": ""}}]}
    report = render_report_markdown(
        "T", _report(analyst_ratings=ratings, holders={"top_institutional": []}, news=news)
    )
    for heading in ("Analyst Consensus", "Top Institutional Holders", "Recent News"):
        assert heading not in report


def test_valuation_markdown_prints_the_ocf_ni_ratio(sample_data_dir):
    data = json.loads(_sample(sample_data_dir, "valuation_analysis.json"))
    quality = data["earnings_analysis"]["earnings_quality"]
    ratio = quality["metrics"]["cash_flow_to_earnings_ratio"]
    assert quality["score"] != round(ratio, 2)  # the bucket score isn't the ratio

    markdown = _sample(sample_data_dir, "valuation_analysis.md")
    assert f"*(OCF/NI Ratio: {ratio:.2f})*" in markdown


def test_chat_context_lists_rating_changes(sample_data_dir):
    from src.llm import build_brief_context

    data = json.loads(_sample(sample_data_dir, "full_report.json"))
    context = build_brief_context(data, red_flags=[])
    assert "Recent changes (latest 5):" in context
    assert "2026-08-01  Broker A  up  Hold -> Buy" in context
