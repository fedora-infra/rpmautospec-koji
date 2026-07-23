import subprocess
import tempfile

import koji.tasks

__all__ = ("CreateGitTagTask",)


class CreateGitTagTask(koji.tasks.BaseTaskHandler):
    """Handler for git tag creation/writeback tasks

    Shallow-clones the SCM, creates a tag on the desired commit, and pushes.
    """

    Methods = ["createGitTag"]

    _taskWeight = 0.2

    def handler(self, scm_url, tag_name):
        """Create and push a git tag.

        :param scm_url: Koji SCM URL (e.g. "git+https://src.fedoraproject.org/rpms/pkg#hash")
        :param tag_name: tag to create (e.g. "f44-pkg-1.0-2")
        """
        if "#" not in scm_url:
            raise koji.GenericError(f"SCM URL missing commit hash: {scm_url}")

        url_part, commit = scm_url.rsplit("#", 1)
        # Strip SCM scheme prefix (e.g. "git+https://...")
        if "+" in url_part and "://" in url_part:
            url_part = url_part.split("+", 1)[1]

        with tempfile.TemporaryDirectory() as tmpdir:
            self._run_git(["init", "--bare", tmpdir])
            self._run_git(["-C", tmpdir, "remote", "add", "--", "origin", url_part])
            self._run_git(["-C", tmpdir, "fetch", "--depth=1", "origin", "--", commit])
            self._run_git(["-C", tmpdir, "tag", "-a", "-m", tag_name, "--", tag_name, commit])
            self._run_git(["-C", tmpdir, "push", "origin", "--", tag_name])

        self.logger.info("Created git tag %s on %s", tag_name, commit[:12])

    def _run_git(self, args, timeout=60):
        """Run a git command, raising on failure."""
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise koji.GenericError(f"git {args[0]} failed: {stderr}")
