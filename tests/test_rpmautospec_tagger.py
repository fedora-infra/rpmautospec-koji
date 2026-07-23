import logging
import sys
from unittest import mock

import pytest

sys.modules["kojihub"] = mock.MagicMock()

from pathlib import Path

from rpmautospec_koji import rpmautospec_tagger
from rpmautospec_koji.rpmautospec_tagger import _get_config, create_git_tag_on_tag


class TestGetConfig:
    """Test _get_config reads real config files."""

    def setup_method(self):
        rpmautospec_tagger._config = None

    def test_no_config_file(self, tmp_path):
        rpmautospec_tagger._config = None
        with mock.patch.object(rpmautospec_tagger, "CONFIG_FILE", str(tmp_path / "missing.conf")):
            assert _get_config() == {"git_tag_rules": []}

    def test_full_config(self):
        rpmautospec_tagger._config = None
        conf = str(Path(__file__).parent / "fixtures" / "tagger_full.conf")
        with mock.patch.object(rpmautospec_tagger, "CONFIG_FILE", conf):
            result = _get_config()
        assert result["git_tag_rules"] == [
            (r"(f\d+)-updates", r"fedora/\1"),
        ]


    def test_malformed_entry_skipped(self):
        rpmautospec_tagger._config = None
        conf = str(Path(__file__).parent / "fixtures" / "tagger_malformed.conf")
        with mock.patch.object(rpmautospec_tagger, "CONFIG_FILE", conf):
            result = _get_config()
        assert result["git_tag_rules"] == [(r"(f\d+)-updates", r"fedora/\1")]


    def test_section_without_rules(self, tmp_path):
        conf = tmp_path / "rpmautospec.conf"
        conf.write_text("[rpmautospec]\n")
        rpmautospec_tagger._config = None
        with mock.patch.object(rpmautospec_tagger, "CONFIG_FILE", str(conf)):
            assert _get_config() == {"git_tag_rules": []}

    def test_caches_result(self, tmp_path):
        conf = tmp_path / "rpmautospec.conf"
        conf.write_text("[rpmautospec]\ngit_tag_rules =\n    (f\\d+)-updates = fedora/\\1\n")
        rpmautospec_tagger._config = None
        with mock.patch.object(rpmautospec_tagger, "CONFIG_FILE", str(conf)):
            first = _get_config()
            second = _get_config()
        assert first is second
        assert first["git_tag_rules"] == [(r"(f\d+)-updates", r"fedora/\1")]


class TestTaggerPlugin:
    """Test the rpmautospec tagger hub plugin."""

    sample_build = {
        "name": "pkg",
        "version": "1.0",
        "release": "2.fc44",
        "epoch": None,
        "nvr": "pkg-1.0-2.fc44",
        "source": "git+https://src.example.com/rpms/pkg#abc123",
        "task_id": 12345,
    }

    def _patch_config(self, config):
        rpmautospec_tagger._config = None
        return mock.patch.object(rpmautospec_tagger, "_get_config", return_value=config)

    @pytest.mark.parametrize(
        "testcase",
        (
            "matching tag",
            "non-matching tag",
            "no rules configured",
            "no source in build",
            "non-numeric release",
            "epoch zero",
            "make_task exception",
        ),
    )
    @mock.patch("rpmautospec_koji.rpmautospec_tagger.make_task")
    def test_git_tag_on_koji_tag(self, make_task_fn, testcase, caplog):
        # Strict write rule: only f44-updates triggers
        config = {"git_tag_rules": [(r"(f\d+)-updates", r"fedora/\1")]}

        tag = {"name": "f44-updates"}
        build = dict(self.sample_build)

        if testcase == "non-matching tag":
            tag = {"name": "f44-updates-candidate"}
        elif testcase == "no rules configured":
            config["git_tag_rules"] = []
        elif testcase == "no source in build":
            build["source"] = None
        elif testcase == "non-numeric release":
            build["release"] = "rc1.fc44"
        elif testcase == "epoch zero":
            build["epoch"] = 0
        elif testcase == "make_task exception":
            make_task_fn.side_effect = Exception("connection failed")

        with self._patch_config(config), caplog.at_level(logging.DEBUG):
            create_git_tag_on_tag("postTag", tag=tag, build=build, user={"name": "releng"})

        if testcase == "matching tag":
            make_task_fn.assert_called_once_with(
                "createGitTag",
                [build["source"], "fedora/f44/pkg-1.0-2"],
                priority=mock.ANY,
                channel="default",
            )
        elif testcase == "epoch zero":
            make_task_fn.assert_called_once_with(
                "createGitTag",
                [build["source"], "fedora/f44/pkg-1.0-2"],
                priority=mock.ANY,
                channel="default",
            )
        elif testcase == "make_task exception":
            make_task_fn.assert_called_once()
            assert "Failed to spawn" in caplog.text
        else:
            make_task_fn.assert_not_called()

    @pytest.mark.parametrize(
        "koji_tag, expected_namespace",
        [
            ("f44-updates", "fedora/f44"),
            ("f43-updates", "fedora/f43"),
            ("f44-updates-candidate", None),

        ],
        ids=["fedora-f44", "fedora-f43", "candidate-no-match"],
    )
    @mock.patch("rpmautospec_koji.rpmautospec_tagger.make_task")
    def test_multi_rule_resolution(self, make_task_fn, koji_tag, expected_namespace):
        """Multiple rules: multiple Fedora releases on same Koji."""
        config = {"git_tag_rules": [
            (r"(f\d+)-updates", r"fedora/\1"),
        ]}
        build = dict(self.sample_build)

        with self._patch_config(config):
            create_git_tag_on_tag("postTag", tag={"name": koji_tag}, build=build, user={"name": "releng"})

        if expected_namespace:
            expected_tag = f"{expected_namespace}/pkg-1.0-2"
            make_task_fn.assert_called_once_with(
                "createGitTag",
                [build["source"], expected_tag],
                priority=mock.ANY,
                channel="default",
            )
        else:
            make_task_fn.assert_not_called()

    @mock.patch("rpmautospec_koji.rpmautospec_tagger.make_task")
    def test_tag_skips_draft_build(self, make_task_fn):
        config = {"git_tag_rules": [(r"(f\d+)-updates", r"fedora/\1")]}
        build = dict(self.sample_build, draft=True)

        with self._patch_config(config):
            create_git_tag_on_tag("postTag", tag={"name": "f44-updates"}, build=build, user={"name": "releng"})

        make_task_fn.assert_not_called()

    @pytest.mark.parametrize(
        "testcase",
        ("matching tag", "non-matching tag", "no rules", "no source", "exception"),
    )
    @mock.patch("rpmautospec_koji.rpmautospec_tagger.make_task")
    def test_promote(self, make_task_fn, testcase, caplog):
        config = {"git_tag_rules": [(r"(f\d+)-updates", r"fedora/\1")]}
        build = dict(self.sample_build, build_id=99)
        kojihub_mock = sys.modules["kojihub"]

        if testcase == "matching tag":
            kojihub_mock.context.handlers.call.return_value = [{"name": "f44-updates"}]
        elif testcase == "non-matching tag":
            kojihub_mock.context.handlers.call.return_value = [{"name": "f44-updates-candidate"}]
        elif testcase == "no rules":
            config = {"git_tag_rules": []}
        elif testcase == "no source":
            build["source"] = None
            kojihub_mock.context.handlers.call.return_value = [{"name": "f44-updates"}]
        elif testcase == "exception":
            kojihub_mock.context.handlers.call.side_effect = Exception("connection lost")

        with self._patch_config(config), caplog.at_level(logging.DEBUG):
            from rpmautospec_koji.rpmautospec_tagger import create_git_tag_on_promote
            create_git_tag_on_promote("postBuildPromote", build=build, user={"name": "releng"})

        kojihub_mock.context.handlers.call.side_effect = None

        if testcase == "matching tag":
            make_task_fn.assert_called_once_with(
                "createGitTag",
                [build["source"], "fedora/f44/pkg-1.0-2"],
                priority=mock.ANY,
                channel="default",
            )
        elif testcase == "exception":
            make_task_fn.assert_not_called()
            assert "Failed to look up tags" in caplog.text
        else:
            make_task_fn.assert_not_called()

    @mock.patch("rpmautospec_koji.rpmautospec_tagger.make_task")
    def test_promote_multiple_matching_tags_uses_first(self, make_task_fn):
        """When multiple tags match, only the first triggers a createGitTag task."""
        config = {"git_tag_rules": [(r"(f\d+)-updates", r"fedora/\1")]}
        build = dict(self.sample_build, build_id=99)
        kojihub_mock = sys.modules["kojihub"]
        kojihub_mock.context.handlers.call.return_value = [
            {"name": "f44-updates"},
            {"name": "f43-updates"},
        ]

        with self._patch_config(config):
            from rpmautospec_koji.rpmautospec_tagger import create_git_tag_on_promote
            create_git_tag_on_promote("postBuildPromote", build=build, user={"name": "releng"})

        kojihub_mock.context.handlers.call.side_effect = None

        # Only one task spawned (first match wins)
        make_task_fn.assert_called_once_with(
            "createGitTag",
            [build["source"], "fedora/f44/pkg-1.0-2"],
            priority=mock.ANY,
            channel="default",
        )
