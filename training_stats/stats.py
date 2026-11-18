"""训练统计的计算逻辑。

本模块只依赖 pandas 和 HistoryService 的只读 SQL 接口，不直接访问数据库文件。
所有函数都在插件工作线程调用，不得触碰 Qt 控件。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared_types.enums import GameBoardState, GameLevel, GameMode

WIN = int(GameBoardState.Win.value)
FAIL = int(GameBoardState.Fail.value)

_LEVEL_NAMES = {
    int(GameLevel.BEGINNER.value): "初级",
    int(GameLevel.INTERMEDIATE.value): "中级",
    int(GameLevel.EXPERT.value): "高级",
    int(GameLevel.CUSTOM.value): "自定义",
}
_MODE_NAMES = {
    mode.value: mode.display_name
    for mode in GameMode
}

_COLUMNS = [
    "replay_id", "start_time", "end_time", "rtime", "level", "mode", "nf",
    "game_state", "bbbv", "bbbv_solved", "cl", "ce",
]

_SELECT = """
SELECT replay_id, start_time, end_time, rtime, level, mode, nf,
       game_state, bbbv, bbbv_solved, cl, ce
FROM history
"""


def level_name(level: int) -> str:
    return _LEVEL_NAMES.get(int(level), str(level))


def mode_name(mode: int) -> str:
    return _MODE_NAMES.get(int(mode), str(mode))


@dataclass(frozen=True, slots=True)
class StatsFilters:
    """统计视图的筛选条件。"""

    level: int | None = None
    mode: int | None = None
    nf_only: bool = False
    limit: int = 500

    def key(self) -> tuple[int | None, int | None, bool, int]:
        return (self.level, self.mode, self.nf_only, self.limit)


@dataclass(slots=True)
class StatsResult:
    """一次刷新产生的全部展示数据。"""

    filters: StatsFilters
    total: int = 0
    overview: dict[str, Any] = field(default_factory=dict)
    trend: dict[str, list[float]] = field(default_factory=dict)
    sessions: pd.DataFrame = field(default_factory=pd.DataFrame)
    recent: pd.DataFrame = field(default_factory=pd.DataFrame)
    error: str = ""

    @property
    def has_data(self) -> bool:
        return self.total > 0


def _where(filters: StatsFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters.level is not None:
        clauses.append("level = ?")
        params.append(int(filters.level))
    if filters.mode is not None:
        clauses.append("mode = ?")
        params.append(int(filters.mode))
    if filters.nf_only:
        clauses.append("nf = 1")
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def fetch_history(history: Any, filters: StatsFilters) -> list[dict[str, Any]]:
    """通过 HistoryService 读取记录，按结束时间倒序。"""
    where, params = _where(filters)
    sql = f"{_SELECT}{where}"
    order = " ORDER BY COALESCE(end_time, start_time) DESC"
    if filters.limit > 0:
        sql += order + " LIMIT ?"
        params.append(int(filters.limit))
    else:
        sql += order
    return history.raw_query(sql, tuple(params))


def _prepare_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_COLUMNS)
    df = pd.DataFrame(rows)
    for column in _COLUMNS:
        if column not in df.columns:
            df[column] = 0
    numeric = [c for c in _COLUMNS if c != "software"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce").fillna(0)
    df["nf"] = df["nf"].astype(bool)
    df["is_win"] = df["game_state"] == WIN
    df["is_loss"] = df["game_state"] == FAIL
    df["is_other"] = ~(df["is_win"] | df["is_loss"])
    df["time_s"] = df["rtime"].astype(float)
    time_s = df["time_s"].where(df["time_s"] > 0)
    cl = df["cl"].where(df["cl"] > 0)
    ce = df["ce"].where(df["ce"] > 0)
    df["bbbv_s"] = (df["bbbv_solved"] / time_s).fillna(0.0)
    df["click_eff"] = (ce / cl).fillna(0.0)
    df["ioe"] = (df["bbbv_solved"] / cl).fillna(0.0)
    df["level_name"] = df["level"].map(level_name)
    df["mode_name"] = df["mode"].map(mode_name)
    df["outcome"] = df.apply(
        lambda row: "胜利" if row["is_win"]
        else ("失败" if row["is_loss"] else "其它"),
        axis=1,
    )
    return df


def _overview(df: pd.DataFrame, attempts: int) -> dict[str, Any]:
    wins = df[df["is_win"]]
    # 用时为 0 的记录多为重开或非有效局，不能作为最佳/平均用时样本。
    timed = wins[wins["time_s"] > 0]
    losses = int(df["is_loss"].sum())
    total = len(df)
    win_rate = len(wins) / total * 100 if total else 0.0
    best_time = float(timed["time_s"].min()) if not timed.empty else 0.0
    best_bbbv_s = float(timed["bbbv_s"].max()) if not timed.empty else 0.0
    avg_time = float(timed["time_s"].mean()) if not timed.empty else 0.0
    avg_bbbv_s = float(timed["bbbv_s"].mean()) if not timed.empty else 0.0
    return {
        "attempts": attempts,
        "total": total,
        "wins": int(len(wins)),
        "losses": losses,
        "others": int(df["is_other"].sum()),
        "win_rate": win_rate,
        "best_time": best_time,
        "avg_time": avg_time,
        "best_bbbv_s": best_bbbv_s,
        "avg_bbbv_s": avg_bbbv_s,
        "avg_click_eff": float(wins["click_eff"].mean()) if not wins.empty else 0.0,
        "avg_ioe": float(wins["ioe"].mean()) if not wins.empty else 0.0,
    }


def _trend(df: pd.DataFrame, window: int) -> dict[str, list[float]]:
    ordered = df.sort_values("end_time", kind="stable")
    window = max(1, int(window))
    win_rate = ordered["is_win"].astype(float).rolling(
        window, min_periods=1).mean() * 100
    win_time = ordered["time_s"].where(ordered["is_win"]).rolling(
        window, min_periods=1).mean().fillna(0.0)
    return {
        "x": list(range(1, len(ordered) + 1)),
        "win_rate": [float(v) for v in win_rate],
        "win_time": [float(v) for v in win_time],
        "window": [window] * len(ordered),
    }


def _sessions(df: pd.DataFrame, gap_minutes: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["开始时间", "局数", "胜场", "胜率", "最佳用时", "时长"])
    ordered = df.sort_values("end_time", kind="stable").copy()
    gap_us = max(1, int(gap_minutes)) * 60 * 1_000_000
    starts = ordered["start_time"].astype("int64")
    previous_end = ordered["end_time"].astype("int64").shift(fill_value=starts.iloc[0])
    ordered["session_id"] = (starts - previous_end > gap_us).cumsum()
    rows: list[dict[str, Any]] = []
    for _, group in ordered.groupby("session_id", sort=False):
        wins = group[group["is_win"]]
        start = pd.to_datetime(int(group["start_time"].min()), unit="us")
        end = pd.to_datetime(int(group["end_time"].max()), unit="us")
        seconds = max(0, int((end - start).total_seconds()))
        rows.append({
            "开始时间": start.strftime("%Y-%m-%d %H:%M"),
            "局数": int(len(group)),
            "胜场": int(len(wins)),
            "胜率": round(len(wins) / len(group) * 100, 1),
            "最佳用时": round(float(wins["time_s"].min()), 3)
            if not wins.empty else 0.0,
            "时长": f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}",
        })
    return pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)


_RECENT_COLUMNS = [
    "结束时间", "难度", "模式", "结果", "用时(s)", "3BV/s", "有效率",
    "3BV", "点击数", "NF",
]


def _recent(df: pd.DataFrame, count: int = 300) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=_RECENT_COLUMNS)
    recent = df.sort_values("end_time", kind="stable", ascending=False).head(count)
    result = pd.DataFrame({
        "结束时间": pd.to_datetime(
            recent["end_time"].astype("int64"), unit="us"
        ).dt.strftime("%Y-%m-%d %H:%M"),
        "难度": recent["level_name"],
        "模式": recent["mode_name"],
        "结果": recent["outcome"],
        "用时(s)": recent["time_s"].round(3),
        "3BV/s": recent["bbbv_s"].round(3),
        "有效率": recent["click_eff"].round(3),
        "3BV": recent["bbbv_solved"].astype(int).astype(str)
        + "/" + recent["bbbv"].astype(int).astype(str),
        "点击数": recent["cl"].astype(int),
        "NF": recent["nf"].map(lambda value: "是" if value else ""),
    })
    return result.reset_index(drop=True)


def build_result(
    history: Any,
    filters: StatsFilters,
    *,
    rolling_window: int = 20,
    session_gap_minutes: int = 30,
) -> StatsResult:
    """读取并计算一次统计结果。"""
    rows = fetch_history(history, filters)
    df = _prepare_frame(rows)
    attempts = len(df)
    if df.empty:
        return StatsResult(
            filters=filters,
            recent=_recent(df),
            sessions=_sessions(df, session_gap_minutes),
        )
    return StatsResult(
        filters=filters,
        total=attempts,
        overview=_overview(df, attempts),
        trend=_trend(df, rolling_window),
        sessions=_sessions(df, session_gap_minutes),
        recent=_recent(df),
    )


def export_rows(history: Any, filters: StatsFilters) -> pd.DataFrame:
    """读取全部匹配记录，用于导出 CSV。"""
    export_filter = StatsFilters(
        level=filters.level,
        mode=filters.mode,
        nf_only=filters.nf_only,
        limit=0,
    )
    return _recent(_prepare_frame(fetch_history(history, export_filter)),
                   count=1_000_000)
