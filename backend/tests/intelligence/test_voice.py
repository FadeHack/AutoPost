"""Tests for the deterministic AI-tell stripper."""
from __future__ import annotations

from app.intelligence.voice import strip_ai_tells


class TestEmDashSeparator:
    def test_replaces_em_dash_with_period(self):
        out, v = strip_ai_tells("This is one thought — and this is another.")
        assert "—" not in out
        assert "This is one thought." in out
        assert "em_dash_separator" in v

    def test_no_em_dash_no_violation(self):
        out, v = strip_ai_tells("This is fine. No em-dash here.")
        assert "em_dash_separator" not in v
        assert out == "This is fine. No em-dash here."


class TestClosingSummary:
    def test_drops_in_summary_paragraph(self):
        text = (
            "Real opening hook.\n\n"
            "Middle paragraph with concrete details.\n\n"
            "In summary, here is what we learned."
        )
        out, v = strip_ai_tells(text)
        assert "In summary" not in out
        assert "closing_summary" in v
        assert "Middle paragraph" in out

    def test_drops_to_summarize_paragraph(self):
        text = (
            "Hook.\n\n"
            "Body.\n\n"
            "To summarize, the lesson here is X."
        )
        out, _ = strip_ai_tells(text)
        assert "summarize" not in out.lower()

    def test_no_summary_no_violation(self):
        out, v = strip_ai_tells("Hook.\n\nBody.\n\nA punchy takeaway.")
        assert "closing_summary" not in v


class TestBannedPhrases:
    def test_strips_delve(self):
        out, v = strip_ai_tells("Let's delve into the details now.")
        assert "delve" not in out.lower()
        assert "delve" in v

    def test_strips_moreover(self):
        out, v = strip_ai_tells("It is fast. Moreover, it is cheap.")
        assert "moreover" not in out.lower()
        assert "moreover" in v

    def test_case_insensitive(self):
        out, v = strip_ai_tells("MOREOVER, FURTHERMORE, this is bad.")
        assert "moreover" not in out.lower()
        assert "furthermore" not in out.lower()
        assert "moreover" in v
        assert "furthermore" in v

    def test_strips_multiple_phrases(self):
        text = (
            "Furthermore, the system is robust. "
            "It's worth noting that this is hard. "
            "I hope this helps explain."
        )
        out, v = strip_ai_tells(text)
        assert "furthermore" not in out.lower()
        assert "it's worth noting" not in out.lower()
        assert "i hope this helps" not in out.lower()
        assert {"furthermore", "it's worth noting", "i hope this helps"}.issubset(set(v))

    def test_clean_text_no_violations(self):
        text = "Hook line. Concrete detail. Sharp takeaway."
        out, v = strip_ai_tells(text)
        assert v == []
        assert out == text


class TestWhitespaceTidying:
    def test_collapses_double_spaces(self):
        out, _ = strip_ai_tells("hello  world  here")
        assert "  " not in out

    def test_collapses_triple_blank_lines(self):
        out, _ = strip_ai_tells("A\n\n\n\nB")
        assert out == "A\n\nB"

    def test_no_space_before_punctuation(self):
        out, _ = strip_ai_tells("Hello , world . Yes !")
        assert ", world." in out
        assert " !" not in out


class TestIdempotent:
    def test_running_twice_is_same_as_once(self):
        text = "Furthermore — this is wrong.\n\nIn conclusion, it works."
        once, _ = strip_ai_tells(text)
        twice, _ = strip_ai_tells(once)
        assert once == twice


class TestOrphanCapitalization:
    def test_capitalizes_lowercase_after_removed_sentence_start(self):
        # Removing "this got me thinking" from sentence start leaves "about X." —
        # the orphan preposition should be capitalized.
        out, v = strip_ai_tells("This got me thinking about the real problem.")
        assert "this got me thinking" in v
        # Whatever the first word ends up being, it must be capitalized.
        assert out[0].isupper()
        assert out == "About the real problem."

    def test_capitalizes_after_period(self):
        # "Moreover" is banned. After removal, "this" must be capitalized.
        out, _ = strip_ai_tells("It is fast. Moreover, this is bad.")
        assert ". This is bad" in out

    def test_capitalizes_after_newline(self):
        out, _ = strip_ai_tells("First line.\n\nfurthermore, second one.")
        # "Furthermore" removed at line start → next word capitalized.
        assert "Second one" in out

    def test_no_change_when_already_capitalized(self):
        out, _ = strip_ai_tells("Hook line. Body line. Closing line.")
        assert out == "Hook line. Body line. Closing line."
