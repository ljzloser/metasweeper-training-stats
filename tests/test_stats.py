"""训练统计插件的核心计算测试（不依赖 Qt 界面）。"""
from __future__ import annotations

import pytest

from training_stats.stats import StatsFilters, build_result, export_rows

WIN = 6
FAIL = 5
BASE_US = 1_700_000_000_000_000


def _row(replay_id: int, offset_s: int, rtime: float, *, level: int = 3,
         state: int = WIN, nf: int = 0, cl: int = 25, ce: int = 20,
         bbbv: int = 20, solved: int = 20) -> dict[str, object]:
    start = BASE_US + offset_s * 1_000_000
    return {
        "replay_id": replay_id,
        "start_time": start,
        "end_time": start + int(rtime * 1_000_000),
        "rtime": rtime,
        "level": level,
        "mode": 0,
        "nf": nf,
        "game_state": state,
        "bbbv": bbbv,
        "bbbv_solved": solved,
        "cl": cl,
        "ce": ce,
    }


class FakeHistory:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def raw_query(self, sql: str, params: tuple = ()) -> list[dict[str, object]]:
        data = list(self.rows)
        if "level = ?" in sql:
            data = [r for r in data if r["level"] == params[0]]
        if "mode = ?" in sql:
            data = [r for r in data if r["mode"] == params[0]]
        if "nf = 1" in sql:
            data = [r for r in data if r["nf"]]
        data.sort(key=lambda r: (r["end_time"], r["start_time"]), reverse=True)
        if sql.endswith("LIMIT ?"):
            data = data[: int(params[-1])]
        return data


def test_overview_win_rate_and_best_time() -> None:
    history = FakeHistory([
        _row(1, 0, 30.0),
        _row(2, 40, 40.0, state=FAIL),
        _row(3, 90, 20.0, level=4, nf=1),
    ])
    result = build_result(history, StatsFilters(), rolling_window=2)

    assert result.total == 3
    assert result.overview["wins"] == 2
    assert result.overview["losses"] == 1
    assert result.overview["win_rate"] == pytest.approx(66.67, abs=0.01)
    assert result.overview["best_time"] == pytest.approx(20.0)


def test_zero_time_win_is_excluded_from_time_metrics() -> None:
    history = FakeHistory([
        _row(1, 0, 0.0),
        _row(2, 10, 25.0),
    ])
    result = build_result(history, StatsFilters(), rolling_window=2)

    assert result.overview["best_time"] == pytest.approx(25.0)
    assert result.overview["avg_time"] == pytest.approx(25.0)
    assert result.overview["best_bbbv_s"] == pytest.approx(20 / 25)


def test_sessions_split_by_inactivity_gap() -> None:
    history = FakeHistory([
        _row(1, 0, 10.0),
        _row(2, 60, 10.0),
        _row(3, 3600, 10.0),
    ])
    result = build_result(
        history, StatsFilters(), session_gap_minutes=30)

    assert len(result.sessions) == 2
    counts = sorted(result.sessions["局数"].tolist())
    assert counts == [1, 2]


def test_filters_apply_to_query_and_export() -> None:
    history = FakeHistory([
        _row(1, 0, 10.0, level=3),
        _row(2, 20, 10.0, level=4),
        _row(3, 40, 10.0, level=4, nf=1),
    ])
    only_expert = build_result(history, StatsFilters(level=4))
    assert only_expert.total == 2

    only_nf = build_result(history, StatsFilters(nf_only=True))
    assert only_nf.total == 1

    exported = export_rows(history, StatsFilters(level=4))
    assert len(exported) == 2
    assert "结果" in exported.columns


def test_empty_history_returns_empty_result() -> None:
    result = build_result(FakeHistory([]), StatsFilters())
    assert not result.has_data
    assert result.sessions.empty
    assert result.recent.empty
    assert list(result.recent.columns)[:3] == ["结束时间", "难度", "模式"]


def test_streaks_and_group_breakdowns() -> None:
    history = FakeHistory([
        _row(1, 0, 10, level=3),
        _row(2, 20, 12, level=3),
        _row(3, 40, 8, level=4, state=FAIL),
        _row(4, 60, 9, level=4, state=FAIL),
    ])
    result = build_result(history, StatsFilters())
    assert result.overview["best_streak"] == 2
    assert result.overview["current_streak"] == -2
    assert result.overview["total_clicks"] == 100
    assert sorted(result.levels["局数"].tolist()) == [2, 2]
    assert result.recent["连胜"].tolist() == [-2, -1, 2, 1]


def test_zero_time_wins_do_not_affect_trends_or_session_best() -> None:
    result = build_result(FakeHistory([
        _row(1, 0, 10), _row(2, 20, 0),
    ]), StatsFilters(), rolling_window=2)
    assert result.trend["win_time"] == [10, 10]
    assert result.sessions["最佳用时"].tolist() == [10]
