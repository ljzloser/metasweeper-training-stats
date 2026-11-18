# training_stats

第三方训练统计插件：复用元扫雷「历史记录」插件的数据，展示训练进度，
不修改、不重复存储对局数据。

## 功能

- **概览**：样本局数、胜率、胜负分布、最佳/平均胜利用时、最佳/平均 3BV/s、
  平均点击有效率与平均 IOE（3BV/点击）。
- **趋势**：滚动胜率、滚动平均胜利用时，窗口默认 20 局，可在设置中调整。
- **会话**：间隔超过 30 分钟（可配置）即切分为新的训练会话，显示会话局数、
  胜场、胜率、最佳用时与时长。
- **分布与连胜**：按难度、模式汇总胜率和用时，显示当前连胜、最长连胜、点击数；当前连胜为负数表示连败，统计范围受当前筛选和局数限制。
- **最近对局**：最近 300 局的明细表。
- **筛选**：难度、模式、仅 NF、统计局数上限。
- **导出与分享**：按当前筛选导出 CSV，或复制统计摘要。
- **多语言**：支持简体中文、英语、德语、日语和波兰语，随主程序语言切换。

所有指标只统计符合筛选条件的对局；用时为 0 的记录视为重开/非有效局，
不计入最佳和平均用时。

## 依赖

插件依赖 `pandas` 和 `pyqtgraph`，由插件管理器的依赖环境负责安装：

```text
pandas>=2.0
pyqtgraph>=0.13
```

未安装 `pyqtgraph` 时插件仍可加载，只有趋势图替换为文字提示；
`pandas` 是核心统计依赖，缺失时插件无法加载。

`pyqtgraph` 上游当前要求 Python 3.12+。若依赖环境使用 Python 3.11，
请改用兼容版本，或只安装 `pandas` 并保留趋势图的降级提示。

## 安装

推荐通过插件市场安装：

1. 插件管理器 → 菜单「插件」→「插件市场...」；
2. 等待自动搜索 GitHub 仓库，或点击刷新；
3. 找到「训练统计」，选择版本后点「安装」；
4. 在「插件依赖环境」中安装本插件依赖；
5. 重启插件管理器并启用「训练统计」。

也可以手动安装：把本目录复制到程序级的 `plugins/` 或 `user_plugins/` 目录。

发布与 GitHub Topic / 版本 tag 约定见 [../PUBLISHING.md](../PUBLISHING.md)。

## 数据来源

只调用 `HistoryService.raw_query` 读取 `history` 表，字段包括
`rtime / level / mode / nf / game_state / bbbv / bbbv_solved / cl / ce /
start_time / end_time`。不写数据库，也不需要额外的数据目录。

## 设置

| 设置项 | 默认 | 说明 |
|---|---|---|
| 滚动窗口（局） | 20 | 趋势图与滚动胜率的样本窗口 |
| 会话间隔（分钟） | 30 | 超过该间隔视为新会话 |
| 默认难度 | 0 | 0=全部，3~6 对应各难度 |
| 默认模式 | -1 | -1=全部 |
| 默认统计局数 | 500 | 0 表示统计全部 |
| 打开界面时自动刷新 | 开 | 插件初始化/窗口创建后自动统计 |

## 开发环境（独立虚拟环境）

本插件项目**不使用元扫雷仓库的 `.venv`**，而是自带一套虚拟环境：

```powershell
cd <本仓库根目录>
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

| 文件 | 用途 |
|---|---|
| `.venv/` | 本项目专用虚拟环境，不与其他仓库共用 |
| `requirements-dev.txt` | 开发依赖：插件运行依赖 + PySide6、pytest、mypy、主程序导入链所需包 |
| `pyproject.toml` | pytest / mypy 配置，把元扫雷 `src` 作为源码路径（只读引用，不用其 venv） |

测试与类型检查：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy training_stats
```

`conftest.py` 通过 `METASWEEPER_SRC` 环境变量定位元扫雷源码目录；未指定时尝试同级或上一级的 `Solvable-Minesweeper/src`。它只把该目录加入 `sys.path`，不激活也不复用其虚拟环境。其他目录布局请设置该变量；类型检查可将相同路径设置为 `MYPYPATH`。

运行 `pyside6-lrelease training_stats/translations/<语言>.ts -qm training_stats/translations/<语言>.qm` 可重新编译翻译；发布时需要同时提交 TS 源文件和 QM 文件。

## 测试

```powershell
cd <本仓库根目录>
.\.venv\Scripts\python.exe -m pytest
```
