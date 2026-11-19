"""training_stats - 基于 HistoryService 的训练统计插件。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

from plugin_sdk import (
    BasePlugin, BoolConfig, IntConfig, OtherInfoBase, PluginInfo, WindowMode,
    make_plugin_icon,
)

from utils.plugin_i18n import PluginTranslate

from .i18n import tr
from .stats import StatsFilters, StatsResult, build_result, export_rows

_translate = PluginTranslate("TrainingStats")
from .widgets import TrainingStatsWidget, format_summary


def _history_protocol() -> type | None:
    """延迟导入历史记录插件提供的接口。"""
    try:
        from plugins.services.history import HistoryService
    except ModuleNotFoundError as exc:
        if exc.name not in {"plugins", "plugins.services", "plugins.services.history"}:
            raise
        return None
    return HistoryService


class _TaskBridge(QObject):
    """把工作线程的结果投递回插件线程（队列连接，串行处理）。"""

    request = Signal(object, object, object)


class TrainingStatsConfig(OtherInfoBase):
    """插件配置。"""

    rolling_window = IntConfig(
        default=20,
        label=_translate("TrainingStats", "滚动窗口（局）"),
        description=_translate("TrainingStats", "趋势图和滚动胜率使用的样本窗口"),
        min_value=5,
        max_value=500,
        step=5,
    )
    session_gap_minutes = IntConfig(
        default=30,
        label=_translate("TrainingStats", "会话间隔（分钟）"),
        description=_translate("TrainingStats", "两局间隔超过该时间视为新的训练会话"),
        min_value=5,
        max_value=240,
        step=5,
    )
    default_level = IntConfig(
        default=0,
        label=_translate("TrainingStats", "默认难度"),
        description=_translate("TrainingStats", "0=全部，3=初级，4=中级，5=高级，6=自定义"),
        min_value=0,
        max_value=6,
    )
    default_mode = IntConfig(
        default=-1,
        label=_translate("TrainingStats", "默认模式"),
        description=_translate("TrainingStats", "-1=全部；其余值参考游戏模式编号"),
        min_value=-1,
        max_value=20,
    )
    default_limit = IntConfig(
        default=500,
        label=_translate("TrainingStats", "默认统计局数"),
        description=_translate("TrainingStats", "0 表示统计全部记录；记录很多时建议保留上限"),
        min_value=0,
        max_value=100_000,
        step=100,
    )
    auto_refresh = BoolConfig(
        default=True,
        label=_translate("TrainingStats", "打开界面时自动刷新"),
        description=_translate("TrainingStats", "打开统计标签页时自动重新计算"),
    )


class TrainingStatsPlugin(BasePlugin[TrainingStatsConfig]):
    """训练统计：复用历史记录，展示训练进度。"""

    @classmethod
    def plugin_info(cls) -> PluginInfo:
        icon = QIcon(str(Path(__file__).resolve().with_name("icon.svg")))
        if icon.isNull():
            icon = make_plugin_icon("#1565C0", "T")
        return PluginInfo(
            name="training_stats",
            version="1.1.3",
            author="third-party",
            description=_translate("TrainingStats", "训练统计：胜率、滚动趋势与训练会话分析"),
            display_name=_translate("TrainingStats", "训练统计"),
            window_mode=WindowMode.TAB,
            icon=icon,
            other_info=TrainingStatsConfig,
        )

    def __init__(self, info: PluginInfo) -> None:
        super().__init__(info)
        self._history: Any = None
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="training-stats")
        self._bridge = _TaskBridge()
        self._bridge.request.connect(
            self._handle_request, Qt.ConnectionType.QueuedConnection)

    def _setup_subscriptions(self) -> None:
        pass

    def _create_widget(self) -> QWidget | None:
        config = self.other_info
        widget = TrainingStatsWidget(
            default_level=(
                None if (config is None or config.default_level == 0)
                else config.default_level),
            default_mode=(
                None if (config is None or config.default_mode < 0)
                else config.default_mode),
            default_limit=config.default_limit if config else 500,
        )
        widget.refresh_requested.connect(self._on_refresh_requested)
        widget.export_requested.connect(self._on_export_requested)
        return widget

    def on_initialized(self) -> None:
        self._bind_history(timeout=5.0)
        self.config_changed.connect(self._on_config_changed)
        if self.other_info is None or self.other_info.auto_refresh:
            self._emit_widget(lambda widget, _: widget._request_refresh(), None)

    def on_shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ── 调度 ──────────────────────────────────────────────────
    def _on_refresh_requested(self, filters: StatsFilters) -> None:
        self._run_task("refresh", filters)

    def _on_export_requested(self, payload: tuple[StatsFilters, str]) -> None:
        filters, path = payload
        self._run_task("export", (filters, Path(path)))

    def _bind_history(self, timeout: float) -> bool:
        """等待并绑定 HistoryService 代理（服务方法在提供者线程执行）。"""
        if self._history is not None:
            return True
        protocol = _history_protocol()
        if protocol is None or self.wait_for_service(protocol, timeout=timeout) is None:
            return False
        self._history = self.get_service_proxy(protocol)
        self.logger.info("TrainingStats 已连接 HistoryService")
        return True

    def _ensure_history(self) -> bool:
        return self._bind_history(timeout=2.0)

    def _run_task(self, kind: str, payload: object) -> None:
        if not self._ensure_history():
            self._notify_error(tr("HistoryService 不可用，请先启用历史记录插件。"))
            return
        history = self._history
        config = self.other_info

        def _work() -> None:
            try:
                if kind == "export":
                    job: Any = payload
                    export_filters: StatsFilters = job[0]
                    export_path: Path = job[1]
                    export_rows(history, export_filters).to_csv(
                        export_path, index=False, encoding="utf-8-sig")
                    self._bridge.request.emit("exported", str(export_path), None)
                    return
                result = build_result(
                    history,
                    payload,  # type: ignore[arg-type]
                    rolling_window=config.rolling_window if config else 20,
                    session_gap_minutes=(
                        config.session_gap_minutes if config else 30),
                )
                self._bridge.request.emit("result", result, None)
            except Exception as exc:  # noqa: BLE001 - 通过界面反馈
                self._bridge.request.emit("error", str(exc), None)

        self._executor.submit(_work)

    def _handle_request(self, kind: str, payload: object, _: object) -> None:
        if kind == "result":
            result = payload
            if not isinstance(result, StatsResult):
                self._notify_error(tr("统计结果类型异常"))
                return
            self.logger.info(f"统计完成: {format_summary(result)}")
            self._emit_widget(
                lambda widget, value: widget._data_signal.emit(value), result)
        elif kind == "exported":
            self._emit_widget(
                lambda widget, path: widget._status_signal.emit(
                    tr("已导出到 {path}").format(path=path)), payload)
        else:
            self._notify_error(str(payload))

    def _emit_widget(self, func, payload: object) -> None:
        widget = self._widget
        if widget is None:
            return

        def _call() -> None:
            if self._widget is not widget:
                return
            try:
                func(widget, payload)
            except RuntimeError:
                pass

        self.run_on_gui(_call)

    def _notify_error(self, message: str) -> None:
        self.logger.error(message)
        self._emit_widget(
            lambda widget, text: widget._error_signal.emit(text), message)

    def _on_config_changed(self, name: str, _value: object) -> None:
        if name in ("rolling_window", "session_gap_minutes"):
            self._emit_widget(lambda widget, _: widget._request_refresh(), None)
