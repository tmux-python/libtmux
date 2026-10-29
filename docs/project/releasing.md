# Releasing

## Version Policy

libtmux is pre-1.0. Minor version bumps may include breaking API changes.
Users should pin to `>=0.x,<0.y`.

## Release Process

Follow the [contributor release checklist] for version updates, commits, and
publication to [PyPI]. The owner creates and pushes release tags; tags trigger
the publishing workflow.

## Changelog Format

Follow [the changelog policy] for the `CHANGES` structure, unreleased entries,
and release-time lead paragraphs.

[contributor release checklist]: https://github.com/tmux-python/libtmux/blob/master/.github/CONTRIBUTING.md#releasing
[the changelog policy]: https://github.com/tmux-python/libtmux/blob/master/.github/WRITING.md#the-changelog
[PyPI]: https://pypi.org/project/libtmux/
