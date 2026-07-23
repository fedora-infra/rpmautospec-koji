import glob
import logging
import os

from koji.plugin import callback

from rpmautospec import process_distgit
from rpmautospec_koji.util import match_tag_rules, parse_config

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

CONFIG_FILE = "/etc/kojid/plugins/rpmautospec.conf"


def _get_config():
    """Read plugin config."""
    return parse_config(CONFIG_FILE)


def _resolve_specfile(srcdir):
    """Resolve the actual spec file to process within an SCM checkout dir.

    PkgHistoryProcessor's directory mode assumes the checkout directory is
    named after the package, i.e. it looks for "<dirname>/<dirname>.spec".
    That assumption doesn't hold for SCM layouts where the checkout
    directory name doesn't match the spec file's.

    1. Look for "*.spec" directly in srcdir.
    2. If none found, also look under "srcdir/SPECS/*.spec"
    3. If exactly one spec file was found (in either location), use it.
    4. If more than one was found, prefer one whose base name matches the
       checkout directory's base name.
    5. Otherwise (zero matches, or multiple with no matching name), fall
       back to returning srcdir unchanged and let process_distgit's own
       directory-mode handling raise/behave as it already does.

    This is effectively Koji's SRPM-from-SCM task logic.

    :param srcdir: the SCM checkout directory
    :return: path to the resolved spec file, or srcdir unchanged
    """
    spec_files = glob.glob(os.path.join(srcdir, "*.spec"))

    if not spec_files:
        spec_files = glob.glob(os.path.join(srcdir, "SPECS", "*.spec"))

    if len(spec_files) == 1:
        return spec_files[0]
    if len(spec_files) > 1:
        dirname = os.path.basename(os.path.normpath(srcdir))
        for candidate in (
            os.path.join(srcdir, f"{dirname}.spec"),
            os.path.join(srcdir, "SPECS", f"{dirname}.spec"),
        ):
            if candidate in spec_files:
                return candidate

    return srcdir


@callback("postSCMCheckout")
def process_distgit_cb(cb_type, *, srcdir, taskinfo, **kwargs):
    # This callback should only run for SRPM builds from SCM;
    # i.e. maven and image builds don't have spec files.
    if taskinfo["method"] != "buildSRPMFromSCM":
        return

    git_tag_namespace = None
    config = _get_config()
    if config["git_tag_rules"]:
        build_tag = kwargs.get("build_tag", {})
        tag_name = build_tag.get("name", "")
        if tag_name:
            git_tag_namespace = match_tag_rules(tag_name, config["git_tag_rules"])

    if not process_distgit(
        _resolve_specfile(srcdir),
        enable_caching=False,
        git_tag_namespace=git_tag_namespace,
        changelog_mode=config["changelog_mode"],
        changelog_use_highest_release_tag=config["changelog_use_highest_release_tag"],
    ):
        log.info("No %autorelease/%autochangelog features used, skipping.")
