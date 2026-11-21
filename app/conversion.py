"""换算码表求解器：在单调不降约束下，为每个原分档从允许区间内选整数基准分。

业务规则：
- 基准分取 0 到 100 的整数；
- 同一原分统一换算（每个原分档只有一条记录，见服务层校验）；
- 原分越高，基准分也必须越高 —— 即按原分升序排列后基准分**单调不降**
  （允许相邻档并到同一基准分，这正是“并档”；码表把并档关系记录下来，
  数仓复核时按码表号做两向回查）。

优化目标：从各档区间（与 0-100 求交后）选值，使
    Σ 人数_i × |基准分_i − 建议分_i|
最小。

实现：基准分定义域只有 0..100 共 101 个整数值，按原分升序做动态规划：
    dp_i(v) = 人数_i × |v − 建议分_i| + min{ dp_{i-1}(u) | u ≤ v }
配合前缀最小值，复杂度 O(档数 × 101)。并列时取较小基准分，结果确定可复现。
"""

from __future__ import annotations

from dataclasses import dataclass

SCORE_MIN = 0
SCORE_MAX = 100
_DOMAIN = SCORE_MAX + 1  # 0..100

NEG_INF = float("-inf")


@dataclass
class TierSpec:
    """一个原分档的求解输入（按原分升序传入）。"""

    original_score: float
    suggested_score: float
    baseline_min: int
    baseline_max: int
    headcount: int


class InfeasibleError(Exception):
    """无可行解，消息中说明原因。"""


def _intersect_domain(tier: TierSpec) -> tuple[int, int]:
    """允许区间与基准分定义域 [0, 100] 求交。"""
    lo = max(tier.baseline_min, SCORE_MIN)
    hi = min(tier.baseline_max, SCORE_MAX)
    if lo > hi:
        raise InfeasibleError(
            f"原分 {tier.original_score} 的允许区间 [{tier.baseline_min}, {tier.baseline_max}] "
            f"与基准分定义域 {SCORE_MIN}-{SCORE_MAX} 没有交集，无整数可取"
        )
    return lo, hi


def solve(tiers: list[TierSpec]) -> tuple[list[int], float]:
    """求解基准分分配。

    tiers 必须按原分升序且无重复原分（服务层保证）。
    返回 (各档基准分, 最小加权绝对差总和)；无解抛 InfeasibleError。
    """
    if not tiers:
        raise InfeasibleError("码表没有任何原分档记录")

    bounds = [_intersect_domain(t) for t in tiers]

    # 前向可行性检查：reach 为到当前档为止可取的最小基准分。
    # 单调不降序列可行 ⇔ 每一档 max(区间下界, 前档最小可达) 不超过本档区间上界。
    reach = bounds[0][0]
    for i in range(1, len(tiers)):
        lo, hi = bounds[i]
        need = max(lo, reach)
        if need > hi:
            raise InfeasibleError(
                f"原分 {tiers[i].original_score} 的允许区间上界 {hi} "
                f"低于前一档（原分 {tiers[i - 1].original_score}）所需的最小基准分 {reach}："
                f"原分越高基准分也必须越高，两组区间无法同时满足"
            )
        reach = need

    n = len(tiers)
    # 第一档：代价即自身加权偏差
    prev = [NEG_INF] * _DOMAIN
    lo, hi = bounds[0]
    for v in range(lo, hi + 1):
        prev[v] = tiers[0].headcount * abs(v - tiers[0].suggested_score)

    # parents[i][v] = 第 i 档取 v 时，第 i-1 档的最优取值（回溯用）
    parents: list[list[int | None]] = [[None] * _DOMAIN for _ in range(n)]
    for i in range(1, n):
        # 前缀最小：best_u[v] = argmin_{u <= v} prev[u]，并列取较小 u
        best_u = [-1] * _DOMAIN
        run_min = NEG_INF
        run_u = -1
        for u in range(_DOMAIN):
            if prev[u] != NEG_INF and (run_u < 0 or prev[u] < run_min):
                run_min = prev[u]
                run_u = u
            best_u[u] = run_u
        cur = [NEG_INF] * _DOMAIN
        lo, hi = bounds[i]
        weight = tiers[i].headcount
        suggested = tiers[i].suggested_score
        for v in range(lo, hi + 1):
            u = best_u[v]
            if u < 0:
                continue
            cur[v] = weight * abs(v - suggested) + prev[u]
            parents[i][v] = u
        prev = cur

    # 终点：取目标值最小的基准分，并列取较小者
    best_v = -1
    best_val = NEG_INF
    for v in range(_DOMAIN):
        if prev[v] != NEG_INF and (best_v < 0 or prev[v] < best_val):
            best_val = prev[v]
            best_v = v
    if best_v < 0:  # 前向检查已拦截，此处兜底
        raise InfeasibleError("在“原分越高基准分也必须越高”的约束下无整数可行解")

    assignment = [0] * n
    v = best_v
    for i in range(n - 1, 0, -1):
        assignment[i] = v
        u = parents[i][v]
        assert u is not None
        v = u
    assignment[0] = v
    return assignment, best_val
