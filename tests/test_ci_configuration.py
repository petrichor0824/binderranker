from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_ci_workflow() -> dict:
    workflow_path = (
        REPOSITORY_ROOT
        / ".github"
        / "workflows"
        / "ci.yml"
    )

    value = yaml.safe_load(
        workflow_path.read_text(
            encoding="utf-8"
        )
    )

    assert isinstance(value, dict)
    return value


def test_windows_ci_runs_full_suite_on_python_312() -> None:
    workflow = load_ci_workflow()
    jobs = workflow.get("jobs")

    assert isinstance(jobs, dict)

    windows_job = jobs.get("windows-tests")

    assert isinstance(windows_job, dict)
    assert windows_job.get("runs-on") == (
        "windows-latest"
    )

    steps = windows_job.get("steps")

    assert isinstance(steps, list)

    setup_step = next(
        step
        for step in steps
        if step.get("uses")
        == "actions/setup-python@v6"
    )

    assert setup_step["with"][
        "python-version"
    ] == "3.12"

    run_commands = "\n".join(
        str(step.get("run", ""))
        for step in steps
    )

    assert 'pip install -e ".[dev]"' in (
        run_commands
    )
    assert "pytest -q" in run_commands
    assert "binderranker doctor" in run_commands


def test_package_ci_verifies_optional_mcp_from_clean_wheel() -> None:
    workflow = load_ci_workflow()
    package_job = workflow["jobs"]["package"]
    run_commands = "\n".join(
        str(step.get("run", ""))
        for step in package_job["steps"]
    )

    assert 'pip install "mcp>=2,<3"' in run_commands
    assert "verify_installed_mcp_smoke.py" in run_commands
