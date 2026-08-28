"""PIPL 法律保留判定单元测试（0006 迁移配套）。

覆盖矩阵（合规口径：宁可误拦不可漏放）：
- REJECTED 报告 → 不阻断
- 他人报告（主体不匹配）→ 不阻断（修复历史骨架缺陷）
- PENDING / SUBMITTED → 阻断
- ACCEPTED 未满 7 年 → 阻断
- ACCEPTED 满 7 年 → 解除
- submitted_at 缺失的 ACCEPTED → 保守阻断
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.workers.tasks_pipl import (
    AML_RETENTION_YEARS,
    _collect_active_legal_holds,
    _is_active_legal_hold,
)


def _report(
    *,
    status: str = "PENDING",
    subject: str | None = "U007",
    submitted_at: datetime | None = None,
    report_no: str = "AML2026-001",
) -> Any:
    return SimpleNamespace(
        id=report_no,
        status=status,
        subject_user_account_id=subject,
        submitted_at=submitted_at,
        report_no=report_no,
    )


def _cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(days=AML_RETENTION_YEARS * 365)


class TestIsActiveLegalHold:
    def test_rejected_never_holds(self) -> None:
        assert _is_active_legal_hold(_report(status="REJECTED"), _cutoff()) is False

    def test_pending_holds(self) -> None:
        assert _is_active_legal_hold(_report(status="PENDING"), _cutoff()) is True

    def test_submitted_holds(self) -> None:
        assert _is_active_legal_hold(_report(status="SUBMITTED"), _cutoff()) is True

    def test_accepted_within_retention_holds(self) -> None:
        recent = datetime.now(UTC) - timedelta(days=365)
        assert _is_active_legal_hold(_report(status="ACCEPTED", submitted_at=recent), _cutoff()) is True

    def test_accepted_expired_released(self) -> None:
        old = datetime.now(UTC) - timedelta(days=AML_RETENTION_YEARS * 365 + 30)
        assert _is_active_legal_hold(_report(status="ACCEPTED", submitted_at=old), _cutoff()) is False

    def test_accepted_missing_time_conservatively_holds(self) -> None:
        """submitted_at 缺失无法证明期满：保守保留。"""
        assert _is_active_legal_hold(_report(status="ACCEPTED", submitted_at=None), _cutoff()) is True


class TestCollectActiveHolds:
    """三路检索 + 去重 + 谓词过滤。

    fake session 模拟各查询的 WHERE 谓词（主体精确匹配 / 孤儿列空），
    使装配逻辑与去重行为可被忠实验证。
    """

    def _fake_session(self, user: str, direct: list, via_tx: list, via_case: list) -> Any:
        results = iter(
            [
                [r for r in direct if r.subject_user_account_id == user],
                [r for r in via_tx if r.subject_user_account_id is None],
                [r for r in via_case if r.subject_user_account_id is None],
            ]
        )

        class _Scalars:
            def __init__(self, rows: list) -> None:
                self._rows = rows

            def all(self):  # noqa: ANN202
                return self._rows

        class _Result:
            def __init__(self, rows: list) -> None:
                self._rows = rows

            def scalars(self) -> _Scalars:
                return _Scalars(self._rows)

        class _Session:
            def execute(self, *_a, **_k):  # noqa: ANN202
                return _Result(next(results))

        return _Session()

    def test_subject_match_only(self) -> None:
        session = self._fake_session("U007", direct=[_report(subject="U007")], via_tx=[], via_case=[])
        holds = _collect_active_legal_holds(session, "00000000-0000-0000-0000-000000000001", "U007", _cutoff())
        assert len(holds) == 1
        assert holds[0].report_no == "AML2026-001"

    def test_other_subject_ignored(self) -> None:
        """他人报告不构成阻断（修复骨架实现的全租户误拦）。"""
        session = self._fake_session(
            "U007",
            direct=[_report(subject="U999"), _report(report_no="AML2026-002")],
            via_tx=[],
            via_case=[],
        )
        holds = _collect_active_legal_holds(session, "00000000-0000-0000-0000-000000000001", "U007", _cutoff())
        # U007 自己的报告命中，U999 的被 WHERE 过滤
        assert [h.report_no for h in holds] == ["AML2026-002"]

    def test_expired_filtered_out(self) -> None:
        old = datetime.now(UTC) - timedelta(days=AML_RETENTION_YEARS * 365 + 1)
        session = self._fake_session(
            "U007",
            direct=[_report(status="ACCEPTED", submitted_at=old)],
            via_tx=[],
            via_case=[],
        )
        assert _collect_active_legal_holds(session, "00000000-0000-0000-0000-000000000001", "U007", _cutoff()) == []

    def test_orphan_via_join_path(self) -> None:
        """孤儿报告（主体列为空）经联表路径归属并阻断。"""
        orphan = _report(subject=None, report_no="AML2026-003")
        session = self._fake_session("U007", direct=[], via_tx=[orphan], via_case=[])
        holds = _collect_active_legal_holds(session, "00000000-0000-0000-0000-000000000001", "U007", _cutoff())
        assert [h.report_no for h in holds] == ["AML2026-003"]

    def test_dedup_across_paths(self) -> None:
        same = _report(subject="U007")
        session = self._fake_session("U007", direct=[same], via_tx=[], via_case=[])
        holds = _collect_active_legal_holds(session, "00000000-0000-0000-0000-000000000001", "U007", _cutoff())
        assert len(holds) == 1
