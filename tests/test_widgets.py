from pathlib import Path
import string
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtCore import QCoreApplication, QTranslator

from plugin_sdk import resolve_display_name
from training_stats import widgets
from training_stats.plugin import TrainingStatsPlugin
from training_stats.stats import StatsFilters, StatsResult


def test_language_change_preserves_filters(qtbot, qapp, monkeypatch):
    monkeypatch.setattr(widgets, "_pyqtgraph", lambda: None)
    widget = widgets.TrainingStatsWidget(default_level=4, default_limit=250)
    qtbot.addWidget(widget)
    translator = QTranslator()
    catalog = Path(widgets.__file__).parent / "translations" / "en_US.qm"
    assert translator.load(str(catalog))
    try:
        QCoreApplication.installTranslator(translator)
        widget.retranslateUi()
        assert widget._tabs.tabText(0) == "Overview"
        assert widget._refresh.text() == "Refresh"
        assert widget.current_filters().level == 4
        assert widget.current_filters().limit == 250
    finally:
        QCoreApplication.removeTranslator(translator)


@pytest.mark.parametrize("locale", ["en_US", "de_DE", "ja_JP", "pl_PL"])
def test_catalogs_are_complete_and_loadable(locale, qapp):
    directory = Path(widgets.__file__).parent / "translations"
    messages = ET.parse(directory / f"{locale}.ts").findall(".//message")
    assert messages
    assert all(m.find("translation") is not None
               and m.find("translation").get("type") != "unfinished"
               and "".join(m.find("translation").itertext()).strip()
               for m in messages)
    formatter = string.Formatter()
    for message in messages:
        source = message.findtext("source") or ""
        translation = "".join(message.find("translation").itertext())
        fields = lambda text: {name for _, name, _, _ in formatter.parse(text) if name}
        assert fields(source) == fields(translation), source
    translator = QTranslator()
    assert translator.load(str(directory / f"{locale}.qm"))
    try:
        QCoreApplication.installTranslator(translator)
        info = TrainingStatsPlugin.plugin_info()
        assert resolve_display_name(info.display_name, info.name) != "训练统计"
    finally:
        QCoreApplication.removeTranslator(translator)


def test_summary_copy_uses_current_language(qtbot, qapp, monkeypatch):
    monkeypatch.setattr(widgets, "_pyqtgraph", lambda: None)
    translator = QTranslator()
    assert translator.load(str(Path(widgets.__file__).parent / "translations" / "en_US.qm"))
    try:
        QCoreApplication.installTranslator(translator)
        widget = widgets.TrainingStatsWidget()
        qtbot.addWidget(widget)
        widget._apply_result(StatsResult(
            filters=StatsFilters(), total=1,
            overview={"attempts": 1, "win_rate": 100},
            trend={"window": [20]},
        ))
        widget._copy_summary()
        assert "100.0%" in qapp.clipboard().text()
        assert "样本局数" not in qapp.clipboard().text()
    finally:
        QCoreApplication.removeTranslator(translator)


def test_graph_import_error_is_shown_and_can_retry(qtbot, monkeypatch):
    import builtins

    original = builtins.__import__
    fail = True

    def importing(name, *args, **kwargs):
        if name == "pyqtgraph" and fail:
            raise ModuleNotFoundError("No module named 'PySide6.QtOpenGL'")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(widgets, "_pg", None)
    monkeypatch.setattr(builtins, "__import__", importing)
    widget = widgets.TrainingStatsWidget()
    qtbot.addWidget(widget)
    assert "PySide6.QtOpenGL" in widget._trend_hint.text()
    fail = False
    assert widgets._pyqtgraph() is not None
