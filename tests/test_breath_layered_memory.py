"""分层浮现 v3（surfacing.layered_memory）行为测试。

设计文档：docs/design-surfacing-quota.md（CLI sol + 官端 sol 双外审，库主终审）。

覆盖面：
- 总开关分流：默认关闭时走旧路径，新路径函数不被触碰
- 近期池选取边界：last_event_at 优先于 created / imported 排除 /
  未来时间戳排除 / recency.max 条数上限
- 保证露面：预算不足时近期桶降级为索引行并明示"正文未展开"，不静默消失
- 域劈分：纯技术域索引化 / 混合域保护 / importance 豁免 / 默认域保护
- 跨池去重：近期桶不在有体温 / 技术索引 / 久未浮现重复出现
- 全文池名额扣减：weighted_limit = max_results - len(近期)
- render_index_line：title 优先 / name 去时间前缀 / meaning 取最新 /
  强制单行 / 保留 stored-data 安全边界
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import frontmatter
import pytest

import tools._runtime as rt
from tools.breath.surface import surface_default
from tools.breath._verbatim import render_index_line


def _layered_cfg(**overrides):
    cfg = {
        "layered_memory": {
            "enabled": True,
            "recency": {"days": 7, "max": 4},
            "tech_index": {
                "enabled": True,
                "domains": ["编程", "工作"],
                "max": 8,
                "importance_exempt": 9,
            },
        }
    }
    cfg["layered_memory"].update(overrides)
    return cfg


class EchoDehydrator:
    async def dehydrate(self, content, meta=None):
        return content


class EmptyEmbedding:
    enabled = False


def install_runtime(bucket_mgr, decay_eng, surfacing_extra=None):
    rt.config = {"surfacing": dict(surfacing_extra or {})}
    rt.bucket_mgr = bucket_mgr
    rt.decay_engine = decay_eng
    rt.dehydrator = EchoDehydrator()
    rt.embedding_engine = EmptyEmbedding()
    rt.logger = MagicMock()
    rt.fire_webhook = None
    rt.mark_op = None


def _set_meta(bucket_mgr, bucket_id: str, **fields) -> None:
    """直接改桶 frontmatter；值为 None 时删除该字段。"""
    fpath = bucket_mgr._find_bucket_file(bucket_id)
    post = frontmatter.load(fpath)
    for k, v in fields.items():
        if v is None:
            post.metadata.pop(k, None)
        else:
            post[k] = v
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _section(result: str, header: str) -> str:
    """截取某一段（=== X === 到下一个 === 或结尾）的文本，缺段返回空串。"""
    marker = f"=== {header} ===\n"
    start = result.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = result.find("\n\n=== ", start)
    return result[start:] if end == -1 else result[start:end]


# ------------------------------------------------------------
# 总开关
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_switch_off_keeps_old_path(bucket_mgr, decay_eng, monkeypatch):
    """默认（不配置 layered_memory）走旧路径，新路径函数零触碰。"""
    install_runtime(bucket_mgr, decay_eng)

    async def _boom(*a, **k):
        raise AssertionError("layered path must not run when switch is off")

    monkeypatch.setattr("tools.breath.surface._surface_layered", _boom)

    await bucket_mgr.create(content="一条普通记忆", importance=5)
    result = await surface_default(max_results=10, max_tokens=10000, tag_filter=[])

    assert "=== 近期原文 ===" not in result
    assert "=== 有体温的浮现 ===" not in result
    assert "一条普通记忆" in result  # 旧路径正常出货


# ------------------------------------------------------------
# 近期池
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_recency_selection_boundaries(bucket_mgr, decay_eng):
    """last_event_at 优先；imported / 未来时间排除；7 天窗口生效。"""
    install_runtime(bucket_mgr, decay_eng, _layered_cfg())
    now = datetime.now()

    a = await bucket_mgr.create(content="昨天的新记忆AAA", importance=5)
    _set_meta(bucket_mgr, a,
              created=_iso(now - timedelta(days=1)),
              last_event_at=_iso(now - timedelta(days=1)))

    b = await bucket_mgr.create(content="十天前的老记忆BBB", importance=5)
    _set_meta(bucket_mgr, b,
              created=_iso(now - timedelta(days=10)),
              last_event_at=_iso(now - timedelta(days=10)))

    c = await bucket_mgr.create(content="老桶并入新事件CCC", importance=5)
    _set_meta(bucket_mgr, c,
              created=_iso(now - timedelta(days=10)),
              last_event_at=_iso(now - timedelta(days=2)))

    d = await bucket_mgr.create(content="批量导入的历史DDD", importance=5)
    _set_meta(bucket_mgr, d,
              created=_iso(now - timedelta(days=1)),
              last_event_at=_iso(now - timedelta(days=1)),
              imported=True)

    e = await bucket_mgr.create(content="时间戳在未来EEE", importance=5)
    _set_meta(bucket_mgr, e,
              created=_iso(now + timedelta(days=1)),
              last_event_at=_iso(now + timedelta(days=1)))

    result = await surface_default(max_results=10, max_tokens=10000, tag_filter=[])
    recency = _section(result, "近期原文")

    assert "昨天的新记忆AAA" in recency
    assert "老桶并入新事件CCC" in recency, "last_event_at 在窗口内的老桶应按事件时间进近期"
    assert "十天前的老记忆BBB" not in recency
    assert "批量导入的历史DDD" not in recency, "imported 桶不得冒充近期"
    assert "时间戳在未来EEE" not in recency, "未来时间戳不得霸榜"
    assert "🌱 [近期]" in recency

    # 未入近期的桶仍应从其他池出货，不是消失
    assert "十天前的老记忆BBB" in result
    assert "批量导入的历史DDD" in result


@pytest.mark.asyncio
async def test_recency_max_cap(bucket_mgr, decay_eng):
    """近期池上限 recency.max=4：只保最新 4 条，溢出的落回权重池。"""
    install_runtime(bucket_mgr, decay_eng, _layered_cfg())
    now = datetime.now()

    ids = []
    for i in range(6):
        bid = await bucket_mgr.create(content=f"近期记忆第{i}号", importance=5)
        ts = _iso(now - timedelta(hours=i + 1))  # 第0号最新
        _set_meta(bucket_mgr, bid, created=ts, last_event_at=ts)
        ids.append(bid)

    result = await surface_default(max_results=10, max_tokens=20000, tag_filter=[])
    recency = _section(result, "近期原文")

    for i in range(4):
        assert f"近期记忆第{i}号" in recency, f"最新4条应含第{i}号"
    for i in (4, 5):
        assert f"近期记忆第{i}号" not in recency, "第5、6新的不得进近期池"
        assert f"近期记忆第{i}号" in result, "溢出的应从权重池出货"


@pytest.mark.asyncio
async def test_recency_guaranteed_presence_degrades_to_index(bucket_mgr, decay_eng):
    """预算塞不下全文时，近期桶降级为索引行并明示未展开——绝不静默消失。"""
    install_runtime(bucket_mgr, decay_eng, _layered_cfg())
    now = datetime.now()

    # 索引行会合法携带正文前 40 字预览，所以全文哨兵放在尾部
    long_body = "近期长文桶XYZ。" + "中段填充" * 400 + "只有全文才有的结尾哨兵句"
    bid = await bucket_mgr.create(content=long_body, importance=5, title="近期长文桶")
    _set_meta(bucket_mgr, bid,
              created=_iso(now - timedelta(hours=2)),
              last_event_at=_iso(now - timedelta(hours=2)))

    result = await surface_default(max_results=10, max_tokens=200, tag_filter=[])

    assert "🌱 [近期·索引]" in result, "全文放不下必须降级索引行露面"
    assert "正文未展开" in result
    assert "breath_search" in result
    assert "只有全文才有的结尾哨兵句" not in result  # 确实没塞全文


# ------------------------------------------------------------
# 域劈分
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_tech_domain_split(bucket_mgr, decay_eng):
    """纯技术域索引化；混合域/importance≥9/默认域保留全文。"""
    install_runtime(bucket_mgr, decay_eng, _layered_cfg())
    now = datetime.now()
    old = _iso(now - timedelta(days=15))  # 全部放到近期窗口外，隔离变量

    t1 = await bucket_mgr.create(
        content="修了构建脚本的流水账", importance=5,
        domain=["编程"], title="构建脚本修理记",
    )
    t2 = await bucket_mgr.create(
        content="求签希望寓言酱留下混合域", importance=5,
        domain=["编程", "恋爱"],
    )
    t3 = await bucket_mgr.create(
        content="importance九分的技术里程碑", importance=9,
        domain=["工作"],
    )
    t4 = await bucket_mgr.create(content="没标域的日常记忆", importance=5)
    for bid in (t1, t2, t3, t4):
        _set_meta(bucket_mgr, bid, created=old, last_event_at=old)

    result = await surface_default(max_results=10, max_tokens=20000, tag_filter=[])
    tech = _section(result, "技术索引")
    warm = _section(result, "有体温的浮现")

    assert "构建脚本修理记" in tech
    assert "[domain:编程]" in tech
    assert "修了构建脚本的流水账" not in warm, "纯技术桶不得再占全文位"

    assert "求签希望寓言酱留下混合域" in warm, "混合域必须保留全文"
    assert "importance九分的技术里程碑" in warm, "importance>=9 豁免降级"
    assert "没标域的日常记忆" in warm, "默认域（未分类）按生活记忆处理"

    assert "breath_search" in tech, "索引段末尾应带调回全文的提示"


# ------------------------------------------------------------
# 去重与名额
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_duplicate_across_pools(bucket_mgr, decay_eng):
    """高重要度新桶（同时命中近期/冷启动/久未浮现条件）只出现一次。"""
    install_runtime(bucket_mgr, decay_eng, _layered_cfg())
    now = datetime.now()

    bid = await bucket_mgr.create(content="唯一露面一次的高分新桶", importance=9)
    _set_meta(bucket_mgr, bid,
              created=_iso(now - timedelta(hours=3)),
              last_event_at=_iso(now - timedelta(hours=3)),
              activation_count=0)

    result = await surface_default(max_results=10, max_tokens=20000, tag_filter=[])
    assert result.count("唯一露面一次的高分新桶") == 1


@pytest.mark.asyncio
async def test_weighted_limit_yields_seats_to_recency(bucket_mgr, decay_eng):
    """max_results=5、近期占4 → 权重池只发 1 个全文席位。"""
    install_runtime(bucket_mgr, decay_eng, _layered_cfg())
    now = datetime.now()

    for i in range(4):
        bid = await bucket_mgr.create(content=f"新席位{i}号记忆", importance=5)
        ts = _iso(now - timedelta(hours=i + 1))
        _set_meta(bucket_mgr, bid, created=ts, last_event_at=ts)

    old = _iso(now - timedelta(days=20))
    for i in range(3):
        bid = await bucket_mgr.create(content=f"老席位{i}号记忆", importance=5)
        _set_meta(bucket_mgr, bid, created=old, last_event_at=old)

    result = await surface_default(max_results=5, max_tokens=30000, tag_filter=[])
    warm = _section(result, "有体温的浮现")
    warm_count = sum(1 for i in range(3) if f"老席位{i}号记忆" in warm)
    assert warm_count == 1, f"权重池应只出 5-4=1 条，实际 {warm_count} 条"


# ------------------------------------------------------------
# last_event_at 真实落盘（官端 sol 判词：不能只检查 mock 收到了参数）
# ------------------------------------------------------------

def _norm_ts(v) -> str:
    """frontmatter 读回的时间可能是 datetime 或 str，归一化到秒级比较。"""
    return str(v).replace("T", " ")[:19]


class _SameEventJudge:
    async def judge_same_event(self, old, new):
        return {"same_event": True, "confidence": 1.0}

    async def merge(self, old, new):
        return old + "\n" + new

    async def dehydrate(self, content, meta=None):
        return content


@pytest.mark.asyncio
async def test_merge_refreshes_last_event_at_on_disk(bucket_mgr, decay_eng, monkeypatch):
    """旧桶并入新事件后，从 Markdown 重读，last_event_at 必须真实变化。"""
    import tools._common as common

    install_runtime(bucket_mgr, decay_eng)
    rt.dehydrator = _SameEventJudge()
    old_ts = _iso(datetime.now() - timedelta(days=30))

    bid = await bucket_mgr.create(
        content="祖传旧事的原始正文", importance=5, domain=["测试"]
    )
    _set_meta(bucket_mgr, bid,
              created=old_ts, last_active=old_ts, last_event_at=old_ts)

    async def fake_search(*a, **k):
        return [{"id": bid, "score": 99}]

    monkeypatch.setattr(bucket_mgr, "search", fake_search)

    _, merged, _ = await common.merge_or_create(
        content="同一事件后来发生的新细节", tags=[], importance=5,
        domain=["测试"], valence=0.5, arousal=0.3,
        raw_merge=True, source_tool="hold",
    )
    assert merged is True, "前置条件：必须真的走了合并分支"

    fresh = await bucket_mgr.get(bid)
    new_val = _norm_ts(fresh["metadata"].get("last_event_at"))
    assert new_val and new_val != _norm_ts(old_ts), (
        "合并新事件后 last_event_at 必须在盘上刷新——update 白名单漏了它就会静默丢失"
    )


@pytest.mark.asyncio
async def test_identical_resubmit_does_not_refresh_last_event_at(
    bucket_mgr, decay_eng, monkeypatch
):
    """幂等：一字不差的重复提交（网络重试）不得刷新 last_event_at。"""
    import tools._common as common

    install_runtime(bucket_mgr, decay_eng)
    rt.dehydrator = _SameEventJudge()
    old_ts = _iso(datetime.now() - timedelta(days=30))
    body = "一字不差的祖传正文"

    bid = await bucket_mgr.create(content=body, importance=5, domain=["测试"])
    _set_meta(bucket_mgr, bid,
              created=old_ts, last_active=old_ts, last_event_at=old_ts)

    async def fake_search(*a, **k):
        return [{"id": bid, "score": 99}]

    monkeypatch.setattr(bucket_mgr, "search", fake_search)

    await common.merge_or_create(
        content=body, tags=[], importance=5,
        domain=["测试"], valence=0.5, arousal=0.3,
        raw_merge=True, source_tool="hold",
    )

    fresh = await bucket_mgr.get(bid)
    assert _norm_ts(fresh["metadata"].get("last_event_at")) == _norm_ts(old_ts), (
        "内容未变的重复提交不得刷新——祖传旧事不能穿着新时间戳混进近期池"
    )


# ------------------------------------------------------------
# render_index_line
# ------------------------------------------------------------

def _mk_bucket(**meta):
    content = meta.pop("content", "正文第一句。正文第二句带换行。\n第二行内容")
    base = {
        "id": "abc123def456",
        "name": "2026-08-09 03-48-12 修路日记",
        "created": "2026-08-09T03:48:12",
        "domain": ["编程"],
    }
    base.update(meta)
    return {"id": base["id"], "content": content, "metadata": base}


def test_index_line_prefers_title_and_stays_single_line():
    bucket = _mk_bucket(title="修路之夜")
    rendered, tokens = render_index_line(bucket)
    assert "修路之夜" in rendered
    assert "\n" not in rendered, "索引行必须是单行"
    assert "[bucket_id:abc123def456]" in rendered
    assert "[domain:编程]" in rendered
    assert tokens > 0


def test_index_line_strips_timestamp_prefix_from_name():
    bucket = _mk_bucket()  # 无 title
    rendered, _ = render_index_line(bucket)
    assert "修路日记" in rendered
    assert "03-48-12 修路日记" not in rendered, "19 位时间前缀应被剥掉"


def test_index_line_uses_latest_nonempty_meaning():
    bucket = _mk_bucket(meaning=["旧的一条感受", "", "最新的一条感受"])
    rendered, _ = render_index_line(bucket)
    assert "最新的一条感受" in rendered
    assert "旧的一条感受" not in rendered


def test_index_line_keeps_stored_data_boundary():
    """预览仍是存储数据——缩写不解除防注入边界。"""
    bucket = _mk_bucket(title="边界检查")
    rendered, _ = render_index_line(bucket)
    assert "content_role" in rendered, "索引行必须保留 stored-data 安全标记"
