"""Tests for tool confinement (agents stay inside the repo).

The tool wrappers are CrewAI Tool objects (not directly callable), so
tests invoke the wrapped functions via .func. The module-level ROOT
is monkeypatched to a temp repo so wrapper tests never touch the
real checkout.
"""

import pytest

pytest.importorskip("crewai")

from scrum_crew import tools


@pytest.fixture
def repo(tmp_path):
    root = (tmp_path / "repo").resolve()
    root.mkdir(parents=True)
    return root


def test_resolve_within_repo(repo):
    assert tools._resolve_within_repo(
        "outputs/x.md", repo) == repo / "outputs" / "x.md"
    assert tools._resolve_within_repo(
        str(repo / "a.py"), repo) == repo / "a.py"
    assert tools._resolve_within_repo("../escape.md", repo) is None
    assert tools._resolve_within_repo("/etc/passwd", repo) is None
    assert tools._resolve_within_repo("a/../../escape.md", repo) is None


def test_resolve_blocks_symlink_escape(repo, tmp_path):
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (repo / "link").symlink_to(outside, target_is_directory=True)
    assert tools._resolve_within_repo("link/evil.md", repo) is None


def test_allowed_test_path(repo):
    (repo / "tests").mkdir()
    assert tools._allowed_test_path("tests", repo)
    assert tools._allowed_test_path("tests/test_a.py", repo)
    assert tools._allowed_test_path("tests/test_a.py::test_b", repo)
    assert tools._allowed_test_path(str(repo / "tests" / "test_a.py"), repo)
    assert not tools._allowed_test_path("demo_app", repo)
    assert not tools._allowed_test_path("../other", repo)
    assert not tools._allowed_test_path("/etc", repo)


def test_write_file_denied_outside_repo(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "ROOT", repo)
    outside = tmp_path / "evil.md"
    result = tools.write_file.func(f"{outside}\nhello")
    assert result.startswith("denied:")
    assert not outside.exists()


def test_write_file_allowed_and_logged(repo, monkeypatch):
    monkeypatch.setattr(tools, "ROOT", repo)
    result = tools.write_file.func("outputs/note.md\nhello")
    assert result.startswith("wrote ")
    assert (repo / "outputs" / "note.md").read_text() == "hello"
    log = (repo / "outputs" / "tool-calls.log").read_text()
    assert "write" in log and "outputs/note.md" in log


def test_read_file_denied_outside_repo(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "ROOT", repo)
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret")
    result = tools.read_file.func(str(secret))
    assert result.startswith("denied:")


def test_run_tests_denied_outside_tree(repo, monkeypatch):
    monkeypatch.setattr(tools, "ROOT", repo)
    result = tools.run_tests.func("demo_app")
    assert result.startswith("denied:")
