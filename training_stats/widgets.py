"""training_stats 界面组件。

界面只在 GUI 线程创建和修改；插件线程通过 `_data_signal` 与
`_status_signal` 投递结果。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from shared_types.enums import GameLevel, GameMode

from .stats import StatsFilters, StatsResult

_pg = None
_pg_loaded = False


def _pyqtgraph() -> Any:
    """延迟导入 pyqtgraph：缺失时整体功能降级，而不是插件加载失败。"""
    global _pg, _pg_loaded
    if not _pg_loaded:
        _pg_loaded = True
        try:
            import pyqtgraph
        except Exception:
            pyqtgraph = None
        _pg = pyqtgraph
    return _pg


def _level_choices() -> list[tuple[str, int | None]]:
    choices: list[tuple[str, int | None]] = [("全部难度", None)]
    choices.extend((level.display_name, int(level.value)) for level in GameLevel)
    return choices


def _mode_choices() -> list[tuple[str, int | None]]:
    choices: list[tuple[str, int | None]] = [("全部模式", None)]
    choices.extend((mode.display_name, int(mode.value)) for mode in GameMode)
    return choices


class _Card(QFrame):
    """概览指标卡片。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self._title = QLabel(title)
        self._title.setStyleSheet("color: gray;")
        self._value = QLabel("-")
        font = self._value.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        self._value.setFont(font)
        layout.addWidget(self._title)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


def _table_from_frame(frame: pd.DataFrame) -> QTableWidget:
    table = QTableWidget(0, len(frame.columns))
    table.setHorizontalHeaderLabels([str(c) for c in frame.columns])
    table.setRowCount(len(frame))
    for row_index, record in enumerate(frame.itertuples(index=False)):
        for col_index, value in enumerate(record):
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_index, col_index, item)
    table.setSortingEnabled(False)
    table.resizeColumnsToContents()
    return table


class TrainingStatsWidget(QWidget):
    """训练统计主界面。"""

    _data_signal = Signal(object)
    _status_signal = Signal(str)
    _error_signal = Signal(str)
    refresh_requested = Signal(object)
    export_requested = Signal(object)

    def __init__(
        self,
        default_level: int | None = None,
        default_mode: int | None = None,
        default_limit: int = 500,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._last_result: StatsResult | None = None
        self._build_ui(default_level, default_mode, default_limit)
        self._data_signal.connect(self._apply_result)
        self._status_signal.connect(self._set_status)
        self._error_signal.connect(self._show_error)

    # ── 界面搭建 ──────────────────────────────────────────────
    def _build_ui(
        self,
        default_level: int | None,
        default_mode: int | None,
        default_limit: int,
    ) -> None:
        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("难度"))
        self._level = QComboBox()
        for text, value in _level_choices():
            self._level.addItem(text, value)
        self._level.setCurrentIndex(
            max(0, self._level.findData(default_level)))
        filters.addWidget(self._level)

        filters.addWidget(QLabel("模式"))
        self._mode = QComboBox()
        for text, value in _mode_choices():
            self._mode.addItem(text, value)
        self._mode.setCurrentIndex(max(0, self._mode.findData(default_mode)))
        filters.addWidget(self._mode)

        self._nf = QCheckBox("仅 NF")
        filters.addWidget(self._nf)

        filters.addWidget(QLabel("最近局数"))
        self._limit = QSpinBox()
        self._limit.setRange(0, 200_000)
        self._limit.setSingleStep(100)
        self._limit.setValue(default_limit)
        self._limit.setSpecialValueText("全部")
        filters.addWidget(self._limit)

        self._refresh = QPushButton("刷新")
        self._refresh.clicked.connect(self._request_refresh)
        filters.addWidget(self._refresh)

        self._export = QPushButton("导出 CSV")
        self._export.clicked.connect(self._request_export)
        filters.addWidget(self._export)
        filters.addStretch(1)
        layout.addLayout(filters)

        self._status = QLabel("等待历史记录…")
        self._status.setStyleSheet("color: gray;")
        layout.addWidget(self._status)

        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(), "概览")
        tabs.addTab(self._build_trend_tab(), "趋势")
        self._sessions_tab = QWidget()
        self._sessions_layout = QVBoxLayout(self._sessions_tab)
        tabs.addTab(self._sessions_tab, "会话")
        self._recent_tab = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_tab)
        tabs.addTab(self._recent_tab, "最近对局")
        layout.addWidget(tabs, 1)

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        grid = QGridLayout()
        specs = [
            ("attempts", "样本局数"), ("win_rate", "胜率"),
            ("wins", "胜场"), ("losses", "失败"),
            ("best_time", "最佳用时"), ("avg_time", "平均胜利用时"),
            ("best_bbbv_s", "最佳 3BV/s"), ("avg_bbbv_s", "平均 3BV/s"),
            ("avg_click_eff", "平均有效率"), ("avg_ioe", "平均 IOE"),
        ]
        self._cards: dict[str, _Card] = {}
        for index, (key, title) in enumerate(specs):
            card = _Card(title)
            self._cards[key] = card
            grid.addWidget(card, index // 4, index % 4)
        layout.addLayout(grid)
        layout.addStretch(1)
        return page

    def _build_trend_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        pg = _pyqtgraph()
        if pg is None:
            hint = QLabel(
                "未安装 pyqtgraph，趋势图不可用。"
                "请在该插件的依赖环境中安装 pyqtgraph。")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self._winrate_plot = None
            self._time_plot = None
            return page
        pg.setConfigOptions(antialias=True)
        self._winrate_plot = pg.PlotWidget(title="滚动胜率 (%)")
        self._winrate_plot.showGrid(x=True, y=True, alpha=0.3)
        self._winrate_curve = self._winrate_plot.plot(pen="#2e7d32")
        layout.addWidget(self._winrate_plot, 1)

        self._time_plot = pg.PlotWidget(title="滚动平均胜利用时 (s)")
        self._time_plot.showGrid(x=True, y=True, alpha=0.3)
        self._time_curve = self._time_plot.plot(pen="#1565c0")
        layout.addWidget(self._time_plot, 1)
        return page

    # ── 交互 ──────────────────────────────────────────────────
    def current_filters(self) -> StatsFilters:
        return StatsFilters(
            level=self._level.currentData(),
            mode=self._mode.currentData(),
            nf_only=self._nf.isChecked(),
            limit=self._limit.value(),
        )

    def _request_refresh(self) -> None:
        self._set_status("正在统计…")
        self.refresh_requested.emit(self.current_filters())

    def _request_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出训练统计", "training_stats.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        self._set_status("正在导出…")
        self.export_requested.emit((self.current_filters(), path))

    def open_widget(self) -> None:
        self._request_refresh()

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _show_error(self, message: str) -> None:
        # 自动刷新可能在工作线程触发错误，不能用模态弹窗阻塞界面。
        self._status.setText(f"统计失败：{message}")
        self._status.setToolTip(message)

    # ── 结果渲染（GUI 线程）────────────────────────────────────
    def _apply_result(self, result: StatsResult) -> None:
        self._last_result = result
        self._status.setToolTip("")
        if result.error:
            self._show_error(result.error)
            return
        if not result.has_data:
            self._set_status("没有符合条件的历史记录。")
            self._clear_views()
            return

        overview = result.overview
        formats = {
            "attempts": str(overview.get("attempts", 0)),
            "win_rate": f"{overview.get('win_rate', 0):.1f}%",
            "wins": str(overview.get("wins", 0)),
            "losses": str(overview.get("losses", 0)),
            "best_time": f"{overview.get('best_time', 0):.3f}s",
            "avg_time": f"{overview.get('avg_time', 0):.3f}s",
            "best_bbbv_s": f"{overview.get('best_bbbv_s', 0):.3f}",
            "avg_bbbv_s": f"{overview.get('avg_bbbv_s', 0):.3f}",
            "avg_click_eff": f"{overview.get('avg_click_eff', 0):.3f}",
            "avg_ioe": f"{overview.get('avg_ioe', 0):.3f}",
        }
        for key, text in formats.items():
            self._cards[key].set_value(text)

        self._render_trend(result)
        self._replace_table(
            self._sessions_layout, result.sessions, "暂无会话数据")
        self._replace_table(self._recent_layout, result.recent, "暂无对局")
        self._set_status(
            f"已统计 {result.total} 局"
            f"（滚动窗口 {result.trend.get('window', [0])[0] if result.trend else 0} 局）")

    def _render_trend(self, result: StatsResult) -> None:
        if self._winrate_plot is None:
            return
        trend = result.trend
        self._winrate_curve.setData(trend.get("x", []), trend.get("win_rate", []))
        self._time_curve.setData(trend.get("x", []), trend.get("win_time", []))

    @staticmethod
    def _replace_table(layout: QVBoxLayout, frame: pd.DataFrame,
                       empty_text: str) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        if frame.empty:
            layout.addWidget(QLabel(empty_text))
            return
        layout.addWidget(_table_from_frame(frame))

    def _clear_views(self) -> None:
        for card in self._cards.values():
            card.set_value("-")
        if self._winrate_plot is not None and self._time_plot is not None:
            self._winrate_curve.setData([], [])
            self._time_curve.setData([], [])
        self._replace_table(self._sessions_layout, pd.DataFrame(), "暂无会话数据")
        self._replace_table(self._recent_layout, pd.DataFrame(), "暂无对局")


def format_summary(result: StatsResult) -> str:
    """给日志用的简短摘要。"""
    if not result.has_data:
        return "无数据"
    overview: dict[str, Any] = result.overview
    return (
        f"{overview.get('attempts', 0)} 局，"
        f"胜率 {overview.get('win_rate', 0):.1f}%，"
        f"最佳 {overview.get('best_time', 0):.3f}s"
    )