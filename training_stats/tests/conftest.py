"""让测试能在项目源码树之外运行。

优先使用环境变量 ``METASWEEPER_SRC``；否则使用同级目录
``Solvable-Minesweeper/src``。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get(
    "METASWEEPER_SRC", PLUGIN_ROOT.parent / "Solvable-Minesweeper" / "src"))

for entry in (str(PLUGIN_ROOT.parent), str(SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
