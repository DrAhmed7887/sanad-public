"""The reviewer must only accept complete, valid Argon reviews and otherwise fall back (PR #4 review)."""
import importlib.util
import json
import pathlib
import subprocess

spec = importlib.util.spec_from_file_location("review_pr", pathlib.Path(__file__).parent.parent / "scripts/review_pr.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

OK = "Summary.\n1. [NIT] x\nVERDICT: APPROVE"
BLOCKED = "1. [BLOCK] wrong rule at r1.py:3\nVERDICT: BLOCK"


def boom(_):
    raise RuntimeError("down")


def test_valid_argon_review_is_used():
    who, text = rp.review_with_fallback("p", primary=lambda p: OK, fallback=boom)
    assert who.startswith("gemini") and text == OK


def test_valid_argon_block_is_kept():
    who, text = rp.review_with_fallback("p", primary=lambda p: BLOCKED, fallback=boom)
    assert who.startswith("gemini") and rp.parse_verdict(text) == "BLOCK"


def test_invalid_argon_review_falls_back():
    who, text = rp.review_with_fallback("p", primary=lambda p: "no verdict here", fallback=lambda p: OK)
    assert who.startswith("gpt-6") and text == OK


def test_argon_errors_fall_back():
    for exc in (RuntimeError("x"), TypeError("x"), KeyError("x"), subprocess.TimeoutExpired("gcloud", 30)):
        def bad(_p, e=exc):
            raise e
        who, _ = rp.review_with_fallback("p", primary=bad, fallback=lambda p: OK)
        assert who.startswith("gpt-6")


class _Resp:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_gcloud(monkeypatch, code=0, out="tok"):
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, code, out, ""))


def test_argon_rejects_truncated_response(monkeypatch):
    _fake_gcloud(monkeypatch)
    payload = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": OK}]}}]}
    monkeypatch.setattr(rp.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    try:
        rp.argon("p")
        assert False, "should raise"
    except RuntimeError as e:
        assert "finishReason" in str(e)


def test_argon_rejects_null_content(monkeypatch):
    _fake_gcloud(monkeypatch)
    payload = {"candidates": [{"finishReason": "STOP", "content": None}]}
    monkeypatch.setattr(rp.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    try:
        rp.argon("p")
        assert False, "should raise"
    except RuntimeError as e:
        assert "empty" in str(e)


def test_argon_token_failure(monkeypatch):
    _fake_gcloud(monkeypatch, code=1, out="")
    try:
        rp.argon("p")
        assert False, "should raise"
    except RuntimeError as e:
        assert "gcloud" in str(e)


def test_argon_complete_response(monkeypatch):
    _fake_gcloud(monkeypatch)
    payload = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": OK}]}}]}
    monkeypatch.setattr(rp.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    assert rp.argon("p") == OK


def test_malformed_argon_with_block_findings_is_kept_not_discarded():
    text = "1. [BLOCK] r1.py:3 wrong threshold\n(no verdict line)"
    who, out = rp.review_with_fallback("p", primary=lambda p: text, fallback=lambda p: OK)
    assert who.startswith("gemini") and out == text and rp.parse_verdict(out) == "INVALID"


def test_any_argon_exception_falls_back():
    class Weird(Exception):
        pass

    def bad(_p):
        raise Weird("incomplete read")
    who, _ = rp.review_with_fallback("p", primary=bad, fallback=lambda p: OK)
    assert who.startswith("gpt-6")


def test_argon_rejects_non_dict_json(monkeypatch):
    _fake_gcloud(monkeypatch)
    monkeypatch.setattr(rp.urllib.request, "urlopen", lambda *a, **k: _Resp([1, 2]))
    try:
        rp.argon("p")
        assert False
    except RuntimeError as e:
        assert "shape" in str(e)


def test_truncated_argon_with_block_is_kept(monkeypatch):
    _fake_gcloud(monkeypatch)
    payload = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "1. [BLOCK] r1.py:3 x"}]}}]}
    monkeypatch.setattr(rp.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    who, out = rp.review_with_fallback("p", fallback=lambda p: OK)
    assert "incomplete" in who and rp.parse_verdict(out) == "INVALID"


def test_argon_retries_on_429(monkeypatch):
    import urllib.error
    _fake_gcloud(monkeypatch)
    monkeypatch.setattr(rp.time, "sleep", lambda s: None)
    calls = {"n": 0}
    payload = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": OK}]}}]}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        return _Resp(payload)
    monkeypatch.setattr(rp.urllib.request, "urlopen", flaky)
    assert rp.argon("p") == OK and calls["n"] == 3
