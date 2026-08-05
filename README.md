# YAML-io

This Python library enables YAML anchors to be imported from external files via custom directives. It also enables imported anchors to be re-exported, so one file can unify many imports and then export them as one source.

This has a few benefits:

- Re-use the same aliases in multiple files without repeating yourself
- Use aliases without worrying about reordering your file, because the anchors are defined elsewhere
- Use multiple layers of imports to logically separate concerns and create versions of files that update all downstream files simultaneously

## Install

```
pip install yaml-io
```

Requires Python 3.11+ and PyYAML 5.4+.

## Usage

```python
import yaml_io

data = yaml_io.load("workspace/acme/actions.yml")
```

`yaml_io.load` accepts a path, an open file object, or a YAML string. For multi-document streams, use `yaml_io.load_all`, which returns a list.

Importing `yaml_io` has no side effects. It does not patch PyYAML, so `yaml.safe_load` and everything else in your process behaves exactly as it always did.

If you would rather go through PyYAML directly, pass the loader explicitly:

```python
import yaml
import yaml_io

with open("workspace/acme/actions.yml") as f:
    data = yaml.load(f, Loader=yaml_io.YamlIOLoader)
```

`YamlIOLoader` is built on PyYAML's `SafeConstructor`, so it is as safe as `yaml.safe_load`.

`load_imports_exports` is also present, returning `(data, exported)` where `exported` maps names to `yaml.Node` objects. It is deprecated in favor of `yaml_io.load`.

## Try it

The [`examples/`](examples/) directory holds a complete, working config tree: two versioned policy files, two package files that select between them, and two workspaces that differ only by which package they import.

```
git clone https://github.com/superstrong/yaml-io
cd yaml-io
pip install yaml-io
python examples/show.py
```

That prints both workspaces fully resolved, showing the same alias landing on different values depending on one import line. See [`examples/README.md`](examples/README.md) for a walkthrough, including how to break it on purpose and what error each mistake produces.

## Directives

Mark directives in your YAML like:

```yaml
#!import ../../global/prod-default/base-package.yml as base
```

and refer to imported anchors as:

```yaml
- *base.progress_check_model
```

Anchors defined directly in a file are exported automatically. Imported anchors are not: to pass one further downstream, re-export it explicitly.

```yaml
#!export base.progress_check_model
```

A re-exported anchor loses its original prefix and picks up the prefix of whoever imports it next. Export several at once with commas, or use `*` to re-export everything from one import:

```yaml
#!export base.model_a, base.model_b
#!export base.*
```

Rules worth knowing:

- Import paths are relative to the file containing the directive.
- Directives must start at column 0. Anything indented is an ordinary YAML comment, so `#!import` inside a block scalar is left alone.
- Paths containing spaces must be quoted: `#!import "my dir/base.yml" as base`.
- Directives are file-scoped. In a multi-document file, imported anchors are available in every document, while anchors defined inside a document stay in that document, matching YAML's own scoping.
- Anchor names (`&name`) may not contain dots. Aliases (`*prefix.name`) may contain exactly one.

## Versioning Example

A versioned file containing all the anchors we want to define once. Imagine we have multiple files and many anchors.

```yaml
# ./global/versions/v1.2/actions.yml

defs:
  one: &anchor1 {name: first, retries: 3}
  two: &anchor2 {name: second, retries: 5}
```

A router-like file where we refer to the versioned files and export them for re-use:

```yaml
# ./global/prod-default/base-package.yml

#!import ../versions/v1.2/actions.yml as a

#!export a.anchor1, a.anchor2
```

This file has no content of its own, only directives. Loading it directly returns `None`, which is expected; its job is to forward anchors.

The most downstream file, where all anchors are resolved and used as aliases, such as `./workspace/acme/actions.yml`:

```yaml
# ./workspace/acme/actions.yml

#!import ../../global/prod-default/base-package.yml as base

steps:
  - *base.anchor1
  - *base.anchor2
```

Loading that last file yields:

```python
{"steps": [{"name": "first", "retries": 3},
           {"name": "second", "retries": 5}]}
```

- One advantage to using the `base-package` intermediary is the ability to change everything from v1.2 to v1.3 with a small number of changes when you're ready.

- One advantage to using the `prod-default` folder is you can create other folders, such as `prod-beta` or `uat-default`, and point specific files there instead for testing.

The same file may be imported along several paths. A diamond, where two intermediaries both import one versioned file, resolves once and is shared.

## Errors

All errors inherit from `yaml_io.YamlIOError`, itself a `ValueError`.

| Error | Raised when |
|---|---|
| `CircularImportError` | A file transitively imports itself |
| `ImportResolutionError` | An `#!import` target cannot be read |
| `DirectiveError` | An `#!import` or `#!export` line is malformed |
| `ExportError` | An `#!export` names an anchor that does not exist |
| `AnchorCollisionError` | Two distinct anchors compete for one name |

Errors from the YAML itself are PyYAML's own, and report the real filename and the correct line number, since directive lines are blanked rather than removed.
