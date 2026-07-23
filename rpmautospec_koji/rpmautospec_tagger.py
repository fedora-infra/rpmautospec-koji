"""Hub plugin: spawn a createGitTag task when a build is tagged.

When a build is tagged into a qualifying destination, this plugin queues
a builder task to push a git tag of the form {namespace}/{name}-{version}-{release}
to the source SCM.

Configuration (/etc/koji-hub/plugins/rpmautospec.conf):

    [rpmautospec]
    # Rules: {regex}:{template} (first match wins, comma-separated)
    # Regex capture groups (\1, \2) are expanded in the template.
    git_tag_rules = (f\\d+)-updates:fedora/\\1, eln:fedora/eln
    # would result in f44-updates builds going to fedora/f44

Note: This requires your Koji have permission to write back to git SCMs.
You may prefer to use a separate microservice depending on your Koji's
and git security models.
If you do not want this enabled, do not set git_tag_rules in Hub config.
(builder config is fine, that only triggers tag *read* for build prep)
"""


import logging

import koji
from koji.plugin import callback
from kojihub import context, make_task
from rpmautospec_core.nvr_util import format_namespaced_nvr

from rpmautospec_koji.util import match_tag_rules, parse_tag_rules

log = logging.getLogger(__name__)

CONFIG_FILE = "/etc/koji-hub/plugins/rpmautospec.conf"
_config = None


def _get_config():
    """Read plugin config. Cached after first call."""
    global _config
    if _config is not None:
        return _config
    _config = {"git_tag_rules": parse_tag_rules(CONFIG_FILE)}
    return _config


def _resolve_namespace(tag_name):
    """Match a Koji tag name against rules and return the resolved namespace, or None."""
    config = _get_config()
    return match_tag_rules(tag_name, config["git_tag_rules"])


@callback("postTag")
def create_git_tag_on_tag(cbtype, *, tag, build, **kws):
    """Queue a createGitTag task when a final build is tagged into a qualifying target."""
    if build.get("draft"):
        return

    _try_create_tag(tag.get("name", ""), build)


@callback("postBuildPromote")
def create_git_tag_on_promote(cbtype, *, build, **kws):
    """Queue a createGitTag task when a draft build is promoted in a qualifying tag."""
    config = _get_config()
    if not config["git_tag_rules"]:
        return

    try:
        build_tags = context.handlers.call("listTags", build=build.get("build_id"))
        for bt in build_tags:
            if _resolve_namespace(bt.get("name", "")) is not None:
                _try_create_tag(bt["name"], build)
                break
    except Exception:
        log.exception("Failed to look up tags for promoted build %s", build.get("nvr"))


def _try_create_tag(tag_name, build):
    """Attempt to spawn a createGitTag task for a build in the given tag."""
    namespace = _resolve_namespace(tag_name)
    if namespace is None:
        return

    source = build.get("source")
    if not source or "#" not in source:
        log.debug("Build %s has no source SCM commit, skipping git tag", build.get("nvr"))
        return

    # Strip dist suffix from release (e.g. "2.fc44" -> "2") and validate
    release = build["release"].split(".", 1)[0]
    if not release.isdigit():
        log.debug("Build %s has non-numeric release %s, skipping git tag", build.get("nvr"), release)
        return

    git_tag_name = format_namespaced_nvr(
        namespace, build["name"], build["version"], release,
        epoch=str(build["epoch"]) if build.get("epoch") is not None else "",
    )

    try:
        task_id = make_task(
            "createGitTag",
            [source, git_tag_name],
            priority=koji.PRIO_DEFAULT + 5,
            channel="default",
        )
        log.info("Spawned createGitTag task %s for %s (%s)", task_id, build["nvr"], git_tag_name)
    except Exception:
        log.error("Failed to spawn createGitTag task for %s", build.get("nvr"), exc_info=True)
