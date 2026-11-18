"""training_stats 界面组件。

界面只在 GUI 线程创建和修改；插件线程通过 `_data_signal` 与
`_status_signal` 投递结果。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from shared_types.enums import GameLevel, GameMode

from .i18n import tr
from .stats import StatsFilters, StatsResult, summary_text

_pg = None
_pg_error = ""


def _pyqtgraph() -> Any:
    """延迟导入；记录实际异常，允许用户安装依赖后重新打开界面重试。"""
    global _pg, _pg_error
    if _pg is None:
        try:
            import pyqtgraph
        except Exception as exc:
            _pg_error = f"{type(exc).__name__}: {exc}"
        else:
            _pg = pyqtgraph
            _pg_error = ""
    return _pg


def _level_choices() -> list[tuple[str, int | None]]:
    choices: list[tuple[str, int | None]] = [(tr("全部难度"), None)]
    choices.extend((level.display_name, int(level.value)) for level in GameLevel)
    return choices


def _mode_choices() -> list[tuple[str, int | None]]:
    choices: list[tuple[str, int | None]] = [(tr("全部模式"), None)]
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

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


def _table_from_frame(frame: pd.DataFrame) -> QTableWidget:
    table = QTableWidget(0, len(frame.columns))
    table.setHorizontalHeaderLabels([tr(str(c)) for c in frame.columns])
    table.setRowCount(len(frame))
    for row_index, record in enumerate(frame.itertuples(index=False)):
        for col_index, value in enumerate(record):
            item = QTableWidgetItem(tr(value) if isinstance(value, str) else str(value))
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

    _CARD_TITLES = (
        ("attempts", "样本局数"), ("win_rate", "胜率"),
        ("wins", "胜场"), ("losses", "失败"),
        ("best_time", "最佳用时"), ("avg_time", "平均胜利用时"),
        ("best_bbbv_s", "最佳 3BV/s"), ("avg_bbbv_s", "平均 3BV/s"),
        ("avg_click_eff", "平均有效率"), ("avg_ioe", "平均 IOE"),
        ("avg_clicks", "平均点击数"), ("current_streak", "当前连胜"),
        ("best_streak", "最长连胜"), ("total_clicks", "总点击数"),
    )

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
        self._level_label = QLabel(tr("难度"))
        filters.addWidget(self._level_label)
        self._level = QComboBox()
        for text, value in _level_choices():
            self._level.addItem(text, value)
        self._level.setCurrentIndex(
            max(0, self._level.findData(default_level)))
        filters.addWidget(self._level)

        self._mode_label = QLabel(tr("模式"))
        filters.addWidget(self._mode_label)
        self._mode = QComboBox()
        for text, value in _mode_choices():
            self._mode.addItem(text, value)
        self._mode.setCurrentIndex(max(0, self._mode.findData(default_mode)))
        filters.addWidget(self._mode)

        self._nf = QCheckBox(tr("仅 NF"))
        filters.addWidget(self._nf)

        self._limit_label = QLabel(tr("最近局数"))
        filters.addWidget(self._limit_label)
        self._limit = QSpinBox()
        self._limit.setRange(0, 200_000)
        self._limit.setSingleStep(100)
        self._limit.setValue(default_limit)
        self._limit.setSpecialValueText(tr("全部"))
        filters.addWidget(self._limit)

        self._refresh = QPushButton(tr("刷新"))
        self._refresh.clicked.connect(self._request_refresh)
        filters.addWidget(self._refresh)

        self._export = QPushButton(tr("导出 CSV"))
        self._export.clicked.connect(self._request_export)
        filters.addWidget(self._export)

        self._copy = QPushButton(tr("复制摘要"))
        self._copy.clicked.connect(self._copy_summary)
        filters.addWidget(self._copy)
        filters.addStretch(1)
        layout.addLayout(filters)

        self._status = QLabel(tr("等待历史记录…"))
        self._status.setStyleSheet("color: gray;")
        layout.addWidget(self._status)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_overview_tab(), tr("概览"))
        self._tabs.addTab(self._build_trend_tab(), tr("趋势"))
        self._sessions_tab = QWidget()
        self._sessions_layout = QVBoxLayout(self._sessions_tab)
        self._tabs.addTab(self._sessions_tab, tr("会话"))
        self._recent_tab = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_tab)
        self._tabs.addTab(self._recent_tab, tr("最近对局"))
        self._breakdown_tab = QWidget()
        self._breakdown_layout = QVBoxLayout(self._breakdown_tab)
        self._tabs.addTab(self._breakdown_tab, tr("分布"))
        layout.addWidget(self._tabs, 1)

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        grid = QGridLayout()
        self._cards: dict[str, _Card] = {}
        for index, (key, title) in enumerate(self._CARD_TITLES):
            card = _Card(tr(title))
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
            self._trend_hint = QLabel(
                tr("无法加载 pyqtgraph，趋势图不可用：{error}").format(error=_pg_error))
            self._trend_hint.setWordWrap(True)
            layout.addWidget(self._trend_hint)
            self._winrate_plot = None
            self._time_plot = None
            return page
        pg.setConfigOptions(antialias=True)
        self._winrate_plot = pg.PlotWidget(title=tr("滚动胜率 (%)"))
        self._winrate_plot.showGrid(x=True, y=True, alpha=0.3)
        self._winrate_curve = self._winrate_plot.plot(pen="#2e7d32")
        layout.addWidget(self._winrate_plot, 1)

        self._time_plot = pg.PlotWidget(title=tr("滚动平均胜利用时 (s)"))
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
        self._set_status(tr("正在统计…"))
        self.refresh_requested.emit(self.current_filters())

    def _request_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出训练统计"), "training_stats.csv",
            tr("CSV 文件 (*.csv)"))
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        self._set_status(tr("正在导出…"))
        self.export_requested.emit((self.current_filters(), path))

    def _copy_summary(self) -> None:
        if self._last_result is None:
            self._set_status(tr("还没有可复制的统计结果。"))
            return
        QApplication.clipboard().setText(summary_text(self._last_result))
        self._set_status(tr("摘要已复制到剪贴板。"))

    def open_widget(self) -> None:
        self._request_refresh()

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _show_error(self, message: str) -> None:
        # 自动刷新可能在工作线程触发错误，不能用模态弹窗阻塞界面。
        self._status.setText(tr("统计失败：{error}").format(error=message))
        self._status.setToolTip(message)

    # ── 语言切换 ──────────────────────────────────────────────
    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "_tabs"):
            self.retranslateUi()
            if self._last_result is not None:
                self._request_refresh()

    def retranslateUi(self) -> None:
        """语言切换后重建固定文本；已选筛选条件保持不变。"""
        self._level_label.setText(tr("难度"))
        self._mode_label.setText(tr("模式"))
        self._nf.setText(tr("仅 NF"))
        self._limit_label.setText(tr("最近局数"))
        self._limit.setSpecialValueText(tr("全部"))
        self._refresh.setText(tr("刷新"))
        self._export.setText(tr("导出 CSV"))
        self._copy.setText(tr("复制摘要"))
        self._tabs.setTabText(0, tr("概览"))
        self._tabs.setTabText(1, tr("趋势"))
        self._tabs.setTabText(2, tr("会话"))
        self._tabs.setTabText(3, tr("最近对局"))
        self._tabs.setTabText(4, tr("分布"))
        for key, title in self._CARD_TITLES:
            self._cards[key].set_title(tr(title))
        self._retranslate_choices()
        if self._winrate_plot is not None:
            self._winrate_plot.setTitle(tr("滚动胜率 (%)"))
            self._time_plot.setTitle(tr("滚动平均胜利用时 (s)"))
        else:
            self._trend_hint.setText(
                tr("无法加载 pyqtgraph，趋势图不可用：{error}").format(error=_pg_error))
        if self._last_result is not None:
            self._apply_result(self._last_result)

    def _retranslate_choices(self) -> None:
        for combo, choices in (
            (self._level, _level_choices()), (self._mode, _mode_choices())
        ):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for text, value in choices:
                combo.addItem(text, value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)

    # ── 结果渲染（GUI 线程）────────────────────────────────────
    def _apply_result(self, result: StatsResult) -> None:
        self._last_result = result
        self._status.setToolTip("")
        if result.error:
            self._show_error(result.error)
            return
        if not result.has_data:
            self._set_status(tr("没有符合条件的历史记录。"))
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
            "avg_clicks": f"{overview.get('avg_clicks', 0):.1f}",
            "current_streak": str(overview.get("current_streak", 0)),
            "best_streak": str(overview.get("best_streak", 0)),
            "total_clicks": str(overview.get("total_clicks", 0)),
        }
        for key, text in formats.items():
            self._cards[key].set_value(text)

        self._render_trend(result)
        self._replace_table(
            self._sessions_layout, result.sessions, tr("暂无会话数据"))
        self._replace_table(self._recent_layout, result.recent, tr("暂无对局"))
        self._render_breakdown(result)
        window = result.trend.get("window", [0])[0] if result.trend else 0
        self._set_status(
            tr("已统计 {total} 局（滚动窗口 {window} 局）").format(
                total=result.total, window=window))

    def _render_breakdown(self, result: StatsResult) -> None:
        while self._breakdown_layout.count():
            item = self._breakdown_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for frame, empty_text in (
            (result.levels, tr("暂无难度分布")),
            (result.modes, tr("暂无模式分布")),
        ):
            if frame.empty:
                self._breakdown_layout.addWidget(QLabel(empty_text))
            else:
                self._breakdown_layout.addWidget(_table_from_frame(frame))

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
        self._replace_table(self._sessions_layout, pd.DataFrame(), tr("暂无会话数据"))
        self._replace_table(self._recent_layout, pd.DataFrame(), tr("暂无对局"))
        self._render_breakdown(StatsResult(filters=self.current_filters()))


def format_summary(result: StatsResult) -> str:
    """给日志用的简短摘要。"""
    if not result.has_data:
        return tr("无数据")
    overview: dict[str, Any] = result.overview
    return tr("{attempts} 局，胜率 {rate:.1f}%，最佳 {best:.3f}s").format(
        attempts=overview.get("attempts", 0),
        rate=overview.get("win_rate", 0),
        best=overview.get("best_time", 0),
    )