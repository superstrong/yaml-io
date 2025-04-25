# YAML-io

This Python library enables YAML anchors to be imported from external files via custom directives. It also enables imported anchors to be re-exported, so one file can unify many imports and them export them as one source.

This has a few benefits:

- Re-use the same aliases in multiple files without repeating yourself
- Use aliases without worrying about reordering your file, because the anchors are defined elsewhere
- Use multiple layers of imports to logically separate concerns and create versions of files that update all downstream files simultaneously.

## Setup

1. If a user calls yaml.load(...) and passes in:

- A path to a file on disk

    → _try_file_path_and_load calls load_imports_exports(...) on that file, recursively resolving #!import statements.

- A file object with a valid .name attribute that actually exists on disk

    → same as above.

- Otherwise, the library just falls back to normal PyYAML behavior (e.g., inline YAML in a string, or a non‑file input).

2. There are no code changes.

```python
import yaml
import yaml_io  # triggers the patch

with open("some_yaml.yaml") as f:
    data = yaml.safe_load(f)  # Now automatically supports #!import, #!export
```

## Usage

Mark directives in your YAML like:

```yaml
#!import ../../global/prod-default/base-package.yml as base
```

and refer to imported anchors as:

```yaml
- *base.progress_check_model
```

Anchors defined directly in the file are automatically available to downstream files. Imported anchors need to be re‑exported with a directive like:

```yaml
#!export base.progress_check_model
```

## Versioning Example

A versioned file containing all the anchors we want to define once. Imagine we have multiple files and many anchors.

```yaml
./global/versions/v1.2/actions.yml

- &anchor1
- &anchor2
```

A router-like file where we refer to the versioned files and export them for re-use:
```
./global/prod-default/base-package.yml

#!import ../../versions/v1.2/acions.yml as a

#!export a.anchor1, a.anchor2
```

The most downstream file where all anchors are resolved and used as aliases, such as this example `./workspace/acme/actions.yml`:

```yaml
#!import ../../global/prod-default/base-package.yml as base

- *base.anchor1
- *base.anchor2
```

- One advantage to using the `base-package` intermediary is the ability to change everything from v1.2 to v1.3 with a small number of changes when you're ready.

- One advantage to using the `prod-default` folder is you can create other folders, such as `prod-beta` or `uat-default` and point specific files there instead for testing.
