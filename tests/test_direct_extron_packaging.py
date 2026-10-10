"""Source packaging contracts; a successful frozen EXE still needs runtime UAT."""

import ast
from importlib.metadata import version
from pathlib import Path

from certmon.direct_extron import ParamikoDirectTransport


ROOT = Path(__file__).resolve().parents[1]


def test_direct_transport_uses_approved_paramiko_version():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "paramiko==5.0.0" in requirements
    assert version("paramiko") == "5.0.0"
    assert ParamikoDirectTransport().connect_timeout > 0


def test_pyinstaller_analysis_reaches_direct_transport():
    spec = ast.parse((ROOT / "certmon.spec").read_text(encoding="utf-8"))
    analysis = next(node for node in ast.walk(spec)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Analysis")
    keywords = {keyword.arg: keyword.value for keyword in analysis.keywords}
    hidden_imports = {node.value for node in ast.walk(keywords["hiddenimports"])
                      if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "app" in hidden_imports
    assert not {"paramiko", "certmon", "certmon.direct_extron"} & set(
        ast.literal_eval(keywords["excludes"]))
    app = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.ImportFrom) and node.module == "certmon.direct_extron"
               for node in ast.walk(app))
    direct = ast.parse((ROOT / "certmon" / "direct_extron.py").read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.Import) and any(alias.name == "paramiko" for alias in node.names)
               for node in ast.walk(direct))
