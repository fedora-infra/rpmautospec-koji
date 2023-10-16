# rpmautospec-koji

This package contains the Koji builder plugin for rpmautospec.

It processes submitted spec file which use the %autorelease and/or %autochangelog before building
the SRPM which is used to build the installable RPM package.

## Installation

The Koji plugin `rpmautospec_builder` is meant to be installed on all Koji builder nodes running the
`buildSRPMFromSCM` task in `/usr/lib/koji-builder-plugins/`. You can either directly place the file
there or install the `rpmautospec_koji` Python package and symlink the module from its location in
the Python `site-packages` directory.

The plugin can be enabled by adding `rpmautospec_builder` to the `plugins` line in the
`/etc/kojid/kojid.conf` configuration file for the Koji builders.
