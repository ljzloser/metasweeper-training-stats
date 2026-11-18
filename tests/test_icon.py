import hashlib
import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
import requests
from PySide6.QtGui import QIcon

from plugin_manager import app_paths
from plugin_manager.plugin_download import PluginDownloader
from plugin_manager.plugin_loader import PluginLoader
from plugin_manager.plugin_repositories import PluginRepository, RepositoryTag
from plugin_sdk import make_plugin_icon
from training_stats import plugin


PACKAGE_DIR = Path(plugin.__file__).resolve().parent


def test_plugin_info_renders_bundled_icon(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asset = PACKAGE_DIR / "icon.svg"
    assert asset.is_file()
    expected = QIcon(str(asset)).pixmap(20, 20)
    assert not expected.isNull()
    icon = plugin.TrainingStatsPlugin.plugin_info().icon
    assert icon is not None
    assert icon.pixmap(20, 20).toImage() == expected.toImage()


@pytest.mark.parametrize("svg_contents", [None, "<invalid>"])
def test_plugin_info_falls_back_when_svg_is_unusable(qapp, tmp_path, monkeypatch, svg_contents):
    monkeypatch.setattr(plugin, "__file__", str(tmp_path / "plugin.py"))
    if svg_contents is not None:
        (tmp_path / "icon.svg").write_text(svg_contents, encoding="utf-8")
    expected = make_plugin_icon("#1565C0", "T").pixmap(20, 20)
    icon = plugin.TrainingStatsPlugin.plugin_info().icon
    assert icon is not None
    assert not expected.isNull()
    assert icon.pixmap(20, 20).toImage() == expected.toImage()


def test_marketplace_zip_installs_renderable_icon(qapp, tmp_path, monkeypatch):
    zip_path = tmp_path / "source.zip"
    with ZipFile(zip_path, "w") as archive:
        for path in PACKAGE_DIR.rglob("*"):
            relpath = path.relative_to(PACKAGE_DIR.parent)
            if path.is_file() and "__pycache__" not in relpath.parts:
                archive.write(path, f"repo-sha/{relpath.as_posix()}")

    def copy_download(repository, tag, destination):
        shutil.copyfile(zip_path, destination)
        return hashlib.sha256(zip_path.read_bytes()).hexdigest()

    repo = PluginRepository.from_url("https://github.com/example/metasweeper-training-stats")
    tag = RepositoryTag("metasweeper-v1.1.0", "a" * 40)
    plugin_dir = tmp_path / "user_plugins"
    with requests.Session() as session:
        downloader = PluginDownloader(session, lambda: False, lambda *_: None)
        monkeypatch.setattr(downloader, "_download", copy_download)
        installed = downloader.install(repo, tag, plugin_dir, [])

    assert installed == plugin_dir / repo.module_name
    assert (installed / "icon.svg").read_bytes() == (PACKAGE_DIR / "icon.svg").read_bytes()

    monkeypatch.setattr(app_paths, "get_data_dir", lambda: tmp_path / "data")
    monkeypatch.syspath_prepend(str(tmp_path))
    loader = PluginLoader([plugin_dir])
    instances = []
    try:
        instances = loader.load_all()
        [loaded] = instances
        assert loaded.name == "training_stats"
        assert loaded.plugin_dir == installed
        expected = QIcon(str(installed / "icon.svg")).pixmap(20, 20)
        assert not expected.isNull()
        assert loaded.plugin_icon.pixmap(20, 20).toImage() == expected.toImage()
    finally:
        for instance in instances:
            instance.shutdown()
        for name in list(sys.modules):
            if name == repo.module_name or name.startswith(f"{repo.module_name}."):
                sys.modules.pop(name, None)
