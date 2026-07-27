import logging

from mystery_atlas_api.analysis_dispatch import _run_inline, _spawn_inline


def test_inline_analysis_failure_does_not_escape_background_task(
    monkeypatch,
    caplog,
) -> None:
    def fail(_job_id: str) -> None:
        raise RuntimeError("provider secret detail")

    monkeypatch.setattr("mystery_atlas_analyzer.runner.run_analysis_job", fail)

    with caplog.at_level(logging.ERROR):
        _run_inline("job-1234")

    assert "job-1234" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "provider secret detail" not in caplog.text


def test_inline_analysis_runs_in_an_isolated_process(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_popen(command, **options):
        captured["command"] = command
        captured["options"] = options
        return object()

    monkeypatch.setattr("mystery_atlas_api.analysis_dispatch.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "mystery_atlas_api.analysis_dispatch._claim_inline_job",
        lambda _job_id: True,
    )

    _spawn_inline("job-5678")

    command = captured["command"]
    options = captured["options"]
    assert command[-1] == "job-5678"
    assert command[0]
    assert options["stdin"] is not None
    assert options["stdout"] is not None
    assert options["stderr"] is not None
    assert "apps" in options["env"]["PYTHONPATH"]
    assert "workers" in options["env"]["PYTHONPATH"]


def test_duplicate_inline_analysis_is_not_spawned(monkeypatch) -> None:
    monkeypatch.setattr(
        "mystery_atlas_api.analysis_dispatch._claim_inline_job",
        lambda _job_id: False,
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("duplicate worker must not be spawned")

    monkeypatch.setattr(
        "mystery_atlas_api.analysis_dispatch.subprocess.Popen",
        fail_if_called,
    )

    _spawn_inline("already-running-job")
