"""OMBRE_BREATH_FOOTPRINT：breath 输出里那行「👣 Footprint：…」可关（2026-08-27 她说没必要看）。默认带。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tools.breath._verbatim import footprint_enabled, render_stored_bucket  # noqa: E402

BUCKET = {"id": "abc123", "content": "正文一行。", "metadata": {}}
FOOT = "👣 Footprint：LLM经hold创建 → 正文重构×2"


def _render():
    text, _ = render_stored_bucket(BUCKET, "[bucket_id:abc123]", FOOT)
    return text


def test_default_shows_footprint(monkeypatch):
    monkeypatch.delenv("OMBRE_BREATH_FOOTPRINT", raising=False)
    assert footprint_enabled()
    assert FOOT in _render()


def test_env_off_hides_footprint_but_keeps_body(monkeypatch):
    for off in ("0", "false", "OFF", "no"):
        monkeypatch.setenv("OMBRE_BREATH_FOOTPRINT", off)
        assert not footprint_enabled()
        text = _render()
        assert "👣" not in text and "正文重构" not in text
        assert "正文一行。" in text and "[bucket_id:abc123]" in text


def test_env_on_values_keep_it(monkeypatch):
    for on in ("1", "true", "yes", ""):
        monkeypatch.setenv("OMBRE_BREATH_FOOTPRINT", on)
        assert footprint_enabled()
        assert FOOT in _render()


def test_fallback_line_also_hidden(monkeypatch):
    monkeypatch.setenv("OMBRE_BREATH_FOOTPRINT", "0")
    text, _ = render_stored_bucket(BUCKET, "[bucket_id:abc123]", "👣 Footprint：暂时无法读取")
    assert "Footprint" not in text
