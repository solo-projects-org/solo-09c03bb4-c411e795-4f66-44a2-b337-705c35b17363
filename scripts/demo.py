"""端到端演示脚本：通过 HTTP 调用运行中的 API（与在 Swagger UI 操作等价）。

用法：python scripts/demo.py [base_url]
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def show(title: str, resp: httpx.Response) -> dict:
    print(f"\n===== {title} -> HTTP {resp.status_code} =====")
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
        return resp.json()
    except Exception:
        print(resp.text)
        return {}


def reg(no: str, a: str, b: str) -> dict:
    return {"action": "register", "report_no": no, "paper_a": a, "paper_b": b}


def wd(no: str) -> dict:
    return {"action": "withdraw", "report_no": no}


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=10)

    show("健康检查", c.get("/health"))

    # 1. 指定基准卷 BASE
    show("批次 B0：指定基准卷 BASE", c.post("/batches", json={
        "batch_no": "B0",
        "baselines": ["BASE"],
        "operations": [reg("R-SEED", "BASE", "SEED")],
    }))

    # 2. 单链登记：X-A-BASE
    show("批次 B1：登记单链 X-A-BASE", c.post("/batches", json={
        "batch_no": "B1",
        "operations": [reg("R1", "X", "A"), reg("R2", "A", "BASE")],
    }))
    show("查 X 资格（期望 single_chain，必经 R1/R2）", c.get("/qualifications/X"))

    # 3. 补一条平行边但仍共用 R2 —— 不能通过
    show("批次 B2：X-A 增加 R3，但 A-BASE 仍共用 R2", c.post("/batches", json={
        "batch_no": "B2", "operations": [reg("R3", "X", "A")],
    }))
    show("查 X 资格（期望 single_chain，仅 R2 必经）", c.get("/qualifications/X"))

    # 4. 再补一条独立 A-BASE 报告 R4 —— 两条边不相交链，通过
    show("批次 B3：A-BASE 增加独立报告 R4", c.post("/batches", json={
        "batch_no": "B3", "operations": [reg("R4", "A", "BASE")],
    }))
    show("查 X 资格（期望 qualified，列出两条链单号）", c.get("/qualifications/X"))

    # 5. 撤回 R4 —— 降回单链，回执失去名单含 X
    show("批次 B4：撤回 R4", c.post("/batches", json={
        "batch_no": "B4", "operations": [wd("R4")],
    }))
    show("查 X 资格（期望 single_chain）", c.get("/qualifications/X"))

    # 6. 再撤回 R2 —— 完全断开，缺依据
    show("批次 B5：撤回 R2", c.post("/batches", json={
        "batch_no": "B5", "operations": [wd("R2")],
    }))
    show("查 X 资格（期望 no_evidence）", c.get("/qualifications/X"))

    # 7. 幂等：B5 原样重送
    show("批次 B5 原样重送（期望 replayed=true，版本不变）", c.post("/batches", json={
        "batch_no": "B5", "operations": [wd("R2")],
    }))

    # 8. 同号异文拒收
    show("批次 B5 同号异文（期望 409 batch_conflict）", c.post("/batches", json={
        "batch_no": "B5", "operations": [reg("R9", "X", "A")],
    }))

    # 9. 版本查询与全量名单
    show("查版本 4 的 X 资格", c.get("/qualifications/X", params={"version": 4}))
    show("最近生效版全量资格", c.get("/qualifications"))
    show("批次列表", c.get("/batches"))
    show("按批号取回 B4 回执", c.get("/batches/B4/receipt"))
    show("报告清单（含撤回状态）", c.get("/reports"))

    # ================= 换算码表 =================

    # 10. 码表批次：基准卷 BASE-100，来源卷 MOCK-150（150 分制）经两份报告接通
    seed = show("批次 C0：基准卷 BASE-100，链 MOCK-150 -R-C1- MID-120 -R-C2- BASE-100",
                c.post("/batches", json={
                    "batch_no": "C0",
                    "baselines": ["BASE-100"],
                    "operations": [reg("R-C1", "MOCK-150", "MID-120"),
                                   reg("R-C2", "MID-120", "BASE-100")],
                }))
    version_used = seed["version"]  # 教研采用的生效版（C0 生效后的当前版）

    # 11. 并档场景：150 分制 0..150 每分一档（151 档）压进 0-100 共 101 个整数值，
    #     鸽笼原理必然并档 —— 这正是码表要记录、供数仓复核找回原分的场景
    records = []
    for original in range(0, 151):
        suggested = round(original * 100 / 150, 1)
        records.append({
            "original_score": original,
            "suggested_score": suggested,
            "baseline_min": max(0, int(suggested) - 2),
            "baseline_max": min(100, int(suggested) + 2),
            "headcount": 40 + (original * 37) % 160,
        })
    table = {
        "table_no": "CT-2026-001",
        "source_paper": "MOCK-150",
        "baseline_paper": "BASE-100",
        "version_used": version_used,
        "report_nos": ["R-C1", "R-C2"],
        "records": records,
    }
    resp = c.post("/conversion-tables", json=table)
    body = resp.json()
    print(f"\n===== 发布码表 CT-2026-001（151 档 -> 0-100 整数）-> HTTP {resp.status_code} =====")
    print(f"原分档数 {len(body['records'])}，不同基准分 {len(body['reverse_mapping'])} 个，"
          f"人数加权绝对差总和 {body['objective']}")
    merged = [e for e in body["reverse_mapping"] if len(e["original_scores"]) > 1]
    print(f"并档档数 {len(merged)}（{len(body['records']) - len(body['reverse_mapping'])} 档被并入），"
          f"示例：{json.dumps(merged[:3], ensure_ascii=False)}")

    # 12. 两向映射回查
    show("正向：原分 80 -> 基准分", c.get("/conversion-tables/CT-2026-001/forward/80"))
    merged_baseline = merged[0]["baseline_score"] if merged else 53
    show(f"反向：基准分 {merged_baseline} -> 原分列表（并档找回原分）",
         c.get(f"/conversion-tables/CT-2026-001/reverse/{merged_baseline}"))

    # 13. 同号原样重送取原码表；同号异文拒收
    replay = c.post("/conversion-tables", json=table)
    print(f"\n===== CT-2026-001 原样重送 -> HTTP {replay.status_code}，"
          f"replayed={replay.json()['replayed']}，created_at 不变："
          f"{replay.json()['created_at'] == body['created_at']} =====")
    changed = dict(table, records=records[:80])
    show("CT-2026-001 同号异文（期望 409 table_conflict）",
         c.post("/conversion-tables", json=changed))

    # 14. 无解场景：高原分档区间整体低于低原分档，说明原因
    show("无解示例（单调冲突，期望 422 infeasible 并说明原因）",
         c.post("/conversion-tables", json={
             "table_no": "CT-BAD", "source_paper": "MOCK-150", "baseline_paper": "BASE-100",
             "version_used": version_used, "report_nos": ["R-C1", "R-C2"],
             "records": [
                 {"original_score": 60, "suggested_score": 95,
                  "baseline_min": 90, "baseline_max": 100, "headcount": 10},
                 {"original_score": 70, "suggested_score": 5,
                  "baseline_min": 0, "baseline_max": 50, "headcount": 10},
             ]}))

    # 15. 撤回场景：撤回链上报告 R-C2
    show("批次 C1：撤回链上报告 R-C2", c.post("/batches", json={
        "batch_no": "C1", "operations": [wd("R-C2")],
    }))
    show("依据撤回后，新码表 CT-2026-002 发布被拒（期望 409 report_not_active）",
         c.post("/conversion-tables", json=dict(table, table_no="CT-2026-002")))
    show("被拒码表不存在（期望 404）", c.get("/conversion-tables/CT-2026-002"))
    kept = c.get("/conversion-tables/CT-2026-001")
    print(f"\n===== 已发布码表依据撤回后仍可回查 -> HTTP {kept.status_code}，"
          f"档数 {len(kept.json()['records'])}，映射完整 =====")
    show("码表清单", c.get("/conversion-tables"))


if __name__ == "__main__":
    main()
