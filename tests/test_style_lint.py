import hashlib
import re
from pathlib import Path

import pytest

from tools import _common as common
from tools import _runtime as rt
from tools.grow import dispatch as grow_dispatch
from tools.hold import core as hold_core
from tools.hold import dispatch as hold_dispatch


class _Decay:
    async def ensure_started(self):
        return None


class _Dehydrator:
    async def analyze(self, _content):
        return {
            "domain": ["未分类"],
            "valence": 0.5,
            "arousal": 0.3,
            "tags": [],
            "suggested_name": "",
        }


@pytest.fixture
def lint_vocabulary(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "style_lint.yaml"
    path.write_text(
        "families:\n  first:\n    - alpha\n  second:\n    - beta\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(common, "_style_lint_paths", lambda: (path,))
    return path


def test_style_lint_defaults_on_and_reloads_vocabulary(
    lint_vocabulary, monkeypatch, tmp_path
):
    from utils import load_config

    config = load_config(str(tmp_path / "missing-config.yaml"))
    assert config["style_lint"]["enabled"] is True
    assert config["style_lint"]["count_mode"] == "distinct"
    monkeypatch.setattr(rt, "config", config)

    assert common.style_lint_rejection("alpha beta") == common.STYLE_LINT_REJECTION
    lint_vocabulary.write_text(
        "families:\n  replacement:\n    - gamma\n    - delta\n",
        encoding="utf-8",
    )
    assert common.style_lint_rejection("alpha beta") == ""
    assert common.style_lint_rejection("gamma delta") == common.STYLE_LINT_REJECTION


@pytest.mark.asyncio
async def test_merge_gate_rejects_two_hits_and_preserves_all_bypasses(
    lint_vocabulary, monkeypatch, tmp_path
):
    calls = []
    log_lines = []

    class _Logger:
        def info(self, message):
            log_lines.append(message)

    async def fake_inner(**kwargs):
        calls.append(kwargs["content"])
        return "bucket-1", False, ""

    monkeypatch.setattr(common, "_merge_or_create_inner", fake_inner)
    monkeypatch.setattr(common.rt, "bucket_mgr", object(), raising=False)
    monkeypatch.setattr(common.rt, "logger", _Logger(), raising=False)
    buckets_dir = tmp_path / "buckets"
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(buckets_dir))
    monkeypatch.setattr(
        common.rt,
        "config",
        {"style_lint": {"enabled": True, "count_mode": "distinct"}},
    )

    repeated = await common.merge_or_create(
        content="alpha alpha alpha",
        tags=[],
        importance=5,
        domain=[],
        valence=0.5,
        arousal=0.3,
        source_tool="hold",
    )
    assert repeated == ("bucket-1", False, "")

    rejected_content = "alpha 第一行\nbeta 尾行"
    rejected = await common.merge_or_create(
        content=rejected_content,
        tags=[],
        importance=5,
        domain=[],
        valence=0.5,
        arousal=0.3,
        source_tool="hold",
    )
    assert rejected == (common.STYLE_LINT_REJECTION, False, "")
    assert calls == ["alpha alpha alpha"]

    quarantine_files = list((buckets_dir / "_lint_quarantine").iterdir())
    assert len(quarantine_files) == 1
    quarantine_file = quarantine_files[0]
    digest = hashlib.sha256(rejected_content.encode("utf-8")).hexdigest()[:8]
    assert re.fullmatch(rf"\d{{8}}-\d{{6}}Z-{digest}\.md", quarantine_file.name)
    record = quarantine_file.read_text(encoding="utf-8")
    header, stored_content = record.split("## Content\n\n", 1)
    assert re.search(r"^- time: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", header, re.M)
    assert "- source_tool: hold\n" in header
    assert "- hits: alphax1,betax1\n" in header
    assert "- hit_total: 2\n" in header
    assert f"- content_bytes: {len(rejected_content.encode('utf-8'))}\n" in header
    assert stored_content == rejected_content
    assert log_lines == [
        f"op=style_lint action=reject hits=alphax1,betax1 "
        f"len={len(rejected_content.encode('utf-8'))} file={quarantine_file.name}"
    ]

    one_hit = await common.merge_or_create(
        content="alpha only",
        tags=[],
        importance=5,
        domain=[],
        valence=0.5,
        arousal=0.3,
    )
    assert one_hit == ("bucket-1", False, "")

    common.rt.config = {"style_lint": {"enabled": False}}
    disabled = await common.merge_or_create(
        content="alpha and beta",
        tags=[],
        importance=5,
        domain=[],
        valence=0.5,
        arousal=0.3,
    )
    assert disabled == ("bucket-1", False, "")

    common.rt.config = {"style_lint": {"enabled": True}}
    test_data = await common.merge_or_create(
        content="alpha and beta",
        tags=[],
        importance=5,
        domain=[],
        valence=0.5,
        arousal=0.3,
        test_data=True,
    )
    assert test_data == ("bucket-1", False, "")
    assert len(list((buckets_dir / "_lint_quarantine").iterdir())) == 1

    common.rt.config = {"style_lint": {"enabled": True, "count_mode": "total"}}
    total_mode = await common.merge_or_create(
        content="alpha alpha",
        tags=[],
        importance=5,
        domain=[],
        valence=0.5,
        arousal=0.3,
        source_tool="grow",
    )
    assert total_mode == (common.STYLE_LINT_REJECTION, False, "")
    assert len(list((buckets_dir / "_lint_quarantine").iterdir())) == 2
    assert calls == [
        "alpha alpha alpha",
        "alpha only",
        "alpha and beta",
        "alpha and beta",
    ]


@pytest.mark.asyncio
async def test_hold_tool_response_is_exact_and_pass_response_is_unchanged(
    lint_vocabulary, monkeypatch, tmp_path
):
    merge_calls = []

    async def fake_merge_or_create(**kwargs):
        merge_calls.append(kwargs["content"])
        return "bucket-1", False, ""

    async def background(*_args, **_kwargs):
        return None

    def close_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(rt, "config", {"style_lint": {"enabled": True}})
    monkeypatch.setattr(rt, "decay_engine", _Decay(), raising=False)
    monkeypatch.setattr(rt, "dehydrator", _Dehydrator(), raising=False)
    monkeypatch.setattr(rt, "mark_op", None, raising=False)
    monkeypatch.setattr(rt, "record_v3_tool_event", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(tmp_path / "buckets"))
    monkeypatch.setattr(hold_core, "merge_or_create", fake_merge_or_create)
    monkeypatch.setattr(hold_core, "check_plan_resolution", background)
    monkeypatch.setattr(hold_core, "check_duplicate_for", background)
    monkeypatch.setattr(hold_core.asyncio, "create_task", close_task)

    rejected = await hold_dispatch("alpha and beta")
    assert rejected == "这条先放着。检查一下自己不合适的比喻，换个说法再存一次。"
    assert "alpha" not in rejected and "beta" not in rejected
    assert merge_calls == []

    rejected_feel = await hold_dispatch(
        "alpha and beta", feel=True, source_bucket="source-1"
    )
    assert rejected_feel == "这条先放着。检查一下自己不合适的比喻，换个说法再存一次。"
    assert merge_calls == []

    one_hit = await hold_dispatch("alpha only")
    assert one_hit == "新建→bucket-1 未分类"

    repeated = await hold_dispatch("alpha alpha alpha")
    assert repeated == one_hit

    rt.config = {"style_lint": {"enabled": False}}
    disabled = await hold_dispatch("alpha and beta")
    assert disabled == one_hit

    rt.config = {"style_lint": {"enabled": True}}
    test_data = await hold_dispatch("alpha and beta", test_data=True)
    assert test_data == one_hit
    assert merge_calls == [
        "alpha only",
        "alpha alpha alpha",
        "alpha and beta",
        "alpha and beta",
    ]


@pytest.mark.asyncio
async def test_grow_items_rejects_entire_batch_before_writing(
    lint_vocabulary, monkeypatch
):
    import tools.grow as grow_module

    called = False

    async def fake_grow_items(*_args, **_kwargs):
        nonlocal called
        called = True
        return "unexpected"

    monkeypatch.setattr(rt, "config", {"style_lint": {"enabled": True}})
    monkeypatch.setattr(rt, "decay_engine", _Decay(), raising=False)
    monkeypatch.setattr(grow_module, "grow_items", fake_grow_items)

    result = await grow_dispatch(items=["alpha and beta"])

    assert result == "这条先放着。检查一下自己不合适的比喻，换个说法再存一次。"
    assert called is False


@pytest.mark.asyncio
async def test_server_wrapper_never_appends_notices_to_rejection(monkeypatch):
    from errors import push_warning
    import server

    async def rejected_with_warning():
        push_warning("OB-W001", "must not be appended")
        return common.STYLE_LINT_REJECTION

    monkeypatch.setattr(server, "_pop_deletion_notice", lambda: "prefix")

    result = await server._with_notice(rejected_with_warning(), op="")

    assert result == "这条先放着。检查一下自己不合适的比喻，换个说法再存一次。"
    assert server.pop_warnings() == []
