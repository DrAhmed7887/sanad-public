"""The PR reviewer's verdict parser must fail closed (Terra review finding 4)."""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("review_pr", pathlib.Path(__file__).parent.parent / "scripts/review_pr.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


def test_clean_approve():
    assert rp.parse_verdict("Summary.\n1. [NIT] style\nVERDICT: APPROVE\n") == "APPROVE"


def test_valid_block_is_block():
    assert rp.parse_verdict("1. [BLOCK] wrong rule\nVERDICT: BLOCK") == "BLOCK"


def test_approve_with_block_finding_is_invalid():
    assert rp.parse_verdict("1. [BLOCK] wrong rule\nVERDICT: APPROVE") == "INVALID"


def test_block_without_findings_is_invalid():
    assert rp.parse_verdict("1. [FIX] x\nVERDICT: BLOCK") == "INVALID"


def test_verdict_not_on_last_line_is_invalid():
    assert rp.parse_verdict("VERDICT: APPROVE\nmore text after") == "INVALID"


def test_malformed_or_empty_is_invalid():
    assert rp.parse_verdict("") == "INVALID"
    assert rp.parse_verdict("verdict: approve") == "INVALID"


def test_secret_patterns_cover_common_formats():
    # Fake credentials are assembled at runtime so this file never contains one (CI scans the repo text).
    pk = "PRIVATE " + "KEY"
    for s in ("-----BEGIN " + pk + "-----", "-----BEGIN OPENSSH " + pk + "-----", "github_" + "pat_" + "A" * 30,
              "gh" + "p_" + "a" * 36, "AK" + "IA" + "B" * 16, "s" + "k-" + "c" * 30, "AI" + "za" + "d" * 35,
              "xo" + "xb-123"):
        assert rp.SECRET_RX.search(s), s
    assert not rp.SECRET_RX.search("BEGIN (RSA|OPENSSH|EC) PRIVATE KEY is a pattern, not a key")


def test_secret_patterns_catch_hex_and_assigned_keys():
    hexkey = "0123456789abcdef" + "0123456789ABCDEF"  # 32 hex, assembled at runtime
    assert rp.SECRET_RX.search("key " + hexkey + " end")
    assert rp.SECRET_RX.search("AZURE_OPENAI_" + "KEY=" + "x" * 20)
    assert not rp.SECRET_RX.search("commit 585db3f0a1b2c3d4e5f60718293a4b5c6d7e8f90 ok")  # 40-hex SHA
    assert not rp.SECRET_RX.search("sha256 prefix 4bb97896afe2ec08")


def test_secret_patterns_catch_json_quoted_keys():
    assert rp.SECRET_RX.search('{"api_' + 'key": "' + "z" * 20 + '"}')
    assert rp.SECRET_RX.search("{'tok" + "en': '" + "q" * 24 + "'}")


def test_secret_patterns_catch_punctuated_values_in_both_scanners(tmp_path):
    import subprocess
    sample = 'api_' + 'key="!Abcdefghijklmnop123"'
    assert rp.SECRET_RX.search(sample)
    f = tmp_path / "sample.txt"
    f.write_text(sample + "\n")
    patterns = pathlib.Path(__file__).parent.parent / ".github/secret-patterns.txt"
    r = subprocess.run(["grep", "-c", "-i", "-E", "-f", str(patterns), str(f)], capture_output=True, text=True)
    assert r.returncode == 0, "CI pattern file must also catch it"


def test_tag_mentioned_in_prose_is_not_a_finding():
    text = "Summary.\n1. [FIX] keep a substantive `[BLOCK]` finding when parsing\nVERDICT: APPROVE"
    assert rp.parse_verdict(text) == "APPROVE"


def test_bold_numbered_block_finding_counts():
    assert rp.parse_verdict("1. **[BLOCK] `x.py:1`** wrong\nVERDICT: BLOCK") == "BLOCK"


def test_tag_after_location_counts():
    assert rp.parse_verdict("1. **src/r1.py:3 — [BLOCK]** wrong threshold\nVERDICT: APPROVE") == "INVALID"
    assert rp.parse_verdict("1. **src/r1.py:3 — [BLOCK]** wrong threshold\nVERDICT: BLOCK") == "BLOCK"


def test_tag_on_following_line_counts():
    text = "Summary.\n1. `src/r1.py:3` wrong threshold\n   [BLOCK] the criterion is inverted\nVERDICT: APPROVE"
    assert rp.parse_verdict(text) == "INVALID"


def test_bare_verdict_is_invalid():
    assert rp.parse_verdict("VERDICT: APPROVE") == "INVALID"


def test_bullet_block_cannot_approve():
    assert rp.parse_verdict("Summary.\n- [BLOCK] src/r1.py:3 wrong threshold\nVERDICT: APPROVE") == "INVALID"
    assert rp.parse_verdict("Summary.\n* **[BLOCK]** x\nVERDICT: APPROVE") == "INVALID"


def test_backticked_mention_still_allows_approve():
    assert rp.parse_verdict("Summary.\n1. [NIT] mention `[BLOCK]` tag docs\nVERDICT: APPROVE") == "APPROVE"


def test_sk_pattern_needs_a_word_start():
    assert not rp.SECRET_RX.search("R3: tas" + "k-and-response-tracker scenario oracle")  # assembled: no literal
    assert rp.SECRET_RX.search("key " + "s" + "k-" + "z" * 24)
