# 发布到插件市场

元扫雷插件市场通过 GitHub 的仓库主题发现公开插件，读取版本标签来显示可安装版本和更新。无需索引仓库。

## 1. 仓库结构约定

插件仓库的**根目录**必须是插件包本身（即根目录有 `__init__.py`）：

```
metasweeper-training-stats/        <- 你的公开仓库
├── __init__.py                    <- 必需：导出 BasePlugin 子类
├── plugin.py
├── stats.py
├── widgets.py
├── requirements.txt               <- 可选：插件运行依赖
├── README.md                      <- 可选：插件管理器里可查看
└── .metasweeper-plugin.json       <- 安装后自动生成，不要手写
```

## 2. 版本标签约定

用 **tag** 发布版本，默认前缀为 `metasweeper-v`：

```powershell
git tag metasweeper-v1.0.0
git push origin metasweeper-v1.0.0
```

- 版本号必须符合 PEP 440（`1.0.0`、`1.2.3`、`2.0`）。
- 预发布标签（`1.0.0-beta`）会被忽略，不会显示在市场中。
- 不符合约定的 tag（例如 `docs-update`）也会被忽略。
- 版本比较使用 `packaging.version.Version`，`1.10.0 > 1.2.3` 正确成立。

## 3. 设置 GitHub 仓库主题

在公开仓库页面右侧 **About → 设置按钮 → Topics** 添加 `metasweeper-plugin`。这是用于发现插件的仓库主题；上面的 Git tag 用于标识具体版本，两者都需要设置。GitHub 搜索索引更新可能有延迟。

## 4. 用户侧流程

1. 插件管理器 → 菜单「插件」→「插件市场...」；
2. 市场自动搜索带 `metasweeper-plugin` 主题的公开 GitHub 仓库；
3. 列表中显示各插件的最新版本、已安装版本与状态（未安装 / 可更新 / 已是最新）；
4. 搜索框按名称、说明、作者过滤；「可更新」筛选只显示有更新的插件；
5. 选中后可从下拉框选具体版本安装，或点「全部更新」批量更新。

安装来源会记录在插件目录的 `.metasweeper-plugin.json`，因此下次扫描能识别
版本并给出更新提示。手工复制的插件没有该文件，市场无法判断其版本。

## 5. 更新时的行为

- 更新会**替换插件目录**，插件数据目录
  （`data/plugin_data/<插件名>/`）保留。
- 更新后需要重启插件管理器生效。
- 插件依赖仍需在「插件依赖环境」中安装，见各插件 README。
