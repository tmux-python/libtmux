# Releasing

## Version Policy

libtmux is pre-1.0. Minor version bumps may include breaking API changes.
Users should pin to `>=0.x,<0.y`.

## Release Process

Releases are triggered by git tags and published to PyPI via OIDC trusted publishing.

1. Update `CHANGES` with the release notes

2. Bump version in `src/libtmux/__about__.py`

3. Commit:

   ```console
   $ git commit -m "libtmux <version>"
   ```

4. Tag:

   ```console
   $ git tag v<version>
   ```

5. Push:

   ```console
   $ git push && git push --tags
   ```

6. CI builds and publishes to PyPI automatically via trusted publishing

## Changelog Format

The `CHANGES` file uses this format:

```text
libtmux <version> (<date>)
--------------------------

### What's new

- Description of feature (#issue)

### Bug fixes

- Description of fix (#issue)

### Breaking changes

- Description of break, migration path (#issue)
```
