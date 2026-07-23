from unittest import mock

import koji
import pytest
from rpmautospec_koji.rpmautospec_git_tag_task import CreateGitTagTask


class TestCreateGitTagTask:

    def _make_task(self):
        session = mock.MagicMock()
        options = mock.MagicMock()
        options.workdir = "/tmp"
        task = CreateGitTagTask(
            id=1,
            method="createGitTag",
            params=[["git+https://src.example.com/rpms/pkg#abc123", "f44-pkg-1.0-2"], {}],
            session=session,
            options=options,
        )
        return task

    @mock.patch("rpmautospec_koji.rpmautospec_git_tag_task.subprocess.run")
    def test_handler_success(self, mock_run):
        mock_run.return_value = mock.MagicMock(returncode=0)
        task = self._make_task()
        task.handler("git+https://src.example.com/rpms/pkg#abc123", "f44-pkg-1.0-2")

        assert mock_run.call_count == 5
        calls = mock_run.call_args_list
        # init --bare
        assert "init" in calls[0][0][0]
        assert "--bare" in calls[0][0][0]
        # remote add
        assert "remote" in calls[1][0][0]
        assert "https://src.example.com/rpms/pkg" in calls[1][0][0]
        # fetch specific commit
        assert "fetch" in calls[2][0][0]
        assert "abc123" in calls[2][0][0]
        # tag
        assert "tag" in calls[3][0][0]
        assert "f44-pkg-1.0-2" in calls[3][0][0]
        assert "abc123" in calls[3][0][0]
        # push
        assert "push" in calls[4][0][0]
        assert "f44-pkg-1.0-2" in calls[4][0][0]

    @mock.patch("rpmautospec_koji.rpmautospec_git_tag_task.subprocess.run")
    def test_handler_no_scheme_prefix(self, mock_run):
        mock_run.return_value = mock.MagicMock(returncode=0)
        task = self._make_task()
        task.handler("https://src.example.com/rpms/pkg#abc123", "f44-pkg-1.0-2")

        calls = mock_run.call_args_list
        assert "https://src.example.com/rpms/pkg" in calls[1][0][0]

    @mock.patch("rpmautospec_koji.rpmautospec_git_tag_task.subprocess.run")
    def test_handler_custom_scheme_prefix(self, mock_run):
        mock_run.return_value = mock.MagicMock(returncode=0)
        task = self._make_task()
        task.handler(
            "custom+https://git.example.com/v1/repos/pkg#abc123",
            "f44-pkg-1.0-2",
        )

        calls = mock_run.call_args_list
        assert "https://git.example.com/v1/repos/pkg" in calls[1][0][0]

    @mock.patch("rpmautospec_koji.rpmautospec_git_tag_task.subprocess.run")
    def test_handler_git_failure(self, mock_run):
        mock_run.return_value = mock.MagicMock(
            returncode=128, stderr=b"fatal: repository not found"
        )
        task = self._make_task()
        with pytest.raises(koji.GenericError, match="repository not found"):
            task.handler("git+https://src.example.com/rpms/pkg#abc123", "f44-pkg-1.0-2")

    def test_handler_missing_hash(self):
        task = self._make_task()
        with pytest.raises(koji.GenericError, match="missing commit hash"):
            task.handler("git+https://src.example.com/rpms/pkg", "f44-pkg-1.0-2")

    @mock.patch("rpmautospec_koji.rpmautospec_git_tag_task.subprocess.run")
    def test_handler_timeout(self, mock_run):
        """TimeoutExpired from subprocess propagates as an error."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=60)
        task = self._make_task()
        with pytest.raises(subprocess.TimeoutExpired):
            task.handler("git+https://src.example.com/rpms/pkg#abc123", "fedora/f44/pkg-1.0-2")


class TestTaggerReaderRoundTrip:
    """Verify tagger output is parseable by the reader (nvr_util)."""

    def test_format_then_parse(self):
        """format_namespaced_nvr → parse_namespaced_nvr round-trip."""
        from rpmautospec_core.nvr_util import format_namespaced_nvr, parse_namespaced_nvr

        # Simple case
        tag = format_namespaced_nvr("fedora/f44", "mesa", "26.0.7", "2")
        parsed = parse_namespaced_nvr(tag, "fedora/f44")
        assert parsed["name"] == "mesa"
        assert parsed["version"] == "26.0.7"
        assert parsed["release"] == "2"
        assert parsed["epoch"] == ""

    def test_format_then_parse_with_epoch(self):
        from rpmautospec_core.nvr_util import format_namespaced_nvr, parse_namespaced_nvr

        tag = format_namespaced_nvr("fedora/f44", "httpd", "2.4.57", "1", epoch="2")
        parsed = parse_namespaced_nvr(tag, "fedora/f44")
        assert parsed["name"] == "httpd"
        assert parsed["version"] == "2.4.57"
        assert parsed["release"] == "1"
        assert parsed["epoch"] == "2"

    def test_dist_suffix_stripping_compat(self):
        """Tagger strips dist suffix before formatting; reader parses the result."""
        from rpmautospec_core.nvr_util import format_namespaced_nvr, parse_namespaced_nvr

        # Tagger does: release = "93.fc44".split(".")[0] = "93"
        release_from_koji = "93.fc44"
        stripped = release_from_koji.split(".")[0]
        tag = format_namespaced_nvr("fedora/f44", "pkg", "1.0", stripped)
        parsed = parse_namespaced_nvr(tag, "fedora/f44")
        assert parsed["release"] == "93"

    def test_epoch_zero_omitted(self):
        """Epoch 0 is the RPM default and is not included in the tag."""
        from rpmautospec_core.nvr_util import format_namespaced_nvr, parse_namespaced_nvr

        tag = format_namespaced_nvr("fedora/f44", "pkg", "1.0", "1", epoch="0")
        # epoch 0 is implicit, not encoded in the tag
        assert tag == "fedora/f44/pkg-1.0-1"
        parsed = parse_namespaced_nvr(tag, "fedora/f44")
        assert parsed["epoch"] == ""
        assert parsed["name"] == "pkg"
