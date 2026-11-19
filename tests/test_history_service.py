import sys
from types import SimpleNamespace
from unittest.mock import Mock

from training_stats.plugin import TrainingStatsPlugin


def test_binding_without_history_plugin_returns_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "plugins.services.history", None)
    plugin = SimpleNamespace(_history=None, wait_for_service=Mock())

    assert not TrainingStatsPlugin._bind_history(plugin, timeout=5.0)
    plugin.wait_for_service.assert_not_called()
