# rpmautospec-koji

This package contains the Koji plugins for rpmautospec.

It processes submitted spec files which use the `%autorelease` and/or `%autochangelog` macros before
building the SRPM which is used to build the installable RPM package.

The package provides three plugins:

- `rpmautospec_builder` — a Koji **builder** plugin that preprocesses the spec file before the SRPM
  is built.
- `rpmautospec_tagger` — a Koji **hub** plugin that, when a final build is tagged or a draft is
  promoted, records the release by creating a git tag on the package's source repository.
- `rpmautospec_git_tag_task` — a Koji **builder** plugin that handles the `createGitTag` task spawned
  by the tagger to create and push the git tag.

The tagger and git-tag task are only active when git tag rules are configured (see
[Git tag rules](#git-tag-rules) below).

## Installation

### Builder plugins

The `rpmautospec_builder` (and optionally `rpmautospec_git_tag_task`) plugins are meant to be
installed on all Koji builder nodes running the `buildSRPMFromSCM` task, in
`/usr/lib/koji-builder-plugins/`. You can either directly place the files there or install the
`rpmautospec_koji` Python package and symlink the modules from their location in the Python
`site-packages` directory.

Enable them by adding `rpmautospec_builder` (and `rpmautospec_git_tag_task`) to the `plugins` line
in the `/etc/kojid/kojid.conf` configuration file for the Koji builders.

If git tag rules are defined, `rpmautospec_builder` will load and use them to determine namespaces
for rpmautospec. For builds where no rule matches (or if there are no rules), then the plugin will
use rpmautospec's default non-git-tag behavior.

### Hub plugin

The `rpmautospec_tagger` plugin is meant to be installed on the Koji hub in
`/usr/lib/koji-hub-plugins/`, the same way as the builder plugins.

Enable it by adding `rpmautospec_tagger` to the `Plugins` line in the `/etc/koji-hub/hub.conf`
configuration file for the Koji hub.

Note the tagger plugin only creates git tag tasks when both of the following apply:

* The build is final (non-draft), or is being promoted to final.
* At least one configured Koji tag rule matches.

This limits git tagging to builds actually on the path to release, following TagBuild or Promote
actions; drafts and builds in non-matching tags are left untagged.

## Git tag rules

The builder and hub git tag plugins read git tag rules from a `[rpmautospec]` section in their
respective configuration files:

- Builder: `/etc/kojid/plugins/rpmautospec.conf`
- Hub: `/etc/koji-hub/plugins/rpmautospec.conf`

A rule maps a Koji tag name to a git tag namespace. Each rule is written on its own line as
`<pattern> = <namespace>`, where `<pattern>` is a regular expression matched against the Koji tag
name (using a full match) and `<namespace>` is the resulting namespace, into which
regular-expression backreferences such as `\1` are expanded. Rules are newline-separated
(ConfigParser multiline values) and tried in order.

```ini
[rpmautospec]
git_tag_rules =
    (f\d+)-updates = fedora/\1
    eln = fedora/eln
```

Using `=` as the separator (instead of `:`) avoids conflicts with colons in non-capturing groups
(e.g. `(?:...)`) and using newlines avoids conflicts with commas in regex quantifiers
(e.g. `{2,3}`).

The two sides use the rules for complementary purposes:

- On the **hub**, the tagger matches the destination Koji tag of a completed build; a match means the
  build is a release and a git tag is created in the resulting namespace. Patterns here are typically
  narrow, so that only release tags trigger tagging.
- On the **builder**, the plugin matches the build tag to determine which namespace to read existing
  git tags from when computing the release number and changelog. Patterns here are typically broader,
  so that all builds for a target resolve to the same namespace.

If `git_tag_rules` is not set, the hub plugin creates no tags and the builder plugin falls back to
computing the release and changelog from the commit history.

## Changelog options

The builder plugin also supports optional changelog configuration in the same config file:

```ini
[rpmautospec]
git_tag_rules =
    (f\d+)(-.*)? = fedora/\1
changelog_mode = accumulated
changelog_use_highest_release_tag = false
```

- `changelog_mode`: either `accumulated` (default) or `tagged-only`. In `accumulated` mode, the
  changelog includes all commits between tags, attributed to their authors. In `tagged-only` mode,
  only tagged commits produce changelog entries.
- `changelog_use_highest_release_tag`: when `true`, if a commit has multiple release tags, use the
  highest release number. Default is `false` (use the lowest/first).
