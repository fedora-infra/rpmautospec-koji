from pathlib import Path

import pytest
from rpmautospec_koji.util import match_tag_rules, parse_config, parse_tag_rules

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestMatchTagRules:
    """Tests for match_tag_rules with regex capture groups."""

    @pytest.mark.parametrize(
        "tag_name, expected",
        [
            ("f44-updates", "fedora/f44"),
            ("f43-updates", "fedora/f43"),
            ("f44-updates-candidate", None),

            ("random-tag", None),
        ],
        ids=["fedora-f44", "fedora-f43", "candidate-no-match", "random-no-match"],
    )
    def test_multi_rule(self, tag_name, expected):
        rules = [
            (r"(f\d+)-updates", r"fedora/\1"),
        ]
        assert match_tag_rules(tag_name, rules) == expected

    def test_static_template(self):
        rules = [(r"f\d+-updates", "distro/release")]
        assert match_tag_rules("f44-updates", rules) == "distro/release"

    def test_multiple_capture_groups(self):
        rules = [(r"(\w+)-(\d+)-updates", r"fedora/\1\2")]
        assert match_tag_rules("fedora-44-updates", rules) == "fedora/fedora44"

    def test_empty_rules(self):
        assert match_tag_rules("f44-updates", []) is None

    def test_first_match_wins(self):
        rules = [
            (r"f44-updates", "specific/f44"),
            (r"f\d+-updates", r"generic/\1"),
        ]
        assert match_tag_rules("f44-updates", rules) == "specific/f44"

    def test_builder_pattern(self):
        """Builder uses build tag (e.g. f44-build) to derive read namespace."""
        rules = [(r"(f\d+)-build", r"fedora/\1")]
        assert match_tag_rules("f44-build", rules) == "fedora/f44"
        assert match_tag_rules("f43-build", rules) == "fedora/f43"
        assert match_tag_rules("random-tag", rules) is None


class TestParseTagRules:
    """Tests for parse_tag_rules config file parsing."""

    def test_reads_newline_separated_rules(self):
        rules = parse_tag_rules(str(FIXTURES_DIR / "tagger_full.conf"))
        assert rules == [(r"(f\d+)-updates", r"fedora/\1")]

    def test_skips_malformed_entries(self):
        rules = parse_tag_rules(str(FIXTURES_DIR / "tagger_malformed.conf"))
        assert rules == [(r"(f\d+)-updates", r"fedora/\1")]

    def test_builder_config(self):
        rules = parse_tag_rules(str(FIXTURES_DIR / "builder_full.conf"))
        assert rules == [(r"(f\d+)(-.*)?", r"fedora/\1")]

    def test_missing_file(self, tmp_path):
        rules = parse_tag_rules(str(tmp_path / "nonexistent.conf"))
        assert rules == []

    def test_no_section(self, tmp_path):
        conf = tmp_path / "empty.conf"
        conf.write_text("")
        assert parse_tag_rules(str(conf)) == []

    def test_regex_with_quantifier(self, tmp_path):
        """Comma in {2,3} doesn't break parsing (newline-separated)."""
        conf = tmp_path / "quantifier.conf"
        conf.write_text("[rpmautospec]\ngit_tag_rules =\n    (f\\d{2,3})-build = fedora/\\1\n")
        rules = parse_tag_rules(str(conf))
        assert rules == [(r"(f\d{2,3})-build", r"fedora/\1")]

    def test_regex_with_colon(self, tmp_path):
        """Colon in regex (e.g. non-capturing group) doesn't break parsing."""
        conf = tmp_path / "colon.conf"
        conf.write_text("[rpmautospec]\ngit_tag_rules =\n    (?:f|el)(\\d+)-updates = distro/\\1\n")
        rules = parse_tag_rules(str(conf))
        assert rules == [(r"(?:f|el)(\d+)-updates", r"distro/\1")]


class TestParseConfig:
    """Tests for parse_config with changelog options."""

    def test_defaults(self, tmp_path):
        conf = tmp_path / "empty.conf"
        conf.write_text("[rpmautospec]\n")
        result = parse_config(str(conf))
        assert result["git_tag_rules"] == []
        assert result["changelog_mode"] == "accumulated"
        assert result["changelog_use_highest_release_tag"] is False

    def test_all_options(self, tmp_path):
        conf = tmp_path / "full.conf"
        conf.write_text(
            "[rpmautospec]\n"
            "git_tag_rules =\n"
            "    (f\\d+)-updates = fedora/\\1\n"
            "changelog_mode = tagged-only\n"
            "changelog_use_highest_release_tag = true\n"
        )
        result = parse_config(str(conf))
        assert result["git_tag_rules"] == [(r"(f\d+)-updates", r"fedora/\1")]
        assert result["changelog_mode"] == "tagged-only"
        assert result["changelog_use_highest_release_tag"] is True

    def test_highest_release_various_truthy(self, tmp_path):
        for val in ("yes", "1", "True", "TRUE"):
            conf = tmp_path / "t.conf"
            conf.write_text(f"[rpmautospec]\nchangelog_use_highest_release_tag = {val}\n")
            assert parse_config(str(conf))["changelog_use_highest_release_tag"] is True

    def test_highest_release_falsy(self, tmp_path):
        conf = tmp_path / "f.conf"
        conf.write_text("[rpmautospec]\nchangelog_use_highest_release_tag = false\n")
        assert parse_config(str(conf))["changelog_use_highest_release_tag"] is False
