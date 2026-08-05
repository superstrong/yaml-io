# Examples

A worked config tree showing what yaml-io is for. Every file here is real and
loadable, and `tests/test_examples.py` asserts against it, so these files
cannot drift from the library's actual behavior.

## Run it

```
pip install yaml-io
python examples/show.py
```

## The tree

```
versions/v1.2/actions.yml     defines the anchors (source of truth)
versions/v1.3/actions.yml     same anchor names, newer values

packages/prod-default.yml     imports v1.2, re-exports it   <- stable channel
packages/prod-beta.yml        imports v1.3, re-exports it   <- beta channel

workspaces/acme/actions.yml     imports prod-default
workspaces/globex/actions.yml   imports prod-beta
```

Data flows upward through that list. A workspace never names a version, only a
package. A package names exactly one version, in one line.

## What each layer is for

**`versions/`** holds the anchor definitions, and nothing else imports into it.
Anchors defined directly in a file are exported automatically, so these files
need no `#!export` directives.

**`packages/`** is the indirection that makes versioning cheap. To move every
workspace on the stable channel from v1.2 to v1.3, edit one line in
`prod-default.yml`. No workspace file changes.

These two files also show the two export styles. `prod-default.yml` names each
anchor explicitly, which pins the package's surface and makes it reviewable.
`prod-beta.yml` uses `#!export v.*`, which forwards everything and keeps up
automatically as the upstream version file grows.

Note that a package file is nothing but directives. It has no YAML content of
its own, so loading one directly returns `None`. That is expected: its job is
to forward anchors, not to hold data.

**`workspaces/`** is where the values get used. `acme` and `globex` are
identical except for their import line, which is the whole point: one line
decides which policy version a workspace runs.

## What to notice

- No repetition. `retry_policy` is written once and used in four places.
- No ordering constraint. The anchors live two files away, so aliases can
  appear anywhere in a workspace file. Plain YAML requires an anchor to be
  defined before it is referenced.
- No version numbers downstream. Workspaces are insulated from version bumps.

## Try breaking it

Each of these produces a specific, named error rather than silent wrong data:

| Edit | Result |
|---|---|
| Change `#!export v.retry_policy` to `v.retry_polciy` in `prod-default.yml` | `ExportError`, listing the names that do exist |
| Point `prod-default.yml` at a file that isn't there | `ImportResolutionError`, naming the importing file and line |
| Make `prod-default.yml` import `prod-beta.yml`, and `prod-beta.yml` import `prod-default.yml` | `CircularImportError` with the full chain |
| Use `*base.retry_policy` in a workspace whose package doesn't export it | PyYAML's undefined-alias error, with the real filename and line number |
