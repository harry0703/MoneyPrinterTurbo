from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_is_independent_and_pinned_to_python_311() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert project["project"]["requires-python"] == ">=3.11,<3.12"
    assert project["project"]["scripts"] == {"hti": "health_trend_intelligence.cli:app"}
    assert "mediacrawler" not in {d.lower() for d in project["project"]["dependencies"]}
    assert (ROOT / ".python-version").read_text("utf-8") == "3.11\n"


def test_notice_binds_fixed_upstream_and_noncommercial_license() -> None:
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    assert "d6f7c5bb906b6dac40ddf343ef9e26438a3de092" in notice
    assert "NON-COMMERCIAL LEARNING LICENSE 1.1" in notice
    assert r"E:\MoneyPrinterTurbo-3期\MediaCrawler" in notice


def test_runtime_data_and_credentials_are_git_ignored() -> None:
    rules = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert {".venv/", ".env", "raw/", "curated/", "approved/", "*_user_data_dir/"} <= set(rules)
