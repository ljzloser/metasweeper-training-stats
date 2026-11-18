"""让测试能在项目源码树之外运行。

优先使用环境变量 ``METASWEEPER_SRC``；否则使用同级目录
``Solvable-Minesweeper/src``。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PACKAGE = PLUGIN_ROOT / "training_stats"
_DEFAULT_SOURCES = (
    PLUGIN_ROOT.parent / "Solvable-Minesweeper" / "src",
    PLUGIN_ROOT.parent.parent / "Solvable-Minesweeper" / "src",
)
SRC = Path(os.environ.get("METASWEEPER_SRC") or next(
    (path for path in _DEFAULT_SOURCES if path.is_dir()), _DEFAULT_SOURCES[0]))

for entry in (str(PLUGIN_ROOT.parent), str(SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

# 测试包名保持稳定；安装器运行时会用仓库来源构造模块名。
if "training_stats" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "training_stats", PLUGIN_PACKAGE / "__init__.py",
        submodule_search_locations=[str(PLUGIN_PACKAGE)],
    )
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load plugin package for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules["training_stats"] = module
    spec.loader.exec_module(module)
