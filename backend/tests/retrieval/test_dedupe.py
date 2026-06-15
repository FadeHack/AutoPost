"""Unit tests for the dedupe module."""
from __future__ import annotations

from app.models.base import TrendSource
from app.retrieval.base import TrendItem
from app.retrieval.dedupe import (
    dedupe,
    normalize_title,
    normalize_url,
    title_similarity,
    url_hash,
)


def _make(title: str, url: str, source: TrendSource = TrendSource.rss) -> TrendItem:
    return TrendItem(source=source, source_id=url, title=title, url=url)


class TestNormalizeURL:
    def test_strips_tracking_params(self):
        result = normalize_url(
            "https://example.com/post?utm_source=x&utm_medium=email&keep=1"
        )
        assert result == "https://example.com/post?keep=1"

    def test_strips_fbclid_gclid_ref(self):
        result = normalize_url(
            "https://example.com/p?fbclid=abc&gclid=xyz&ref=feed&id=42"
        )
        assert result == "https://example.com/p?id=42"

    def test_lowercases_host(self):
        assert normalize_url("https://EXAMPLE.com/p").startswith(
            "https://example.com"
        )

    def test_drops_trailing_slash(self):
        assert normalize_url("https://example.com/p/") == "https://example.com/p"

    def test_keeps_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_degenerate_input_does_not_raise(self):
        # urlparse is permissive — degenerate input gets normalized rather
        # than rejected. The contract is "don't crash on weird inputs."
        assert isinstance(normalize_url("  not a url  "), str)
        assert isinstance(normalize_url(""), str)


class TestURLHash:
    def test_equivalence(self):
        a = url_hash("https://example.com/p?utm_source=x")
        b = url_hash("https://EXAMPLE.com/p/")
        assert a == b

    def test_distinct(self):
        a = url_hash("https://example.com/a")
        b = url_hash("https://example.com/b")
        assert a != b


class TestTitleSimilarity:
    def test_identical(self):
        assert title_similarity("hello world", "hello world") == 1.0

    def test_disjoint_low(self):
        assert title_similarity("hello world", "totally unrelated") < 0.2

    def test_punctuation_insensitive(self):
        # Punctuation/case shouldn't move the score meaningfully.
        assert (
            title_similarity("OpenAI ships new model!", "openai ships new model")
            >= 0.9
        )

    def test_normalize_title_collapses_whitespace(self):
        assert normalize_title("  Foo   BAR! ") == "foo bar"


class TestDedupe:
    def test_empty(self):
        assert dedupe([]) == []

    def test_collapses_url_dups_with_tracking_diff(self):
        items = [
            _make("OpenAI ships model", "https://openai.com/p?utm_source=x"),
            _make("OpenAI ships model", "https://openai.com/p/"),
        ]
        result = dedupe(items)
        assert len(result) == 1
        # First in wins
        assert result[0].url == "https://openai.com/p?utm_source=x"

    def test_collapses_near_title_dups_across_sources(self):
        items = [
            _make(
                "OpenAI ships new model GPT-5",
                "https://openai.com/blog/gpt5",
            ),
            _make(
                "OpenAI ships new model GPT-5",
                "https://news.ycombinator.com/item?id=123",
                source=TrendSource.hackernews,
            ),
        ]
        result = dedupe(items)
        assert len(result) == 1
        # Earlier-source wins (RSS over HN)
        assert result[0].source == TrendSource.rss

    def test_keeps_distinct_items(self):
        items = [
            _make("OpenAI ships GPT-5", "https://openai.com/p1"),
            _make("Stripe explains payments", "https://stripe.com/p2"),
            _make("Hugging Face new infra", "https://huggingface.co/p3"),
        ]
        result = dedupe(items)
        assert len(result) == 3

    def test_preserves_input_order(self):
        items = [
            _make("first", "https://example.com/a"),
            _make("second", "https://example.com/b"),
            _make("third", "https://example.com/c"),
        ]
        result = dedupe(items)
        assert [t.title for t in result] == ["first", "second", "third"]

    def test_threshold_configurable(self):
        items = [
            _make("OpenAI ships GPT-5", "https://a.com/1"),
            _make("OpenAI ships GPT-4", "https://b.com/2"),
        ]
        # At the default 0.85 these should be distinct.
        assert len(dedupe(items)) == 2
        # At a permissive 0.5 they collapse.
        assert len(dedupe(items, title_threshold=0.5)) == 1
