"""Tests against the committed files in examples/.

These assert on real files rather than temp fixtures, so the examples cannot
drift from the library's behavior. If someone edits examples/ and breaks it,
CI catches it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import yaml_io
from yaml_io import CircularImportError, ExportError

EXAMPLES = Path(__file__).parent.parent / "examples"

V12_RETRY = {"attempts": 3, "backoff": "exponential", "initial_delay_seconds": 2}
V13_RETRY = {"attempts": 5, "backoff": "linear", "initial_delay_seconds": 1}


def test_examples_directory_exists():
    assert EXAMPLES.is_dir(), "examples/ is referenced by the README and must ship"


def test_acme_resolves_to_v12_policies():
    data = yaml_io.load(EXAMPLES / "workspaces/acme/actions.yml")
    assert data["workspace"] == "acme"
    assert data["jobs"][0]["retry"] == V12_RETRY
    assert data["jobs"][0]["timeout"] == {"seconds": 300, "on_expire": "fail"}


def test_globex_resolves_to_v13_policies():
    data = yaml_io.load(EXAMPLES / "workspaces/globex/actions.yml")
    assert data["workspace"] == "globex"
    assert data["jobs"][0]["retry"] == V13_RETRY
    assert data["jobs"][0]["timeout"] == {"seconds": 900, "on_expire": "warn"}


def test_the_two_channels_differ_only_by_their_import_line():
    """The selling point: one line decides which version a workspace runs."""
    acme = (EXAMPLES / "workspaces/acme/actions.yml").read_text().splitlines()
    globex = (EXAMPLES / "workspaces/globex/actions.yml").read_text().splitlines()

    def significant(lines):
        """Drop blanks and prose comments, but keep #! directives."""
        kept = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") and not stripped.startswith("#!"):
                continue
            kept.append(line)
        return kept

    acme_body = significant(acme)
    globex_body = significant(globex)

    differing = [
        (a, b) for a, b in zip(acme_body, globex_body) if a != b
    ]
    # Only the import line and the workspace name differ.
    assert len(differing) == 2
    assert any("#!import" in a for a, _ in differing)


def test_one_anchor_is_reused_across_every_job():
    """retry_policy is written once upstream and lands in both jobs."""
    data = yaml_io.load(EXAMPLES / "workspaces/acme/actions.yml")
    assert [job["retry"] for job in data["jobs"]] == [V12_RETRY, V12_RETRY]


def test_explicit_and_wildcard_exports_yield_the_same_names():
    """prod-default names its exports; prod-beta uses `v.*`. Same surface."""
    _, default_exports = yaml_io.load_imports_exports(
        str(EXAMPLES / "packages/prod-default.yml")
    )
    _, beta_exports = yaml_io.load_imports_exports(
        str(EXAMPLES / "packages/prod-beta.yml")
    )
    assert set(default_exports) == set(beta_exports)
    assert set(default_exports) == {"retry_policy", "timeout_policy", "notify_policy"}


def test_package_files_are_directives_only():
    for package in ("prod-default.yml", "prod-beta.yml"):
        assert yaml_io.load(EXAMPLES / "packages" / package) is None


def test_version_files_load_standalone():
    """The version files have no imports, so they load on their own."""
    data = yaml_io.load(EXAMPLES / "versions/v1.2/actions.yml")
    assert data["policies"]["retry"] == V12_RETRY


def test_repointing_a_package_repoints_its_workspace(tmp_path):
    """Copy the tree, change the one import line, confirm everything moves."""
    import shutil

    copied = tmp_path / "examples"
    shutil.copytree(EXAMPLES, copied)

    package = copied / "packages/prod-default.yml"
    package.write_text(
        package.read_text().replace("v1.2/actions.yml", "v1.3/actions.yml")
    )

    data = yaml_io.load(copied / "workspaces/acme/actions.yml")
    assert data["jobs"][0]["retry"] == V13_RETRY, "workspace should follow the package"


def test_show_script_runs_clean():
    """examples/show.py is the first thing a new user runs."""
    # Hand the subprocess whatever path this test process is using, so the
    # script resolves yaml_io from src/ or from site-packages either way.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)

    result = subprocess.run(
        [sys.executable, str(EXAMPLES / "show.py")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "acme" in result.stdout and "globex" in result.stdout


# --------------------------------------------------------------------------
# The failure modes examples/README.md promises
# --------------------------------------------------------------------------


def _copy(tmp_path):
    import shutil

    copied = tmp_path / "examples"
    shutil.copytree(EXAMPLES, copied)
    return copied


def test_typo_in_a_package_export_is_caught(tmp_path):
    copied = _copy(tmp_path)
    package = copied / "packages/prod-default.yml"
    package.write_text(package.read_text().replace("v.retry_policy", "v.retry_polciy"))

    with pytest.raises(ExportError, match="retry_polciy"):
        yaml_io.load(copied / "workspaces/acme/actions.yml")


def test_packages_importing_each_other_is_caught(tmp_path):
    copied = _copy(tmp_path)
    (copied / "packages/prod-default.yml").write_text(
        "#!import prod-beta.yml as b\n#!export b.retry_policy\n"
    )
    (copied / "packages/prod-beta.yml").write_text(
        "#!import prod-default.yml as d\n#!export d.retry_policy\n"
    )

    with pytest.raises(CircularImportError):
        yaml_io.load(copied / "workspaces/acme/actions.yml")
