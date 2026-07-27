from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_local_api_reloads_when_source_contract_changes() -> None:
    startup_script = (PROJECT_ROOT / "scripts" / "start-local.ps1").read_text(encoding="utf-8")

    assert '"--reload"' in startup_script
    assert '"--reload-dir"' in startup_script
    assert "apps\\api\\src" in startup_script
