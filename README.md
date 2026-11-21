# 跨校成绩入仓资格核查 + 换算码表 API

教研员按批号登记/撤回卷型等值报告。每份报告以唯一单号连接两个卷型（无向、可双向引用），
一个卷型必须存在**两条不共用报告**的等值链通往基准卷，才取得入仓资格。

不同卷型的成绩换成百分制整数时，部分原分档会并到同一档（并档），数仓复核找不回原分。
**换算码表**把来源卷各原分档到基准卷的换算关系固化发布：按码表号可做原分 ↔ 基准分
两向回查，依据报告撤回或服务重启后码表仍可查。

## 资格规则

| 状态 | 含义 | 返回内容 |
| --- | --- | --- |
| `baseline` | 基准卷本身，免核查 | — |
| `qualified` | 存在两条边不相交的链到基准卷（链可经过相同卷型） | `chains`：两条链各自的报告单号 |
| `single_chain` | 尚能接通基准卷，但只有一条边不相交链 | `mandatory_report_nos`：所有必经单号（桥边） |
| `no_evidence` | 与基准卷完全断开，缺依据 | 空 |

- 同一对卷型的不同报告单号分别计入（平行边各自独立）。
- 两条链允许经过相同卷型，但不能共用同一份报告。
- 算法：无向图边容量为 1，Edmonds-Karp 最大流（最多增广两次）判定边不相交路径数；
  单链时用逐边删除 BFS 求全部桥边。

## 批次与版本语义

- 每个成功生效的批次产生一个自增版本号，按实际生效顺序核对；
- 报告变更、资格重算、回执写入在**同一个 SQLite 事务**中一起生效（`BEGIN IMMEDIATE` + 应用层写锁）；
- 批次回执列出相对上一版**取得资格**（`qualified_papers`）和**失去资格**（`disqualified_papers`）的卷型，供数仓更新入仓名单；
- 已生效批次**原样重送**返回原回执（`replayed=true`，版本号不变）；
- **同号异文**返回 `409 batch_conflict`，不产生新版本；
- 数据落盘 SQLite（WAL），进程失败/重启后仍可查最近生效版及任一历史版本。

## 换算码表

把来源卷各原分档换算成基准卷的 0-100 整数基准分：

- 提交内容：码表号、来源卷、基准卷、教研采用的生效版（`version_used`）、
  按顺序填写的报告单号（`report_nos`），以及每个原分档一条记录
  （原分、建议分、允许的基准分整数区间、人数）；
- 换算规则：基准分取 0-100 整数；同一原分统一换算（重复原分 422 拒收）；
  原分越高基准分也必须越高 —— 按原分升序基准分**单调不降**
  （允许相邻档并到同一基准分，即并档；151 个原分压进 101 个整数值时并档不可避免）；
- 求解：在各档区间（与 0-100 求交）内选值，使 `Σ 人数 × |基准分 − 建议分|` 最小；
  动态规划 O(档数 × 101)，并列取较小基准分保证结果确定；
  无解时返回 `422 infeasible` 并说明原因（区间与 0-100 无交集 / 单调约束冲突的档位）；
- 发布校验（全部在写事务内，任一失败整体回滚，**不产生新码表**）：
  - 报告链在所用版和当前版都须有效（未登记/已撤回即 `409 report_not_active`）；
  - 基准卷须为两版共同的基准卷（否则 `409 baseline_not_common`）；
  - 报告链按顺序从来源卷接到基准卷（断裂 `409 chain_broken`，
    未到基准卷 `409 chain_not_reaching_baseline`）；
- 发布后按码表号查两向映射（正向：原分 → 基准分；反向：基准分 → 原分列表，
  并档档可见全部原分与合计人数）；码表是发布时快照，依据撤回或服务重启后仍可回查；
- 同号原样重送返回原码表（`replayed=true`），同号异文 `409 table_conflict` 拒收。

### 码表请求示例

```json
{
  "table_no": "CT-2026-001",
  "source_paper": "MOCK-150",
  "baseline_paper": "BASE-100",
  "version_used": 7,
  "report_nos": ["R-C1", "R-C2"],
  "records": [
    {"original_score": 88, "suggested_score": 58.6, "baseline_min": 55, "baseline_max": 60, "headcount": 300},
    {"original_score": 89, "suggested_score": 59.1, "baseline_min": 56, "baseline_max": 61, "headcount": 250},
    {"original_score": 90, "suggested_score": 59.4, "baseline_min": 57, "baseline_max": 62, "headcount": 100}
  ]
}
```

上例三档最优解并到基准分 59（并档），反向映射 `59 -> [88, 89, 90]`。

## 启动方式

### Docker Compose（推荐）

```bash
docker compose up --build
# API:   http://localhost:8000
# Swagger: http://localhost:8000/docs
```

SQLite 数据保存在命名卷 `qualification-data`（容器内 `/data/qualification.db`）。

### 本地运行

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
QUAL_DB_PATH=./data/qualification.db uvicorn app.main:app --reload
```

## 接口（均可在 Swagger UI 提交）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/batches` | 提交批次（登记/撤回，可同时指定基准卷全集） |
| GET | `/batches` | 列出全部生效批次/版本 |
| GET | `/batches/{batch_no}/receipt` | 按批号取回执 |
| GET | `/qualifications/{paper_id}?version=` | 查单个卷型资格（缺省最近生效版） |
| GET | `/qualifications?version=` | 查同一生效版下全部卷型资格 |
| GET | `/reports` / `/reports/{report_no}` | 报告查询（含撤回状态） |
| POST | `/conversion-tables` | 发布换算码表（校验报告链后求解最优换算） |
| GET | `/conversion-tables` | 列出全部已发布码表 |
| GET | `/conversion-tables/{table_no}` | 按码表号查两向映射（撤回/重启后可回查） |
| GET | `/conversion-tables/{table_no}/forward/{original_score}` | 正向换算：原分 → 基准分 |
| GET | `/conversion-tables/{table_no}/reverse/{baseline_score}` | 反向回查：基准分 → 原分列表 |

### 批次请求示例

```json
{
  "batch_no": "B2026-001",
  "baselines": ["BASE-2026"],
  "operations": [
    {"action": "register", "report_no": "R001", "paper_a": "P-A", "paper_b": "P-B"},
    {"action": "withdraw", "report_no": "R099"}
  ]
}
```

`baselines` 为该批生效的基准卷全集；不提供则沿用上一版。

## 自测

```bash
pip install pytest httpx
python -m pytest tests/ -q          # 41 项单元/接口测试
python scripts/demo.py              # 对运行中的服务做端到端演示（含并档与撤回场景）
python scripts/concurrency_check.py # 并发批次顺序与幂等核对
```

重点场景：
- `tests/test_graph.py::test_shared_edge_fails_even_with_extra_branch`：共用报告不通过；
- `tests/test_api.py::test_withdraw_downgrades_to_single_chain`：撤回后降为单链、再撤回变缺依据；
- `tests/test_conversion.py::test_solver_matches_brute_force_randomized`：求解器与暴力枚举对拍；
- `tests/test_conversion.py::test_withdrawn_chain_report_blocks_publish_but_keeps_old_table`：
  链上报告撤回后拒发新码表、已发布码表仍可回查；
- `tests/test_conversion.py::test_table_survives_restart`：服务重启后按码表号回查。
