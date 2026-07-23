import logging
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from rpmautospec_koji import rpmautospec_builder
from rpmautospec_koji.rpmautospec_builder import _get_config, _resolve_specfile, process_distgit_cb

FIXTURES_DIR = Path(__file__).parent / "fixtures"

DEFAULT_CONFIG = {
    "git_tag_rules": [],
    "changelog_mode": "accumulated",
    "changelog_use_highest_release_tag": False,
}


class TestGetConfig:
    """Test _get_config reads real config files."""

    def test_no_config_file(self, tmp_path):
        with mock.patch.object(rpmautospec_builder, "CONFIG_FILE", str(tmp_path / "missing.conf")):
            assert _get_config() == DEFAULT_CONFIG

    def test_empty_config(self, tmp_path):
        conf = tmp_path / "rpmautospec.conf"
        conf.write_text("")
        with mock.patch.object(rpmautospec_builder, "CONFIG_FILE", str(conf)):
            assert _get_config() == DEFAULT_CONFIG

    def test_with_rules(self):
        with mock.patch.object(rpmautospec_builder, "CONFIG_FILE", str(FIXTURES_DIR / "builder_full.conf")):
            result = _get_config()
        assert result["git_tag_rules"] == [(r"(f\d+)(-.*)?", r"fedora/\1")]

    def test_section_without_rules(self, tmp_path):
        conf = tmp_path / "rpmautospec.conf"
        conf.write_text("[rpmautospec]\n")
        with mock.patch.object(rpmautospec_builder, "CONFIG_FILE", str(conf)):
            assert _get_config() == DEFAULT_CONFIG

    def test_malformed_entry_skipped(self):
        with mock.patch.object(rpmautospec_builder, "CONFIG_FILE", str(FIXTURES_DIR / "builder_malformed.conf")):
            result = _get_config()
        assert result["git_tag_rules"] == [(r"(f\d+)-build", r"fedora/\1")]


class TestBuilderPlugin:
    """Test the rpmautospec builder plugin for Koji."""

    data_build_tag = {
        "id": 11522,
        "name": "f44-build",
        "arches": "armv7hl i686 x86_64 aarch64 ppc64le s390x",
    }

    @pytest.mark.parametrize(
        "testcase",
        (
            "normal",
            "other taskinfo method",
            "no features used",
            "namespace from build tag",
            "namespace from candidate tag",
            "no rules configured",
            "empty build tag",
        ),
    )
    @mock.patch("rpmautospec_koji.rpmautospec_builder.process_distgit")
    @mock.patch("rpmautospec_koji.rpmautospec_builder._get_config")
    def test_process_distgit_cb(self, get_config_fn, process_distgit_fn, testcase, caplog):
        taskinfo_method_responsible = testcase != "other taskinfo method"

        # Default: broad regex matches any f44-* build tag
        rules = [(r"(f\d+)(-.*)?", r"fedora/\1")]

        if testcase == "no rules configured":
            rules = []
        elif testcase == "namespace from candidate tag":
            # f44-updates-candidate also resolves to fedora/f44 (broad read regex)
            pass

        get_config_fn.return_value = {
            "git_tag_rules": rules,
            "changelog_mode": "accumulated",
            "changelog_use_highest_release_tag": False,
        }

        specfile_dir = "some dummy path"
        args = ["postSCMCheckout"]
        kwargs = {
            "build_tag": self.data_build_tag,
            "scratch": mock.MagicMock(),
            "srcdir": specfile_dir,
            "taskinfo": {"method": "buildSRPMFromSCM"},
        }

        process_distgit_fn.return_value = testcase != "no features used"

        if not taskinfo_method_responsible:
            kwargs["taskinfo"]["method"] = "not the method you're looking for"
        if testcase == "namespace from candidate tag":
            kwargs["build_tag"] = {"name": "f44-updates-candidate"}
        if testcase == "empty build tag":
            kwargs["build_tag"] = {"name": ""}

        with caplog.at_level(logging.DEBUG):
            process_distgit_cb(*args, **kwargs)

        if not taskinfo_method_responsible:
            process_distgit_fn.assert_not_called()
        elif testcase in ("namespace from build tag", "namespace from candidate tag"):
            process_distgit_fn.assert_called_once_with(
                specfile_dir, enable_caching=False, git_tag_namespace="fedora/f44",
                changelog_mode="accumulated", changelog_use_highest_release_tag=False
            )
        elif testcase in ("no rules configured", "empty build tag"):
            process_distgit_fn.assert_called_once_with(
                specfile_dir, enable_caching=False, git_tag_namespace=None,
                changelog_mode="accumulated", changelog_use_highest_release_tag=False
            )
        else:
            process_distgit_fn.assert_called_once_with(
                specfile_dir, enable_caching=False, git_tag_namespace="fedora/f44",
                changelog_mode="accumulated", changelog_use_highest_release_tag=False
            )

        if testcase == "no features used":
            assert "skipping" in caplog.text
        elif taskinfo_method_responsible:
            assert not caplog.records

    @mock.patch("rpmautospec_koji.rpmautospec_builder.process_distgit")
    @mock.patch("rpmautospec_koji.rpmautospec_builder._get_config")
    def test_resolve_mismatched_dirname_specfile(self, get_config_fn, process_distgit_fn):
        """Checkout dirs whose name doesn't match the spec file's
        must still resolve to the real spec file, not the directory.
        """
        get_config_fn.return_value = dict(DEFAULT_CONFIG)
        process_distgit_fn.return_value = True

        with tempfile.TemporaryDirectory(prefix="distro-packaging-pngcrush-") as srcdir:
            specfile = Path(srcdir) / "pngcrush.spec"
            specfile.write_text("Name: pngcrush\n")

            process_distgit_cb(
                "postSCMCheckout",
                build_tag={"name": "f44-build"},
                scratch=None,
                srcdir=srcdir,
                taskinfo={"method": "buildSRPMFromSCM"},
            )

            process_distgit_fn.assert_called_once_with(
                str(specfile),
                enable_caching=False,
                git_tag_namespace=None,
                changelog_mode="accumulated",
                changelog_use_highest_release_tag=False,
            )

    @mock.patch("rpmautospec_koji.rpmautospec_builder.process_distgit")
    @mock.patch("rpmautospec_koji.rpmautospec_builder._get_config")
    def test_resolve_dirname_matches_specfile(self, get_config_fn, process_distgit_fn):
        get_config_fn.return_value = dict(DEFAULT_CONFIG)
        process_distgit_fn.return_value = True

        with tempfile.TemporaryDirectory() as tmp:
            pkgdir = Path(tmp) / "somepkg"
            pkgdir.mkdir()
            specfile = pkgdir / "somepkg.spec"
            specfile.write_text("Name: somepkg\n")

            process_distgit_cb(
                "postSCMCheckout",
                build_tag={"name": "f44-build"},
                scratch=None,
                srcdir=str(pkgdir),
                taskinfo={"method": "buildSRPMFromSCM"},
            )

            process_distgit_fn.assert_called_once_with(
                str(specfile),
                enable_caching=False,
                git_tag_namespace=None,
                changelog_mode="accumulated",
                changelog_use_highest_release_tag=False,
            )


class TestResolveSpecfile:
    """Behavioral coverage for _resolve_specfile's discovery
    This is a mirror of kojid's BuildSRPMFromSCMTask logic/testing
    """

    # --- Single spec file, flat layout ---

    def test_single_specfile_mismatched_dirname_resolved(self, tmp_path):
        specfile = tmp_path / "pngcrush.spec"
        specfile.write_text("Name: pngcrush\n")

        assert _resolve_specfile(str(tmp_path)) == str(specfile)

    def test_single_specfile_matching_dirname_resolved(self, tmp_path):
        pkgdir = tmp_path / "pkgname"
        pkgdir.mkdir()
        specfile = pkgdir / "pkgname.spec"
        specfile.write_text("Name: pkgname\n")

        assert _resolve_specfile(str(pkgdir)) == str(specfile)

    def test_single_specfile_with_trailing_slash_in_srcdir(self, tmp_path):
        specfile = tmp_path / "pkg.spec"
        specfile.write_text("Name: pkg\n")

        assert _resolve_specfile(str(tmp_path) + "/") == str(specfile)

    # --- SPECS/ subdir layout ---

    def test_single_specfile_in_specs_subdir_resolved(self, tmp_path):
        specs_dir = tmp_path / "SPECS"
        specs_dir.mkdir()
        specfile = specs_dir / "pngcrush.spec"
        specfile.write_text("Name: pngcrush\n")

        assert _resolve_specfile(str(tmp_path)) == str(specfile)

    def test_flat_specfile_preferred_over_specs_subdir(self, tmp_path):
        """If a spec file exists directly in srcdir, SPECS/ is skipped"""
        flat_spec = tmp_path / "pkg.spec"
        flat_spec.write_text("Name: pkg\n")
        specs_dir = tmp_path / "SPECS"
        specs_dir.mkdir()
        (specs_dir / "other.spec").write_text("Name: other\n")

        assert _resolve_specfile(str(tmp_path)) == str(flat_spec)

    def test_multiple_in_specs_subdir_with_dirname_match_resolved(self, tmp_path):
        pkgdir = tmp_path / "mypkg"
        specs_dir = pkgdir / "SPECS"
        specs_dir.mkdir(parents=True)
        matching = specs_dir / "mypkg.spec"
        matching.write_text("Name: mypkg\n")
        (specs_dir / "other.spec").write_text("Name: other\n")

        assert _resolve_specfile(str(pkgdir)) == str(matching)

    # --- Multiple spec files, flat layout ---

    def test_multiple_specfiles_no_dirname_match_falls_back_to_srcdir(self, tmp_path):
        (tmp_path / "a.spec").write_text("Name: a\n")
        (tmp_path / "b.spec").write_text("Name: b\n")

        assert _resolve_specfile(str(tmp_path)) == str(tmp_path)

    def test_multiple_specfiles_with_dirname_match_resolved(self, tmp_path):
        """When there are multiple spec files, the one matching the
        checkout dir wins.
        """
        pkgdir = tmp_path / "winner"
        pkgdir.mkdir()
        matching = pkgdir / "winner.spec"
        matching.write_text("Name: winner\n")
        (pkgdir / "loser.spec").write_text("Name: loser\n")

        assert _resolve_specfile(str(pkgdir)) == str(matching)

    # --- Zero spec files ---

    def test_empty_dir_falls_back_to_srcdir(self, tmp_path):
        assert _resolve_specfile(str(tmp_path)) == str(tmp_path)

    def test_dir_with_non_spec_files_falls_back_to_srcdir(self, tmp_path):
        (tmp_path / "sources").write_text("stuff\n")
        (tmp_path / "fetch").write_text("#!/bin/sh\n")

        assert _resolve_specfile(str(tmp_path)) == str(tmp_path)

    def test_empty_specs_subdir_falls_back_to_srcdir(self, tmp_path):
        (tmp_path / "SPECS").mkdir()
        assert _resolve_specfile(str(tmp_path)) == str(tmp_path)

    # --- Nonexistent / inaccessible paths ---

    def test_nonexistent_dir_falls_back_to_srcdir(self):
        missing = "/no/such/directory/at/all"
        assert _resolve_specfile(missing) == missing

    def test_file_path_instead_of_dir_falls_back_to_srcdir(self, tmp_path):
        """srcdir should be a directory. If it's a file then
        globbing "<file>/*.spec" can't match anything so we
        fall back rather than raising.
        """
        not_a_dir = tmp_path / "not_a_directory"
        not_a_dir.write_text("just a file\n")

        assert _resolve_specfile(str(not_a_dir)) == str(not_a_dir)
