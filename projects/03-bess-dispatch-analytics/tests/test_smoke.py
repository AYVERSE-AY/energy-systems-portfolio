"""环境冒烟测试：只验证 pytest 与运行环境可用，不涉及任何储能业务逻辑。"""

import sys

import pytest


def test_python_version_supported():
    assert sys.version_info >= (3, 10), f"需要 Python 3.10+，当前 {sys.version}"


def test_pytest_runs():
    assert pytest.__version__


def test_temp_dir_writable(tmp_path):
    target = tmp_path / "probe.txt"
    target.write_text("ok", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "ok"


def test_core_dependencies_importable():
    import matplotlib
    import numpy
    import pandas

    assert numpy.__version__
    assert pandas.__version__
    assert matplotlib.__version__


def test_venv_is_isolated():
    """确认测试跑在虚拟环境里，而不是系统 Python。"""
    assert sys.prefix != sys.base_prefix, f"未在虚拟环境中运行：{sys.executable}"
