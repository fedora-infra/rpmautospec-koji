"""Shared utilities for rpmautospec Koji plugins."""

import logging
import re

import koji

logger = logging.getLogger(__name__)


def match_tag_rules(tag_name, rules):
    """Match a tag name against rules and expand the namespace template.

    Rules are (regex_pattern, template) tuples. The template can reference
    capture groups from the pattern using \\1, \\2, etc.

    Example:
        rules = [("(f\\d+)-updates", "fedora/\\1")]
        match_tag_rules("f44-updates", rules) -> "fedora/f44"

    :param tag_name: the Koji tag name to match
    :param rules: list of (pattern, template) tuples
    :return: expanded namespace string, or None if no rule matches
    """
    for pattern, template in rules:
        m = re.fullmatch(pattern, tag_name)
        if m:
            return m.expand(template)
    return None


def parse_tag_rules(config_path):
    """Read git_tag_rules from a Koji plugin config file.

    Rules are newline-separated in the config file (ConfigParser multiline),
    with '=' separating pattern from template:

        [rpmautospec]
        git_tag_rules =
            (f\\d+)-updates = fedora/\\1
            (f\\d{2,3})-build = fedora/\\1

    Using '=' as separator avoids conflicts with ':' in regex (e.g. (?:...))
    and ',' in quantifiers (e.g. {2,3}).

    :param config_path: path to the .conf file
    :return: list of (pattern, template) tuples
    """
    cp = koji.read_config_files(config_path, raw=True)
    rules = []
    if not cp.has_section("rpmautospec"):
        return rules
    if not cp.has_option("rpmautospec", "git_tag_rules"):
        return rules

    raw = cp.get("rpmautospec", "git_tag_rules")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            logger.warning(f"Skipping malformed git_tag_rules entry: {line}")
            continue
        pattern, template = line.split("=", 1)
        rules.append((pattern.strip(), template.strip()))
    return rules


def parse_config(config_path):
    """Read full rpmautospec plugin config.

    :param config_path: path to the .conf file
    :return: dict with git_tag_rules, changelog_mode, changelog_use_highest_release_tag
    """
    result = {
        "git_tag_rules": parse_tag_rules(config_path),
        "changelog_mode": "accumulated",
        "changelog_use_highest_release_tag": False,
    }
    cp = koji.read_config_files(config_path, raw=True)
    if cp and cp.has_section("rpmautospec"):
        if cp.has_option("rpmautospec", "changelog_mode"):
            result["changelog_mode"] = cp.get("rpmautospec", "changelog_mode")
        if cp.has_option("rpmautospec", "changelog_use_highest_release_tag"):
            val = cp.get("rpmautospec", "changelog_use_highest_release_tag")
            result["changelog_use_highest_release_tag"] = val.lower() in ("true", "yes", "1")
    return result
