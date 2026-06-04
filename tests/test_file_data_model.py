import sys

import pytest
from PySide6.QtWidgets import QApplication

from file_data_model import FileDataModel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_set_displayed_images_clamps_index(qapp, tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    pa, pb = str(a.resolve()), str(b.resolve())
    model = FileDataModel()
    model.set_displayed_images([pa, pb], notify=False)
    model.set_current_index(1, notify=False)
    model.set_displayed_images([pa], notify=True)
    assert model.get_current_index() == 0
    assert model.get_current_image_path() == pa


def test_set_current_image_path_syncs_index(qapp, tmp_path):
    paths = []
    for name in ("one.jpg", "two.jpg"):
        p = tmp_path / name
        p.write_bytes(b"x")
        paths.append(str(p.resolve()))
    model = FileDataModel()
    model.set_displayed_images(paths, notify=False)
    model.set_current_image_path(paths[1], notify=False)
    assert model.get_current_index() == 1
    assert model.get_current_image_path() == paths[1]


def test_set_current_index_updates_path(qapp, tmp_path):
    paths = []
    for name in ("a.jpg", "b.jpg"):
        p = tmp_path / name
        p.write_bytes(b"x")
        paths.append(str(p.resolve()))
    model = FileDataModel()
    model.set_displayed_images(paths, notify=False)
    model.set_current_index(1, notify=False)
    assert model.get_current_image_path() == paths[1]
