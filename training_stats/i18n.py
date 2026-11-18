"""插件本地翻译上下文。

宿主只加载插件包根目录 ``translations/<locale>.qm``，并拒绝覆盖应用与 Qt
的公共上下文，因此所有文本都绑定到本插件独有的 ``TrainingStats`` 上下文。
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication

CONTEXT = "TrainingStats"


def tr(source: str) -> str:
    return QCoreApplication.translate(CONTEXT, source)
