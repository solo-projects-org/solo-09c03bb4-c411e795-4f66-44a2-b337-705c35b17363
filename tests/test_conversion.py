"""换算码表：求解器单元测试（含暴力对拍）与 API 场景测试。"""

from __future__ import annotations

import importlib
import itertools
import random

import pytest

from app.conversion import InfeasibleError, TierSpec, solve


def _tier(suggested, lo, hi, headcount, original=0.0):
    return TierSpec(original_score=original, suggested_score=suggested,
                    baseline_min=lo, baseline_max=hi, headcount=headcount)


# ---------- 求解器单元测试 ----------


def test_solver_basic_zero_deviation():
    tiers = [_tier(46.5, 40, 52, 120), _tier(53.5, 48, 58, 200)]
    assignment, obj = solve(tiers)
    assert assignment == [46, 53]  # 46/47 并列取较小者
    assert obj == pytest.approx(120 * 0.5 + 200 * 0.5)


def test_solver_forced_merge_into_same_tier():
    """三档建议分接近，最优解并到同一基准分（并档）。"""
    tiers = [_tier(58.6, 55, 60, 300), _tier(59.1, 56, 61, 250), _tier(59.4, 57, 62, 100)]
    assignment, obj = solve(tiers)
    assert assignment == [59, 59, 59]
    assert obj == pytest.approx(300 * 0.4 + 250 * 0.1 + 100 * 0.4)


def test_solver_forced_merge_by_narrow_interval():
    """区间只剩一个值，不同原分被迫并档。"""
    tiers = [_tier(95, 90, 90, 10), _tier(10, 90, 90, 5)]
    assignment, obj = solve(tiers)
    assert assignment == [90, 90]
    assert obj == pytest.approx(10 * 5 + 5 * 80)


def test_solver_weighted_choice_follows_majority():
    tiers = [_tier(80, 0, 100, 1), _tier(90, 0, 100, 100)]
    assignment, obj = solve(tiers)
    assert assignment == [80, 90]
    assert obj == pytest.approx(0)


def test_solver_monotone_chain_propagates():
    """前档区间抬高后档下界：单调不降约束沿链传递。"""
    tiers = [_tier(50, 50, 60, 10), _tier(10, 0, 100, 10), _tier(10, 0, 100, 10)]
    assignment, _ = solve(tiers)
    assert assignment[0] == 50
    assert assignment == sorted(assignment)
    assert all(v >= 50 for v in assignment)


def test_solver_infeasible_interval_outside_domain():
    tiers = [_tier(50, 105, 120, 1)]
    with pytest.raises(InfeasibleError, match="0-100|没有交集"):
        solve(tiers)


def test_solver_infeasible_monotonic_conflict():
    tiers = [_tier(90, 90, 100, 1, original=60), _tier(10, 0, 50, 1, original=70)]
    with pytest.raises(InfeasibleError, match="原分 70"):
        solve(tiers)


def test_solver_tie_break_picks_smaller_baseline():
    tiers = [_tier(50.5, 0, 100, 2), _tier(60.5, 0, 100, 2)]
    assignment, obj = solve(tiers)
    assert assignment == [50, 60]
    assert obj == pytest.approx(2 * 0.5 + 2 * 0.5)


def test_solver_zero_headcount_still_constrained():
    """人数为 0 的档不影响目标，但仍受单调约束。"""
    tiers = [_tier(90, 90, 90, 5), _tier(0, 0, 100, 0)]
    assignment, obj = solve(tiers)
    assert assignment[0] == 90 and assignment[1] >= 90
    assert obj == pytest.approx(0)


def _brute_force(tiers):
    bounds = [(max(t.baseline_min, 0), min(t.baseline_max, 100)) for t in tiers]
    if any(lo > hi for lo, hi in bounds):
        return None
    best = None
    for combo in itertools.product(*(range(lo, hi + 1) for lo, hi in bounds)):
        if any(combo[i + 1] < combo[i] for i in range(len(combo) - 1)):
            continue
        cost = sum(t.headcount * abs(v - t.suggested_score) for t, v in zip(tiers, combo))
        if best is None or cost < best:
            best = cost
    return best


def test_solver_matches_brute_force_randomized():
    """随机小案例与暴力枚举对拍：目标值一致、解合法且单调不降。"""
    rng = random.Random(20261121)
    for _ in range(300):
        n = rng.randint(1, 4)
        tiers = []
        for _ in range(n):
            lo = rng.randint(-5, 100)
            hi = lo + rng.randint(0, 8)
            tiers.append(_tier(rng.randint(0, 100), lo, hi, rng.randint(0, 50)))
        try:
            assignment, obj = solve(tiers)
        except InfeasibleError:
            assert _brute_force(tiers) is None
            continue
        best = _brute_force(tiers)
        assert best is not None
        assert obj == pytest.approx(best)
        for t, v in zip(tiers, assignment):
            assert max(t.baseline_min, 0) <= v <= min(t.baseline_max, 100)
            assert isinstance(v, int)
        assert all(assignment[i + 1] >= assignment[i] for i in range(n - 1))


# ---------- API 场景测试 ----------


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("QUAL_DB_PATH", str(tmp_path / "test.db"))
    import app.main as main
    importlib.reload(main)  # 每个测试函数一个全新的库
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


def _reg(no, a, b):
    return {"action": "register", "report_no": no, "paper_a": a, "paper_b": b}


def _wd(no):
    return {"action": "withdraw", "report_no": no}


def _seed_chain(client):
    """版本 1：基准卷 BASE，报告链 SRC --R1-- MID --R2-- BASE。"""
    resp = client.post("/batches", json={
        "batch_no": "B1", "baselines": ["BASE"],
        "operations": [_reg("R1", "SRC", "MID"), _reg("R2", "MID", "BASE")]})
    assert resp.status_code == 200, resp.text


def _merge_records():
    """三档最优解并到基准分 59（并档场景）。"""
    return [
        {"original_score": 88, "suggested_score": 58.6,
         "baseline_min": 55, "baseline_max": 60, "headcount": 300},
        {"original_score": 89, "suggested_score": 59.1,
         "baseline_min": 56, "baseline_max": 61, "headcount": 250},
        {"original_score": 90, "suggested_score": 59.4,
         "baseline_min": 57, "baseline_max": 62, "headcount": 100},
    ]


def _table_payload(table_no="CT-1", version_used=1, report_nos=("R1", "R2"), records=None):
    return {
        "table_no": table_no,
        "source_paper": "SRC",
        "baseline_paper": "BASE",
        "version_used": version_used,
        "report_nos": list(report_nos),
        "records": records if records is not None else _merge_records(),
    }


def _publish(client, payload, expected=200):
    resp = client.post("/conversion-tables", json=payload)
    assert resp.status_code == expected, resp.text
    return resp.json()


# 场景 1：发布 + 并档 + 两向映射

def test_publish_merge_and_bidirectional_query(client):
    _seed_chain(client)
    body = _publish(client, _table_payload())

    assert body["replayed"] is False
    assert body["version_used"] == 1 and body["version_current"] == 1
    assert body["report_nos"] == ["R1", "R2"]
    assigned = [r["baseline_score"] for r in body["records"]]
    assert assigned == [59, 59, 59]  # 并档：三个原分档并入同一基准分
    assert body["objective"] == pytest.approx(300 * 0.4 + 250 * 0.1 + 100 * 0.4)

    # 正向映射：原分 -> 基准分
    assert body["forward_mapping"] == [
        {"original_score": 88, "baseline_score": 59},
        {"original_score": 89, "baseline_score": 59},
        {"original_score": 90, "baseline_score": 59},
    ]
    # 反向映射：基准分 59 并了三档，复核时可找回原分
    assert body["reverse_mapping"] == [
        {"baseline_score": 59, "original_scores": [88, 89, 90], "headcount": 650},
    ]

    # 按码表号回查两向映射
    got = client.get("/conversion-tables/CT-1").json()
    assert got["replayed"] is False and got["reverse_mapping"][0]["original_scores"] == [88, 89, 90]

    fwd = client.get("/conversion-tables/CT-1/forward/89").json()
    assert fwd == {"table_no": "CT-1", "original_score": 89, "baseline_score": 59}
    rev = client.get("/conversion-tables/CT-1/reverse/59").json()
    assert rev["original_scores"] == [88, 89, 90] and rev["headcount"] == 650

    assert client.get("/conversion-tables/CT-1/forward/55").status_code == 404
    assert client.get("/conversion-tables/CT-1/reverse/60").status_code == 404
    assert client.get("/conversion-tables/NOPE").status_code == 404

    tables = client.get("/conversion-tables").json()
    assert [t["table_no"] for t in tables] == ["CT-1"]


# 场景 2：同号原样重送取原码表，同号异文拒收

def test_replay_returns_original_and_conflict_rejected(client):
    _seed_chain(client)
    first = _publish(client, _table_payload())

    replay = _publish(client, _table_payload())
    assert replay["replayed"] is True
    assert replay["created_at"] == first["created_at"]
    assert replay["records"] == first["records"]

    changed = _table_payload()
    changed["records"] = _merge_records()[:2]  # 同号异文
    resp = client.post("/conversion-tables", json=changed)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "table_conflict"
    # 拒收不产生新码表，原码表不变
    assert len(client.get("/conversion-tables").json()) == 1
    assert len(client.get("/conversion-tables/CT-1").json()["records"]) == 3


# 场景 3：链中报告先撤回 -> 不产生新码表；已发布码表仍可回查

def test_withdrawn_chain_report_blocks_publish_but_keeps_old_table(client):
    _seed_chain(client)
    _publish(client, _table_payload("CT-OLD"))

    # 版本 2：撤回链上报告 R2
    resp = client.post("/batches", json={"batch_no": "B2", "operations": [_wd("R2")]})
    assert resp.status_code == 200

    # 用所用版 1 发布：R2 在当前版已撤回 -> 拒收
    resp = client.post("/conversion-tables", json=_table_payload("CT-NEW", version_used=1))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "report_not_active"
    # 用当前版 2 发布：R2 在所用版同样已撤回 -> 拒收
    resp = client.post("/conversion-tables", json=_table_payload("CT-NEW2", version_used=2))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "report_not_active"

    # 不产生新码表
    assert client.get("/conversion-tables/CT-NEW").status_code == 404
    assert client.get("/conversion-tables/CT-NEW2").status_code == 404
    assert [t["table_no"] for t in client.get("/conversion-tables").json()] == ["CT-OLD"]

    # 依据撤回后，已发布码表的两向映射仍可回查
    old = client.get("/conversion-tables/CT-OLD").json()
    assert old["forward_mapping"][0]["baseline_score"] == 59
    assert client.get("/conversion-tables/CT-OLD/reverse/59").json()["original_scores"] == [88, 89, 90]


def test_report_not_yet_registered_in_used_version(client):
    _seed_chain(client)
    # 版本 2 才登记 R3（MID-BASE 平行报告）
    resp = client.post("/batches", json={"batch_no": "B2", "operations": [_reg("R3", "MID", "BASE")]})
    assert resp.status_code == 200
    # 所用版 1 中 R3 尚未登记 -> 拒收
    resp = client.post("/conversion-tables",
                       json=_table_payload("CT-X", version_used=1, report_nos=("R1", "R3")))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "report_not_active"
    assert client.get("/conversion-tables/CT-X").status_code == 404
    # 所用版 2 中链有效 -> 发布成功
    body = _publish(client, _table_payload("CT-X", version_used=2, report_nos=("R1", "R3")))
    assert body["version_current"] == 2


# 场景 4：基准卷须为两版共同基准卷

def test_baseline_must_be_common_to_both_versions(client):
    _seed_chain(client)
    # 版本 2：基准卷全集换成 BASE2
    resp = client.post("/batches", json={
        "batch_no": "B2", "baselines": ["BASE2"],
        "operations": [_reg("R9", "BASE2", "W")]})
    assert resp.status_code == 200

    # BASE 只是所用版 1 的基准卷，当前版已不是 -> 拒收
    resp = client.post("/conversion-tables", json=_table_payload("CT-B1", version_used=1))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "baseline_not_common"

    # BASE2 只是当前版基准卷，所用版 1 不是 -> 拒收
    payload = _table_payload("CT-B2", version_used=1)
    payload["baseline_paper"] = "BASE2"
    resp = client.post("/conversion-tables", json=payload)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "baseline_not_common"
    assert client.get("/conversion-tables/CT-B1").status_code == 404


# 场景 5：报告链必须从来源卷接到基准卷

def test_chain_must_connect_source_to_baseline(client):
    _seed_chain(client)
    # 顺序填反：R2（MID-BASE）不与来源卷 SRC 相接
    resp = client.post("/conversion-tables",
                       json=_table_payload("CT-C1", report_nos=("R2", "R1")))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "chain_broken"

    # 链太短：终点是 MID 而非基准卷
    resp = client.post("/conversion-tables", json=_table_payload("CT-C2", report_nos=("R1",)))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "chain_not_reaching_baseline"

    # 不存在的报告单号
    resp = client.post("/conversion-tables",
                       json=_table_payload("CT-C3", report_nos=("R1", "R-X")))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "report_not_found"

    # 重复单号 / 来源卷等于基准卷
    resp = client.post("/conversion-tables",
                       json=_table_payload("CT-C4", report_nos=("R1", "R1")))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "duplicate_report_in_chain"
    payload = _table_payload("CT-C5")
    payload["baseline_paper"] = "SRC"
    resp = client.post("/conversion-tables", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "same_paper"

    assert client.get("/conversion-tables").json() == []


def test_version_used_must_exist(client):
    _seed_chain(client)
    resp = client.post("/conversion-tables", json=_table_payload("CT-V", version_used=99))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "version_not_found"


# 场景 6：记录校验与无解说明

def test_duplicate_original_rejected(client):
    _seed_chain(client)
    records = _merge_records()
    records.append(dict(records[0]))  # 重复原分 88
    resp = client.post("/conversion-tables", json=_table_payload("CT-D", records=records))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "duplicate_original"


def test_infeasible_explains_reason_and_creates_nothing(client):
    _seed_chain(client)
    # 单调冲突：高原分档区间整体低于低原分档
    records = [
        {"original_score": 60, "suggested_score": 95,
         "baseline_min": 90, "baseline_max": 100, "headcount": 10},
        {"original_score": 70, "suggested_score": 5,
         "baseline_min": 0, "baseline_max": 50, "headcount": 10},
    ]
    resp = client.post("/conversion-tables", json=_table_payload("CT-F1", records=records))
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "infeasible"
    assert "原分 70" in err["message"] and "90" in err["message"]

    # 区间完全落在 0-100 之外
    records = [{"original_score": 60, "suggested_score": 130,
                "baseline_min": 105, "baseline_max": 120, "headcount": 3}]
    resp = client.post("/conversion-tables", json=_table_payload("CT-F2", records=records))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "infeasible"
    assert "0-100" in resp.json()["error"]["message"]

    # 无解不产生新码表
    assert client.get("/conversion-tables/CT-F1").status_code == 404
    assert client.get("/conversion-tables").json() == []


def test_record_field_validation(client):
    _seed_chain(client)
    base = _table_payload("CT-G")
    bad = dict(base, records=[])  # 空记录
    assert client.post("/conversion-tables", json=bad).status_code == 422
    bad = dict(base, records=[{"original_score": 1, "suggested_score": 1,
                               "baseline_min": 60, "baseline_max": 50, "headcount": 1}])
    assert client.post("/conversion-tables", json=bad).status_code == 422
    bad = dict(base, records=[{"original_score": 1, "suggested_score": 1,
                               "baseline_min": 0, "baseline_max": 50, "headcount": -1}])
    assert client.post("/conversion-tables", json=bad).status_code == 422
    bad = dict(base, report_nos=[])
    assert client.post("/conversion-tables", json=bad).status_code == 422


# 场景 7：服务重启后仍可按码表号回查

def test_table_survives_restart(monkeypatch, tmp_path):
    db_path = tmp_path / "restart.db"
    monkeypatch.setenv("QUAL_DB_PATH", str(db_path))
    import app.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c1:
        _seed_chain(c1)
        body = _publish(c1, _table_payload("CT-KEEP"))
        assert body["replayed"] is False
        # 撤回链上报告：码表依据失效
        resp = c1.post("/batches", json={"batch_no": "B2", "operations": [_wd("R2")]})
        assert resp.status_code == 200

    # 模拟服务重启：同一库文件重新加载应用
    importlib.reload(main)
    with TestClient(main.app) as c2:
        got = c2.get("/conversion-tables/CT-KEEP")
        assert got.status_code == 200
        assert got.json()["forward_mapping"][0]["baseline_score"] == 59
        rev = c2.get("/conversion-tables/CT-KEEP/reverse/59")
        assert rev.status_code == 200
        assert rev.json()["original_scores"] == [88, 89, 90]
        # 重启后原样重送仍取原码表
        replay = c2.post("/conversion-tables", json=_table_payload("CT-KEEP"))
        assert replay.status_code == 200 and replay.json()["replayed"] is True
