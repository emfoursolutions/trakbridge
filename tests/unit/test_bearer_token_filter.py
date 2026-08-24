# ABOUTME: Unit tests for the BearerTokenFilter log redactor.
# ABOUTME: Ensures API-key bearer secrets never leak into log output.
"""Tests for services.logging_service.BearerTokenFilter."""

import logging

import pytest

from services.logging_service import BearerTokenFilter, _redact_bearer


@pytest.fixture
def filter_():
    return BearerTokenFilter()


def _make_record(msg, args=None):
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )


class TestRedactBearer:
    def test_full_token_reduced_to_prefix(self):
        text = "Bearer tb_pat_abcdefghijklmnopqrstuvwxyz012345678"
        result = _redact_bearer(text)
        assert result == "Bearer tb_pat_abcdefghijkl...REDACTED"

    def test_multiple_tokens_in_one_line(self):
        text = (
            "old=Bearer tb_pat_AAAAAAAAAAAAsecret "
            "new=Bearer tb_pat_BBBBBBBBBBBBother"
        )
        result = _redact_bearer(text)
        assert "secret" not in result
        assert "other" not in result
        assert result.count("REDACTED") == 2

    def test_short_token_still_redacted(self):
        # A pathological short token (shouldn't exist in prod but must
        # still be redacted if seen).
        text = "Bearer tb_pat_abc"
        result = _redact_bearer(text)
        assert "REDACTED" in result

    def test_non_matching_text_passthrough(self):
        text = "Normal log line about a stream_id=5 event"
        assert _redact_bearer(text) == text

    def test_case_insensitive_bearer(self):
        text = "bearer tb_pat_XXXXXXXXXXXXsupersecret"
        result = _redact_bearer(text)
        assert "supersecret" not in result

    def test_never_touches_ghp_or_other_prefixes(self):
        # Only our own prefix is redacted; other services' tokens are
        # not in scope for this filter.
        text = "Bearer ghp_1234567890abcdef"
        assert _redact_bearer(text) == text


class TestFilterAppliedToRecord:
    def test_string_msg_is_redacted(self, filter_):
        record = _make_record(
            "auth failed for Bearer tb_pat_XXXXXXXXXXXXpayload"
        )
        filter_.filter(record)
        assert "payload" not in record.msg
        assert "REDACTED" in record.msg

    def test_tuple_args_are_redacted(self, filter_):
        record = _make_record(
            "auth failed for %s",
            args=("Bearer tb_pat_XXXXXXXXXXXXpayload",),
        )
        filter_.filter(record)
        assert "payload" not in record.args[0]

    def test_dict_args_are_redacted(self, filter_):
        # Bypass LogRecord's dict-in-tuple auto-unwrap by constructing
        # the record with tuple args and then swapping to a dict — this
        # mirrors production code that later assigns record.args = {...}.
        record = _make_record("auth failed for %(auth)s")
        record.args = {"auth": "Bearer tb_pat_XXXXXXXXXXXXpayload"}
        filter_.filter(record)
        assert "payload" not in record.args["auth"]

    def test_non_string_args_untouched(self, filter_):
        record = _make_record("count=%d", args=(42,))
        result = filter_.filter(record)
        assert result is True
        assert record.args == (42,)

    def test_filter_never_drops_records(self, filter_):
        record = _make_record("anything")
        assert filter_.filter(record) is True
