"""
========================================
tools/breath/surface.py — 无 query 浮现模式
========================================

走 breath()（不传 query）时进入这里，是 OB 主动「想到什么」的核心：
按权重从未解决桶里浮现 + pinned 桶置顶 + 加权采样 + 久未浮现的被动联想。

关键行为：
- 排除 anchor 桶（anchor 是坐标系，不主动出现）
- 排除 digested 桶（已消化记忆只允许显式检索/审计找回）
- 通过主动浮现策略的 pinned/protected 桶作为「核心准则」置顶（digested、dont_surface、anchor 优先隐藏；letter 桶也不置顶）
- 未解决桶按 calculate_score 排序；冷启动桶（从未访问且 importance>=8）插队前 2
- 配置开关 surfacing.sampling.enabled 启用后做加权无放回采样，否则
  保留 top1 + top20 内随机洗牌
- 末尾 1~2 条「久未浮现」passive association（imp>=8 且未访问 / imp>=9 且 7 天未活跃）

不做什么（边界）：
- 不调用 touch()：浮现不能重置衰减计时器
- 不返回 feel / plan / letter / archived（专用通道有自己的入口）
- 不做关键词检索（那是 search.py 的事）

对外暴露：surface_default(max_results, max_tokens, tag_filter) → str
========================================
"""

import random
import time
from datetime import datetime, timedelta

from ombrebrain.policy.surfacing import SurfacePolicyVM
from .. import _runtime as rt
from ..plan.core import is_letter_bucket
from utils import count_tokens_approx, parse_bool, parse_iso_datetime
from ._verbatim import render_index_line, render_stored_bucket

# U-07 fix: throttle the sampling-fallback INFO log to once per 5 minutes.
# 库小且 sampling=ON 时此分支每次 breath 都触发，原本会刷屏；改为 ≥300s
# 才打一次，并附带本窗口被压制的次数（首次为 0）。
_FALLBACK_LOG_INTERVAL_SEC = 300
_fallback_log_state = {"last_ts": 0.0, "suppressed": 0}
_SURFACE_POLICY = SurfacePolicyVM.default()
_BUDGET_NOTICE = (
    "token 预算不足：有 {omitted} 条主要浮现记忆因放不下剩余预算而未返回；"
    "已返回正文均保持完整，未截断或摘要。"
    "当前约使用 {used}/{limit} token，如需被省略的整桶请提高 max_tokens 后重试。"
)


def _bucket_has_tags(meta: dict, tag_filter: list) -> bool:
    if not tag_filter:
        return True
    bucket_tags = set(meta.get("tags", []) or [])
    return all(t in bucket_tags for t in tag_filter)


def _can_surface(bucket: dict) -> bool:
    return _SURFACE_POLICY.evaluate_bucket(bucket, mode="spontaneous").allowed


def _budget_notice(*, omitted: int, used: int, limit: int) -> str:
    return _BUDGET_NOTICE.format(omitted=omitted, used=used, limit=limit)


async def surface_default(max_results: int, max_tokens: int, tag_filter: list) -> str:
    # 分层浮现 v3 总开关：开启走独立新路径；关闭（默认）走下方旧路径。
    # 旧路径主体自 v3 起零改动——"关闭即旧行为"由结构保证，不靠测试锁随机数。
    _layered_cfg_probe = (rt.config.get("surfacing", {}) or {}).get(
        "layered_memory", {}
    ) or {}
    if parse_bool(_layered_cfg_probe.get("enabled", False), default=False):
        return await _surface_layered(max_results, max_tokens, tag_filter)

    try:
        all_buckets = await rt.bucket_mgr.list_all(include_archive=False)
    except Exception as e:
        rt.logger.error(f"Failed to list buckets for surfacing / 浮现列桶失败: {e}")
        return "记忆系统暂时无法访问。"

    surfacing_cfg = rt.config.get("surfacing", {}) or {}
    try:
        footprint_snapshot = rt.bucket_mgr.footprint_snapshot()
    except Exception as exc:
        rt.logger.warning(f"Footprint snapshot unavailable / 足迹读取失败: {exc}")
        footprint_snapshot = None

    def _footprint(bucket: dict) -> str:
        if footprint_snapshot is None:
            return "👣 Footprint：暂时无法读取"
        return footprint_snapshot.summary(
            str(bucket.get("id") or ""), bucket.get("metadata", {})
        )

    # --- pinned/protected 桶置顶（排除 letter 桶：letter 的 importance=10 不代表核心准则）---
    # pinned 与 anchor 在正常写入路径互斥：钉选会清除 anchor，设 anchor 会拒绝 pinned 桶。
    # 末尾的 anchor 排除是脏数据防御；若异常并存，仍按 anchor 语义不主动浮现。
    pinned_buckets = [
        b for b in all_buckets
        if (
            b["metadata"].get("pinned")
            or b["metadata"].get("protected")
            or b["metadata"].get("type") == "permanent"
        )
        and _can_surface(b)
        and not is_letter_bucket(b)
        and not b["metadata"].get("anchor", False)  # 防御：anchor 是坐标系，永不主动浮现，即使 pinned
    ]
    core_filter_notice = ""
    if tag_filter and pinned_buckets:
        core_filter_notice = "[说明：tags 仅过滤普通浮现记忆；核心准则按设计始终注入。]"
    pinned_ids = {b["id"] for b in pinned_buckets}
    pinned_results = []
    token_budget = max_tokens
    primary_omitted = 0
    for b in pinned_buckets:
        try:
            rendered, entry_tokens = render_stored_bucket(
                b,
                f"📌 [核心准则] [bucket_id:{b['id']}]",
                _footprint(b),
            )
            if entry_tokens > token_budget:
                primary_omitted += 1
                continue
            pinned_results.append(rendered)
            token_budget -= entry_tokens
        except Exception as e:
            rt.logger.warning(f"Failed to render pinned bucket / 钉选桶渲染失败: {e}")

    # --- iter 2.0: anchor 桶在默认浮现模式的 *未解决池* 不出现（anchor 是坐标系不是浮现对象）---
    # anchor 过滤仅作用于 unresolved 候选，不影响 pinned 提取（上方已完成）。
    all_buckets_non_anchor = [b for b in all_buckets if not b["metadata"].get("anchor", False)]

    # --- 未解决桶 ---
    unresolved = [
        b for b in all_buckets_non_anchor
        if _can_surface(b)
        and not b["metadata"].get("resolved", False)
        and not is_letter_bucket(b)
        and b["metadata"].get("type") not in ("permanent", "feel", "plan", "letter", "self", "i")
        and not b["metadata"].get("pinned", False)
        and not b["metadata"].get("protected", False)
        and not b["metadata"].get("dont_surface", False)
        and _bucket_has_tags(b["metadata"], tag_filter)
    ]

    rt.logger.info(
        f"Breath surfacing: {len(all_buckets)} total, "
        f"{len(pinned_buckets)} pinned, {len(unresolved)} unresolved"
    )


    def _sort_key(b: dict):
        """F-05: 二级排序 key，消除同分时浮现随机抖动。
        主键：decay_score（降序）
        次键：last_active 时间戳（越新越高）
        三键：arousal × valence（情感强度，越高越先浮现）
        四键：importance
        """
        meta = b["metadata"]
        score = rt.decay_engine.calculate_score(meta)
        try:
            last_ts = parse_iso_datetime(
                meta.get("last_active") or meta.get("created", "")
            ).timestamp()
        except (ValueError, TypeError):
            last_ts = 0.0
        # `or` 会把合法的 0.0（比如效价/唤醒度恰好为极端值的记忆）当成缺失值
        # 吞掉，静默换成默认值——用 .get(key, default) 才能保留 0.0 本身。
        try:
            av = float(meta.get("arousal", 0.3)) * float(meta.get("valence", 0.5))
        except (TypeError, ValueError):
            av = 0.3 * 0.5
        imp = int(meta.get("importance") or 5)
        return (score, last_ts, av, imp)

    scored = sorted(unresolved, key=_sort_key, reverse=True)

    if scored:
        top_scores = [(b["metadata"].get("name", b["id"]), rt.decay_engine.calculate_score(b["metadata"])) for b in scored[:5]]
        rt.logger.info(f"Top unresolved scores: {top_scores}")

    # --- 冷启动检测 ---
    cold_start = [
        b for b in unresolved
        if int(b["metadata"].get("activation_count") or 0) == 0
        and int(b["metadata"].get("importance") or 0) >= 8
    ][:2]
    cold_start_ids = {b["id"] for b in cold_start}
    _ = pinned_ids  # suppress unused-var warning; used implicitly for logging only
    scored_deduped = [b for b in scored if b["id"] not in cold_start_ids]
    scored_with_cold = cold_start + scored_deduped

    # --- 按 token 预算浮现，加权采样 / 随机洗牌 + 硬上限 ---
    candidates = list(scored_with_cold)
    sampling_cfg = surfacing_cfg.get("sampling", {}) or {}
    sampling_enabled = parse_bool(sampling_cfg.get("enabled", False), default=False)
    if sampling_enabled and len(candidates) > len(cold_start) + 1:
        n_cold = len(cold_start)
        non_cold = candidates[n_cold:]
        top_k = int(sampling_cfg.get("top_k") or 5)
        sample_k = int(sampling_cfg.get("sample_k") or 2)
        temperature = max(0.1, float(sampling_cfg.get("temperature") or 0.7))
        pool = non_cold[:max(top_k, sample_k)]
        try:
            weights = [
                max(0.0001, rt.decay_engine.calculate_score(b["metadata"])) ** (1.0 / temperature)
                for b in pool
            ]
            picked = []
            pool_copy = list(pool)
            weights_copy = list(weights)
            for _ in range(min(sample_k, len(pool_copy))):
                idx = random.choices(range(len(pool_copy)), weights=weights_copy, k=1)[0]
                picked.append(pool_copy.pop(idx))
                weights_copy.pop(idx)
            rest = pool_copy + non_cold[len(pool):]
            non_cold = picked + rest
            candidates = cold_start + non_cold
        except Exception as e:
            rt.logger.warning(f"Weighted sampling failed, fallback to original / 加权采样失败: {e}")
    elif len(candidates) > 1:
        if sampling_enabled:
            now_ts = time.monotonic()
            if now_ts - _fallback_log_state["last_ts"] >= _FALLBACK_LOG_INTERVAL_SEC:
                suppressed = _fallback_log_state["suppressed"]
                rt.logger.info(
                    f"weighted sampling fallback: candidates={len(candidates)}, "
                    f"cold_start={len(cold_start)}, sample_k={sampling_cfg.get('sample_k', 2)}, "
                    f"reason=pool_too_small, suppressed_in_window={suppressed}"
                )
                _fallback_log_state["last_ts"] = now_ts
                _fallback_log_state["suppressed"] = 0
            else:
                _fallback_log_state["suppressed"] += 1
        n_cold = len(cold_start)
        non_cold = candidates[n_cold:]
        if len(non_cold) > 1:
            top1 = [non_cold[0]]
            pool = non_cold[1:min(20, len(non_cold))]
            random.shuffle(pool)
            non_cold = top1 + pool + non_cold[min(20, len(non_cold)):]
        candidates = cold_start + non_cold
    candidates = candidates[:max_results]

    dynamic_results = []
    for b in candidates:
        try:
            score = rt.decay_engine.calculate_score(b["metadata"])
            rendered, entry_tokens = render_stored_bucket(
                b,
                f"[权重:{score:.2f}] [bucket_id:{b['id']}]",
                _footprint(b),
            )
            if entry_tokens > token_budget:
                primary_omitted += 1
                continue
            dynamic_results.append(rendered)
            token_budget -= entry_tokens
        except Exception as e:
            rt.logger.warning(f"Failed to render surfaced bucket / 浮现渲染失败: {e}")
            continue

    if not pinned_results and not dynamic_results:
        if primary_omitted:
            return _budget_notice(
                omitted=primary_omitted,
                used=max_tokens - token_budget,
                limit=max_tokens,
            )
        if rt.mark_op:
            rt.mark_op("breath_empty")
        stats = await rt.bucket_mgr.get_stats()
        total = stats.get("permanent_count", 0) + stats.get("dynamic_count", 0)
        if total == 0:
            return (
                "我的记忆池现在是空的。\n"
                "想给我留点种子？用 hold(content=\"...\") 写下第一条；\n"
                "或者 grow(content=\"...\") 把一段长对话/日记一次性灌给我。"
            )
        return (
            "权重池暂时平静——我手上没什么需要主动浮现的东西。\n"
            "可以试试 breath_search(query=\"想找的关键词\") 走检索，\n"
            "或者 dream() 让我自己挑几段最近的记忆嚼一嚼。"
        )

    # --- iter 1.6 §7: passive association ---
    passive_results: list[str] = []
    try:
        now = datetime.now()
        seven_days_ago = now - timedelta(days=7)
        already = {b["id"] for b in candidates}
        passive_pool = []
        for b in unresolved:
            if b["id"] in already:
                continue
            meta = b["metadata"]
            ac = int(meta.get("activation_count") or 0)
            imp = int(meta.get("importance") or 0)
            cond_a = ac == 0 and imp >= 8
            cond_b = False
            if imp >= 9:
                last = meta.get("last_active") or meta.get("created", "")
                try:
                    last_dt = parse_iso_datetime(last) if last else None
                    if last_dt and last_dt < seven_days_ago:
                        cond_b = True
                except Exception:
                    cond_b = False
            if cond_a or cond_b:
                passive_pool.append(b)
        if passive_pool and not primary_omitted:
            random.shuffle(passive_pool)
            for b in passive_pool[:2]:
                try:
                    rendered, entry_tokens = render_stored_bucket(
                        b,
                        f"💤 [久未浮现] [bucket_id:{b['id']}]",
                        _footprint(b),
                    )
                    if entry_tokens > token_budget:
                        continue
                    passive_results.append(rendered)
                    token_budget -= entry_tokens
                except Exception as e:
                    rt.logger.warning(f"passive association render failed: {e}")
    except Exception as e:
        rt.logger.warning(f"passive association block failed: {e}")

    # --- 3% 偶遇：从 resolved 池随机浮现 1~3 条沉底记忆 (iter 2.1) ---
    # 设计意图：让已解决的记忆有小概率重新出现，制造"忽然想起"的温度。
    # 与无结果兜底逻辑并存；不替换主流程。
    dream_results: list[str] = []
    if not primary_omitted and random.random() < 0.03:
        try:
            shown_ids = {b["id"] for b in candidates}
            resolved_pool = [
                b for b in all_buckets
                if _can_surface(b)
                and b["metadata"].get("resolved", False)
                and b["id"] not in shown_ids
                and not is_letter_bucket(b)
                and b["metadata"].get("type") not in ("feel", "plan", "letter")
                and not b["metadata"].get("pinned")
            ]
            if resolved_pool:
                random.shuffle(resolved_pool)
                for b in resolved_pool[:3]:
                    try:
                        rendered, entry_tokens = render_stored_bucket(
                            b,
                            f"✨ [偶遇] [bucket_id:{b['id']}]",
                            _footprint(b),
                        )
                        if entry_tokens > token_budget:
                            continue
                        dream_results.append(rendered)
                        token_budget -= entry_tokens
                        rt.logger.info(f"Dream surface triggered / 偶遇机制触发: {b['id']}")
                    except Exception as e:
                        rt.logger.warning(f"Dream surface render failed / 偶遇渲染失败: {e}")
        except Exception as e:
            rt.logger.warning(f"Dream surface block failed / 偶遇模块异常: {e}")

    parts = []
    if core_filter_notice:
        parts.append(core_filter_notice)
    if pinned_results:
        parts.append("=== 核心准则 ===\n" + "\n---\n".join(pinned_results))
    if dynamic_results:
        parts.append("=== 浮现记忆 ===\n" + "\n---\n".join(dynamic_results))
    if passive_results:
        parts.append("=== 久未浮现 ===\n" + "\n---\n".join(passive_results))
    if dream_results:
        parts.append("=== 偶然想起 ===\n" + "\n---\n".join(dream_results))
    if primary_omitted:
        parts.append(
            _budget_notice(
                omitted=primary_omitted,
                used=max_tokens - token_budget,
                limit=max_tokens,
            )
        )
    return "\n\n".join(parts)

# ============================================================
# 分层浮现 v3（layered_memory.enabled=true 时的独立路径）
# ------------------------------------------------------------
# 设计：docs/design-surfacing-quota.md（CLI sol + 官端 sol 双外审，库主终审）
# 六段输出：核心准则 / 近期原文 / 有体温的浮现 / 技术索引 / 久未浮现 / 偶然想起
#
# 与旧路径的关系：核心准则、unresolved 过滤、排序 key、采样/洗牌、久未浮现、
# 偶遇均为旧逻辑的镜像（刻意复制而非抽公共函数——旧函数体零改动是
# "总开关关闭=旧行为"的结构保证，DRY 在回归承诺面前让步）。
#
# 新增语义：
# - 近期原文池：last_event_at（回退 created）在 recency.days 内的最新
#   recency.max 条，无条件优先；预算不够时降级为索引行，保证"露面"，
#   绝不静默消失。imported 桶、非法/未来时间戳不入池。
# - 域劈分：tech_index.domains 全覆盖（且 importance < exempt）的桶进
#   技术索引池，单行渲染；混合域/无域/高重要度留在全文池。
# - 名额：全文池上限 = max_results - len(近期池)；技术索引独立上限。
# ============================================================


async def _surface_layered(max_results: int, max_tokens: int, tag_filter: list) -> str:
    try:
        all_buckets = await rt.bucket_mgr.list_all(include_archive=False)
    except Exception as e:
        rt.logger.error(f"Failed to list buckets for surfacing / 浮现列桶失败: {e}")
        return "记忆系统暂时无法访问。"

    surfacing_cfg = rt.config.get("surfacing", {}) or {}
    layered_cfg = surfacing_cfg.get("layered_memory", {}) or {}
    now = datetime.now()  # 入口捕获一次：所有时间边界判定用同一个 now，不漂移

    try:
        footprint_snapshot = rt.bucket_mgr.footprint_snapshot()
    except Exception as exc:
        rt.logger.warning(f"Footprint snapshot unavailable / 足迹读取失败: {exc}")
        footprint_snapshot = None

    def _footprint(bucket: dict) -> str:
        if footprint_snapshot is None:
            return "👣 Footprint：暂时无法读取"
        return footprint_snapshot.summary(
            str(bucket.get("id") or ""), bucket.get("metadata", {})
        )

    # --- 核心准则（镜像旧路径）---
    pinned_buckets = [
        b for b in all_buckets
        if (
            b["metadata"].get("pinned")
            or b["metadata"].get("protected")
            or b["metadata"].get("type") == "permanent"
        )
        and _can_surface(b)
        and not is_letter_bucket(b)
        and not b["metadata"].get("anchor", False)
    ]
    core_filter_notice = ""
    if tag_filter and pinned_buckets:
        core_filter_notice = "[说明：tags 仅过滤普通浮现记忆；核心准则按设计始终注入。]"
    pinned_results = []
    token_budget = max_tokens
    primary_omitted = 0
    for b in pinned_buckets:
        try:
            rendered, entry_tokens = render_stored_bucket(
                b,
                f"📌 [核心准则] [bucket_id:{b['id']}]",
                _footprint(b),
            )
            if entry_tokens > token_budget:
                primary_omitted += 1
                continue
            pinned_results.append(rendered)
            token_budget -= entry_tokens
        except Exception as e:
            rt.logger.warning(f"Failed to render pinned bucket / 钉选桶渲染失败: {e}")

    # --- unresolved 候选（镜像旧路径）---
    all_buckets_non_anchor = [b for b in all_buckets if not b["metadata"].get("anchor", False)]
    unresolved = [
        b for b in all_buckets_non_anchor
        if _can_surface(b)
        and not b["metadata"].get("resolved", False)
        and not is_letter_bucket(b)
        and b["metadata"].get("type") not in ("permanent", "feel", "plan", "letter", "self", "i")
        and not b["metadata"].get("pinned", False)
        and not b["metadata"].get("protected", False)
        and not b["metadata"].get("dont_surface", False)
        and _bucket_has_tags(b["metadata"], tag_filter)
    ]

    # --- 近期原文池（v3 新增）---
    rec_cfg = layered_cfg.get("recency", {}) or {}
    try:
        rec_days = float(rec_cfg.get("days") or 7)
    except (TypeError, ValueError):
        rec_days = 7.0
    try:
        rec_max = int(rec_cfg.get("max") or 4)
    except (TypeError, ValueError):
        rec_max = 4
    cutoff = now - timedelta(days=rec_days)

    def _event_dt(b: dict):
        meta = b["metadata"]
        raw = meta.get("last_event_at") or meta.get("created") or ""
        try:
            return parse_iso_datetime(raw)
        except (ValueError, TypeError):
            return None

    recency_scored = []
    for b in unresolved:
        if parse_bool(b["metadata"].get("imported"), default=False):
            continue  # 批量导入桶的时间是导入时刻，不冒充近期
        if "digest" in (b["metadata"].get("tags") or []):
            continue  # 摘要桶不占近期原文席位，另有印象席
        dt = _event_dt(b)
        if dt is None or dt > now:
            continue  # 非法时间只排除该桶；未来时间不得霸榜
        if dt >= cutoff:
            recency_scored.append((dt, str(b.get("id") or ""), b))
    recency_scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    recency_selected = [
        t[2] for t in recency_scored[: max(0, min(rec_max, max_results))]
    ]
    recency_ids = {b["id"] for b in recency_selected}

    recency_results = []
    for b in recency_selected:
        try:
            rendered, entry_tokens = render_stored_bucket(
                b, f"🌱 [近期] [bucket_id:{b['id']}]", _footprint(b)
            )
            if entry_tokens > token_budget:
                # 保证露面：全文放不下降级为索引行 + 明示未展开，绝不静默消失
                note = (
                    f'[正文未展开：预算不足，'
                    f'详情 breath_search(query="{b["id"]}")]'
                )
                rendered, entry_tokens = render_index_line(
                    b, label="近期·索引", emoji="🌱", note=note
                )
                if entry_tokens > token_budget:
                    primary_omitted += 1
                    continue
            recency_results.append(rendered)
            token_budget -= entry_tokens
        except Exception as e:
            rt.logger.warning(f"recency render failed / 近期渲染失败: {e}")

    # --- 印象席（巩固仪式配套）: 最新一篇摘要常驻 1 席 ---
    # 排序按 pend_YYYYMMDD 标签（周期终点）而非 created：
    # 后补的旧周摘不得篡位最新印象（外审验收①）。
    # 无 pend_ 标签的 digest 桶不入席（仍走权重池）。
    def _pend_key(b: dict) -> str:
        for t in (b["metadata"].get("tags") or []):
            if isinstance(t, str) and t.startswith("pend_") and t[5:].isdigit():
                return t[5:]
        return ""

    impression_results = []
    impression_ids: set = set()
    digest_pool = [
        b for b in unresolved
        if "digest" in (b["metadata"].get("tags") or [])
        and _pend_key(b)
        and b["id"] not in recency_ids
    ]
    if digest_pool:
        digest_pool.sort(
            key=lambda b: (_pend_key(b), str(b.get("id") or "")), reverse=True
        )
        top = digest_pool[0]
        try:
            rendered, entry_tokens = render_stored_bucket(
                top, f"📖 [印象] [bucket_id:{top['id']}]", _footprint(top)
            )
            if entry_tokens <= token_budget:
                impression_results.append(rendered)
                impression_ids.add(top["id"])
                token_budget -= entry_tokens
            else:
                primary_omitted += 1
        except Exception as e:
            rt.logger.warning(f"impression render failed / 印象渲染失败: {e}")

    # --- 域劈分（v3 新增）---
    tech_cfg = layered_cfg.get("tech_index", {}) or {}
    tech_enabled = parse_bool(tech_cfg.get("enabled", False), default=False)
    tech_domains = set(
        s for s in (
            str(x).strip() for x in (tech_cfg.get("domains") or ["编程", "工作"])
        ) if s
    )
    try:
        tech_max = int(tech_cfg.get("max") or 8)
    except (TypeError, ValueError):
        tech_max = 8
    try:
        tech_exempt = int(tech_cfg.get("importance_exempt") or 9)
    except (TypeError, ValueError):
        tech_exempt = 9

    def _domains_of(meta: dict) -> list:
        d = meta.get("domain")
        if isinstance(d, str):
            return [d.strip()] if d.strip() else []
        if isinstance(d, list):
            return [s for s in (str(x).strip() for x in d) if s]
        return []

    def _is_tech_only(b: dict) -> bool:
        meta = b["metadata"]
        doms = _domains_of(meta)
        if not doms:
            return False  # 无域按生活记忆处理，保留全文
        try:
            imp = int(meta.get("importance") or 5)
        except (TypeError, ValueError):
            imp = 5
        if imp >= tech_exempt:
            return False  # 高重要度技术记忆豁免降级
        return all(x in tech_domains for x in doms)  # 混合域保护：全属才降级

    rest = [
        b for b in unresolved
        if b["id"] not in recency_ids and b["id"] not in impression_ids
    ]
    if tech_enabled and tech_domains:
        tech_pool = [b for b in rest if _is_tech_only(b)]
        tech_pool_ids = {b["id"] for b in tech_pool}
        warm_pool = [b for b in rest if b["id"] not in tech_pool_ids]
    else:
        tech_pool = []
        warm_pool = rest

    rt.logger.info(
        f"Layered surfacing: {len(all_buckets)} total, {len(pinned_buckets)} pinned, "
        f"{len(recency_selected)} recency, {len(warm_pool)} warm, {len(tech_pool)} tech"
    )

    # --- 有体温的浮现：旧赛马制镜像，跑在 warm_pool 上 ---
    def _sort_key(b: dict):
        meta = b["metadata"]
        score = rt.decay_engine.calculate_score(meta)
        try:
            last_ts = parse_iso_datetime(
                meta.get("last_active") or meta.get("created", "")
            ).timestamp()
        except (ValueError, TypeError):
            last_ts = 0.0
        try:
            av = float(meta.get("arousal", 0.3)) * float(meta.get("valence", 0.5))
        except (TypeError, ValueError):
            av = 0.3 * 0.5
        imp = int(meta.get("importance") or 5)
        return (score, last_ts, av, imp)

    scored = sorted(warm_pool, key=_sort_key, reverse=True)

    cold_start = [
        b for b in warm_pool
        if int(b["metadata"].get("activation_count") or 0) == 0
        and int(b["metadata"].get("importance") or 0) >= 8
    ][:2]
    cold_start_ids = {b["id"] for b in cold_start}
    scored_deduped = [b for b in scored if b["id"] not in cold_start_ids]
    scored_with_cold = cold_start + scored_deduped

    candidates = list(scored_with_cold)
    sampling_cfg = surfacing_cfg.get("sampling", {}) or {}
    sampling_enabled = parse_bool(sampling_cfg.get("enabled", False), default=False)
    if sampling_enabled and len(candidates) > len(cold_start) + 1:
        n_cold = len(cold_start)
        non_cold = candidates[n_cold:]
        top_k = int(sampling_cfg.get("top_k") or 5)
        sample_k = int(sampling_cfg.get("sample_k") or 2)
        temperature = max(0.1, float(sampling_cfg.get("temperature") or 0.7))
        pool = non_cold[:max(top_k, sample_k)]
        try:
            weights = [
                max(0.0001, rt.decay_engine.calculate_score(b["metadata"])) ** (1.0 / temperature)
                for b in pool
            ]
            picked = []
            pool_copy = list(pool)
            weights_copy = list(weights)
            for _ in range(min(sample_k, len(pool_copy))):
                idx = random.choices(range(len(pool_copy)), weights=weights_copy, k=1)[0]
                picked.append(pool_copy.pop(idx))
                weights_copy.pop(idx)
            rest_tail = pool_copy + non_cold[len(pool):]
            non_cold = picked + rest_tail
            candidates = cold_start + non_cold
        except Exception as e:
            rt.logger.warning(f"Weighted sampling failed, fallback to original / 加权采样失败: {e}")
    elif len(candidates) > 1:
        n_cold = len(cold_start)
        non_cold = candidates[n_cold:]
        if len(non_cold) > 1:
            top1 = [non_cold[0]]
            pool = non_cold[1:min(20, len(non_cold))]
            random.shuffle(pool)
            non_cold = top1 + pool + non_cold[min(20, len(non_cold)):]
        candidates = cold_start + non_cold
    weighted_limit = max(0, max_results - len(recency_selected))
    candidates = candidates[:weighted_limit]

    dynamic_results = []
    for b in candidates:
        try:
            score = rt.decay_engine.calculate_score(b["metadata"])
            rendered, entry_tokens = render_stored_bucket(
                b,
                f"[权重:{score:.2f}] [bucket_id:{b['id']}]",
                _footprint(b),
            )
            if entry_tokens > token_budget:
                primary_omitted += 1
                continue
            dynamic_results.append(rendered)
            token_budget -= entry_tokens
        except Exception as e:
            rt.logger.warning(f"Failed to render surfaced bucket / 浮现渲染失败: {e}")
            continue

    # --- 技术索引段（v3 新增）---
    tech_results = []
    tech_shown_ids: set = set()
    if tech_pool:
        tech_sorted = sorted(tech_pool, key=_sort_key, reverse=True)[:max(0, tech_max)]
        for b in tech_sorted:
            try:
                rendered, entry_tokens = render_index_line(b)
                if entry_tokens > token_budget:
                    primary_omitted += 1
                    continue
                tech_results.append(rendered)
                tech_shown_ids.add(b["id"])
                token_budget -= entry_tokens
            except Exception as e:
                rt.logger.warning(f"tech index render failed / 技术索引渲染失败: {e}")
        if tech_results:
            hint = '（索引条目详情：breath_search(query="<bucket_id>") 逐字调回全文）'
            hint_tokens = count_tokens_approx(hint)
            if hint_tokens <= token_budget:
                tech_results.append(hint)
                token_budget -= hint_tokens

    # --- 空结果判断（纳入全部新池）---
    if (
        not pinned_results
        and not recency_results
        and not impression_results
        and not dynamic_results
        and not tech_results
    ):
        if primary_omitted:
            return _budget_notice(
                omitted=primary_omitted,
                used=max_tokens - token_budget,
                limit=max_tokens,
            )
        if rt.mark_op:
            rt.mark_op("breath_empty")
        stats = await rt.bucket_mgr.get_stats()
        total = stats.get("permanent_count", 0) + stats.get("dynamic_count", 0)
        if total == 0:
            return (
                "我的记忆池现在是空的。\n"
                "想给我留点种子？用 hold(content=\"...\") 写下第一条；\n"
                "或者 grow(content=\"...\") 把一段长对话/日记一次性灌给我。"
            )
        return (
            "权重池暂时平静——我手上没什么需要主动浮现的东西。\n"
            "可以试试 breath_search(query=\"想找的关键词\") 走检索，\n"
            "或者 dream() 让我自己挑几段最近的记忆嚼一嚼。"
        )

    # --- 久未浮现（镜像旧路径；already 含近期/全文/技术全部已展示）---
    passive_results: list[str] = []
    try:
        seven_days_ago = now - timedelta(days=7)
        already = (
            recency_ids
            | impression_ids
            | {b["id"] for b in candidates}
            | tech_shown_ids
        )
        passive_pool = []
        for b in unresolved:
            if b["id"] in already:
                continue
            meta = b["metadata"]
            ac = int(meta.get("activation_count") or 0)
            imp = int(meta.get("importance") or 0)
            cond_a = ac == 0 and imp >= 8
            cond_b = False
            if imp >= 9:
                last = meta.get("last_active") or meta.get("created", "")
                try:
                    last_dt = parse_iso_datetime(last) if last else None
                    if last_dt and last_dt < seven_days_ago:
                        cond_b = True
                except Exception:
                    cond_b = False
            if cond_a or cond_b:
                passive_pool.append(b)
        if passive_pool and not primary_omitted:
            random.shuffle(passive_pool)
            for b in passive_pool[:2]:
                try:
                    rendered, entry_tokens = render_stored_bucket(
                        b,
                        f"💤 [久未浮现] [bucket_id:{b['id']}]",
                        _footprint(b),
                    )
                    if entry_tokens > token_budget:
                        continue
                    passive_results.append(rendered)
                    token_budget -= entry_tokens
                except Exception as e:
                    rt.logger.warning(f"passive association render failed: {e}")
    except Exception as e:
        rt.logger.warning(f"passive association block failed: {e}")

    # --- 3% 偶遇（镜像旧路径；shown 扩展为全部已展示）---
    dream_results: list[str] = []
    if not primary_omitted and random.random() < 0.03:
        try:
            shown_ids = (
                recency_ids
                | impression_ids
                | {b["id"] for b in candidates}
                | tech_shown_ids
            )
            resolved_pool = [
                b for b in all_buckets
                if _can_surface(b)
                and b["metadata"].get("resolved", False)
                and b["id"] not in shown_ids
                and not is_letter_bucket(b)
                and b["metadata"].get("type") not in ("feel", "plan", "letter")
                and not b["metadata"].get("pinned")
            ]
            if resolved_pool:
                random.shuffle(resolved_pool)
                for b in resolved_pool[:3]:
                    try:
                        rendered, entry_tokens = render_stored_bucket(
                            b,
                            f"✨ [偶遇] [bucket_id:{b['id']}]",
                            _footprint(b),
                        )
                        if entry_tokens > token_budget:
                            continue
                        dream_results.append(rendered)
                        token_budget -= entry_tokens
                        rt.logger.info(f"Dream surface triggered / 偶遇机制触发: {b['id']}")
                    except Exception as e:
                        rt.logger.warning(f"Dream surface render failed / 偶遇渲染失败: {e}")
        except Exception as e:
            rt.logger.warning(f"Dream surface block failed / 偶遇模块异常: {e}")

    # --- 六段组装 ---
    parts = []
    if core_filter_notice:
        parts.append(core_filter_notice)
    if pinned_results:
        parts.append("=== 核心准则 ===\n" + "\n---\n".join(pinned_results))
    if recency_results:
        parts.append("=== 近期原文 ===\n" + "\n---\n".join(recency_results))
    if impression_results:
        parts.append("=== 印象 ===\n" + "\n---\n".join(impression_results))
    if dynamic_results:
        parts.append("=== 有体温的浮现 ===\n" + "\n---\n".join(dynamic_results))
    if tech_results:
        parts.append("=== 技术索引 ===\n" + "\n".join(tech_results))
    if passive_results:
        parts.append("=== 久未浮现 ===\n" + "\n---\n".join(passive_results))
    if dream_results:
        parts.append("=== 偶然想起 ===\n" + "\n---\n".join(dream_results))
    if primary_omitted:
        parts.append(
            _budget_notice(
                omitted=primary_omitted,
                used=max_tokens - token_budget,
                limit=max_tokens,
            )
        )
    return "\n\n".join(parts)
