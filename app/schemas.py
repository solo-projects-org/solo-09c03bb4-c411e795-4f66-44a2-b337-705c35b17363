"""请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Status = Literal["baseline", "qualified", "single_chain", "no_evidence"]


class ReportRegister(BaseModel):
    model_config = {"extra": "forbid"}

    action: Literal["register"]
    report_no: str = Field(min_length=1, description="报告唯一单号")
    paper_a: str = Field(min_length=1, description="卷型甲")
    paper_b: str = Field(min_length=1, description="卷型乙")

    @field_validator("report_no", "paper_a", "paper_b")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空字符串")
        return v


class ReportWithdraw(BaseModel):
    model_config = {"extra": "forbid"}

    action: Literal["withdraw"]
    report_no: str = Field(min_length=1, description="要撤回的报告单号")

    @field_validator("report_no")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空字符串")
        return v


class BatchSubmitRequest(BaseModel):
    model_config = {"extra": "forbid"}

    batch_no: str = Field(min_length=1, description="批次号")
    baselines: list[str] = Field(default_factory=list, description="本批生效的基准卷全集（不提供则沿用）")
    operations: list[dict] = Field(min_length=1, description="登记/撤回操作列表")

    @field_validator("batch_no")
    @classmethod
    def _strip_batch(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空字符串")
        return v

    @field_validator("baselines")
    @classmethod
    def _strip_baselines(cls, v: list[str]) -> list[str]:
        cleaned = [b.strip() for b in v]
        if any(not b for b in cleaned):
            raise ValueError("基准卷不能为空字符串")
        return cleaned


class Qualification(BaseModel):
    paper_id: str
    version: int
    status: Status
    label: str
    chains: list[list[str]] = Field(description="通过时：两条链各自的报告单号")
    mandatory_report_nos: list[str] = Field(description="单链时：所有必经报告单号")


class BatchReceipt(BaseModel):
    batch_no: str
    version: int
    effective_at: str
    baselines: list[str]
    qualified_papers: list[str] = Field(description="本批后取得资格的卷型（相对上一版新增）")
    disqualified_papers: list[str] = Field(description="本批后失去资格的卷型（相对上一版移除）")
    current_qualified: list[str] = Field(description="本批生效后全部有资格的非基准卷")
    current_status: dict[str, Qualification] = Field(description="本批涉及卷型的当前资格明细")
    replayed: bool = Field(description="是否为已生效批次的原样重送")


class ReportView(BaseModel):
    report_no: str
    paper_a: str
    paper_b: str
    status: Literal["active", "withdrawn"]
    reg_batch: str
    reg_version: int
    wd_batch: str | None
    wd_version: int | None


# ---------- 换算码表 ----------


class ConversionRecordIn(BaseModel):
    """一个原分档的换算记录。"""

    model_config = {"extra": "forbid"}

    original_score: float = Field(description="原分（原分档，同一码表内不得重复）")
    suggested_score: float = Field(description="建议分")
    baseline_min: int = Field(description="允许的基准分整数区间下界")
    baseline_max: int = Field(description="允许的基准分整数区间上界")
    headcount: int = Field(ge=0, description="人数")

    @model_validator(mode="after")
    def _check_interval(self):
        if self.baseline_min > self.baseline_max:
            raise ValueError("允许的基准分区间下界不能大于上界")
        return self


class ConversionTableSubmitRequest(BaseModel):
    model_config = {"extra": "forbid"}

    table_no: str = Field(min_length=1, description="码表号")
    source_paper: str = Field(min_length=1, description="来源卷")
    baseline_paper: str = Field(min_length=1, description="基准卷（须为所用版与当前版共同的基准卷）")
    version_used: int = Field(ge=1, description="教研采用的生效版")
    report_nos: list[str] = Field(min_length=1, description="按顺序填写的报告单号（从来源卷接到基准卷）")
    records: list[ConversionRecordIn] = Field(min_length=1, description="每个原分档一条记录")

    @field_validator("table_no", "source_paper", "baseline_paper")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空字符串")
        return v

    @field_validator("report_nos")
    @classmethod
    def _strip_report_nos(cls, v: list[str]) -> list[str]:
        cleaned = [no.strip() for no in v]
        if any(not no for no in cleaned):
            raise ValueError("报告单号不能为空字符串")
        return cleaned


class ConversionRecordOut(BaseModel):
    original_score: float
    suggested_score: float
    baseline_min: int
    baseline_max: int
    headcount: int
    baseline_score: int = Field(description="求解选定的基准分（0-100 整数）")
    deviation: float = Field(description="|基准分 − 建议分|")
    weighted_deviation: float = Field(description="人数 × 偏差")


class ForwardMappingEntry(BaseModel):
    original_score: float
    baseline_score: int


class ReverseMappingEntry(BaseModel):
    baseline_score: int
    original_scores: list[float] = Field(description="并到该基准分的全部原分（并档时多于一个）")
    headcount: int = Field(description="该基准分档合计人数")


class ConversionTableView(BaseModel):
    table_no: str
    source_paper: str
    baseline_paper: str
    version_used: int = Field(description="教研采用的生效版")
    version_current: int = Field(description="发布时的当前生效版")
    report_nos: list[str] = Field(description="发布时校验通过的报告链（按顺序）")
    objective: float = Field(description="人数加权绝对差总和的最小值")
    records: list[ConversionRecordOut]
    forward_mapping: list[ForwardMappingEntry] = Field(description="正向映射：原分 → 基准分")
    reverse_mapping: list[ReverseMappingEntry] = Field(description="反向映射：基准分 → 原分列表（并档可见）")
    created_at: str
    replayed: bool = Field(description="是否为同号原样重送返回的原码表")


class ConversionTableSummary(BaseModel):
    table_no: str
    source_paper: str
    baseline_paper: str
    version_used: int
    version_current: int
    objective: float
    created_at: str
