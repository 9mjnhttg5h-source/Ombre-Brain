"""trace 门房卡口（2026-08-15 立法）：堵「先干净入库、再 trace 补写」的后门。

范围：
- content 全文替换：整篇按新货标准检；
- old_str/new_str 局部替换：只检 new_str 新增片段（旧正文历史病灶不阻塞编辑）；
- plan / letter / test_data：豁免，与 hold/grow 门房范围对称。
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools import _common as common
from tools import _runtime as rt
from tools.trace.core import _trace_style_lint, trace_core


@pytest.fixture
def gate_runtime(monkeypatch, bucket_mgr, test_config, tmp_path):
    monkeypatch.setattr(rt, "config", test_config, raising=False)
    monkeypatch.setattr(rt, "bucket_mgr", bucket_mgr, raising=False)
    monkeypatch.setattr(rt, "logger", MagicMock(), raising=False)
    monkeypatch.setattr(rt, "fire_webhook", None, raising=False)
    monkeypatch.setattr(rt, "mark_op", None, raising=False)
    monkeypatch.setattr(rt, "v3_runtime", None, raising=False)
    # 词表：alpha / beta 两词；隔离区写到 tmp，绝不碰真数据盘
    vocab = tmp_path / "style_lint.yaml"
    vocab.write_text(
        "families:\n  first:\n    - alpha\n  second:\n    - beta\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(common, "_style_lint_paths", lambda: (vocab,))
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(tmp_path / "buckets"))
    return bucket_mgr


@pytest.mark.asyncio
async def test_trace_content_rejects_two_distinct_terms(gate_runtime):
    manager = gate_runtime
    original = "干净的正文，没有任何命中。"
    bucket_id = await manager.create(content=original)

    result = await trace_core(
        bucket_id, content="改写正文，夹带 alpha 与 beta 两个词。"
    )
    bucket = await manager.get(bucket_id)

    assert result == common.STYLE_LINT_REJECTION
    assert bucket is not None
    assert bucket["content"] == original


@pytest.mark.asyncio
async def test_trace_patch_new_str_rejects_two_terms(gate_runtime):
    manager = gate_runtime
    original = "开头\n可替换片段\n结尾"
    bucket_id = await manager.create(content=original)

    result = await trace_core(
        bucket_id,
        old_str="可替换片段",
        new_str="夹带 alpha 与 beta 的新片段",
    )
    bucket = await manager.get(bucket_id)

    assert result == common.STYLE_LINT_REJECTION
    assert bucket is not None
    assert bucket["content"] == original


@pytest.mark.asyncio
async def test_trace_patch_single_term_passes(gate_runtime, monkeypatch):
    manager = gate_runtime
    original = "开头\n可替换片段\n结尾"
    bucket_id = await manager.create(content=original)

    async def fake_embedding(target_id, content):
        return True

    monkeypatch.setattr(
        manager.embedding_engine, "generate_and_store", fake_embedding
    )

    result = await trace_core(
        bucket_id,
        old_str="可替换片段",
        new_str="只带 alpha 一个词的新片段",
    )
    bucket = await manager.get(bucket_id)

    assert "content=已局部替换" in result
    assert bucket is not None
    assert "只带 alpha 一个词的新片段" in bucket["content"]


def test_trace_gate_exemptions_plan_letter_testdata(gate_runtime):
    dirty = "夹带 alpha 与 beta"
    plan_bucket = {"metadata": {"type": "plan"}}
    test_bucket = {"metadata": {"type": "dynamic", "test_data": True}}
    normal_bucket = {"metadata": {"type": "dynamic"}}

    assert _trace_style_lint(dirty, plan_bucket) == ""
    assert _trace_style_lint(dirty, test_bucket) == ""
    assert _trace_style_lint(dirty, normal_bucket) == common.STYLE_LINT_REJECTION
