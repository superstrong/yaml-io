"""Tests for yaml-io.

Each test builds a real file tree under ``tmp_path``, because import resolution
is relative to a file's own directory and cannot be exercised from strings.
"""

import textwrap

import pytest
import yaml

import yaml_io
from yaml_io import (
    AnchorCollisionError,
    CircularImportError,
    DirectiveError,
    ExportError,
    ImportResolutionError,
)


@pytest.fixture
def tree(tmp_path):
    """Write a {relative path: contents} mapping to disk, returning the root."""

    def build(files):
        for relative, contents in files.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(contents).lstrip("\n"), encoding="utf-8")
        return tmp_path

    return build


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------


def test_plain_yaml_without_directives(tree):
    root = tree({"a.yml": "a: 1\nb: 2\n"})
    assert yaml_io.load(root / "a.yml") == {"a": 1, "b": 2}


def test_load_accepts_a_file_object(tree):
    root = tree({"a.yml": "a: 1\n"})
    with open(root / "a.yml", encoding="utf-8") as handle:
        assert yaml_io.load(handle) == {"a": 1}


def test_load_accepts_a_yaml_string():
    assert yaml_io.load("a: 1\nb: 2\n") == {"a": 1, "b": 2}
    assert yaml_io.load("a: 1") == {"a": 1}


def test_mistyped_path_raises_rather_than_parsing_as_text(tree):
    """'congif.yml' must not quietly load as the string 'congif.yml'."""
    root = tree({"real.yml": "a: 1\n"})
    with pytest.raises(FileNotFoundError):
        yaml_io.load(str(root / "congif.yml"))


def test_load_accepts_a_pathlib_path(tree):
    root = tree({"a.yml": "a: 1\n"})
    assert yaml_io.load(root / "a.yml") == {"a": 1}


def test_anchors_still_work_within_a_single_file(tree):
    root = tree({"a.yml": "base: &b {x: 1}\ncopy: *b\n"})
    assert yaml_io.load(root / "a.yml") == {"base": {"x": 1}, "copy": {"x": 1}}


# --------------------------------------------------------------------------
# Import and export
# --------------------------------------------------------------------------


def test_import_resolves_an_alias_across_files(tree):
    root = tree(
        {
            "child.yml": "c: &child_anchor 100\n",
            "parent.yml": "#!import child.yml as child\nd: *child.child_anchor\n",
        }
    )
    assert yaml_io.load(root / "parent.yml") == {"d": 100}


def test_local_anchors_are_exported_automatically(tree):
    root = tree(
        {
            "child.yml": "c: &only 1\n",
            "parent.yml": "#!import child.yml as c\nv: *c.only\n",
        }
    )
    assert yaml_io.load(root / "parent.yml") == {"v": 1}


def test_imported_anchors_need_explicit_reexport(tree):
    """An imported anchor is not visible two levels up unless re-exported."""
    root = tree(
        {
            "leaf.yml": "l: &deep 1\n",
            "middle.yml": "#!import leaf.yml as leaf\nm: 0\n",
            "top.yml": "#!import middle.yml as mid\nv: *mid.deep\n",
        }
    )
    with pytest.raises(yaml.YAMLError, match="undefined alias"):
        yaml_io.load(root / "top.yml")


def test_reexport_strips_the_prefix(tree):
    root = tree(
        {
            "leaf.yml": "l: &deep 1\n",
            "middle.yml": "#!import leaf.yml as leaf\n#!export leaf.deep\n",
            "top.yml": "#!import middle.yml as mid\nv: *mid.deep\n",
        }
    )
    assert yaml_io.load(root / "top.yml") == {"v": 1}


def test_readme_three_level_versioning_example(tree):
    """The worked example from the README, end to end."""
    root = tree(
        {
            "global/versions/v1.2/actions.yml": """
                defs:
                  one: &anchor1 {name: first, retries: 3}
                  two: &anchor2 {name: second, retries: 5}
            """,
            "global/prod-default/base-package.yml": """
                #!import ../versions/v1.2/actions.yml as a

                #!export a.anchor1, a.anchor2
            """,
            "workspace/acme/actions.yml": """
                #!import ../../global/prod-default/base-package.yml as base

                steps:
                  - *base.anchor1
                  - *base.anchor2
            """,
        }
    )
    assert yaml_io.load(root / "workspace/acme/actions.yml") == {
        "steps": [
            {"name": "first", "retries": 3},
            {"name": "second", "retries": 5},
        ]
    }


def test_directive_only_file_loads_as_none(tree):
    """The router pattern: a file that is nothing but directives."""
    root = tree(
        {
            "leaf.yml": "l: &deep 1\n",
            "router.yml": "#!import leaf.yml as leaf\n#!export leaf.deep\n",
        }
    )
    assert yaml_io.load(root / "router.yml") is None


def test_wildcard_reexport(tree):
    root = tree(
        {
            "leaf.yml": "a: &one 1\nb: &two 2\n",
            "middle.yml": "#!import leaf.yml as c\n#!export c.*\n",
            "top.yml": "#!import middle.yml as m\nv: [*m.one, *m.two]\n",
        }
    )
    assert yaml_io.load(root / "top.yml") == {"v": [1, 2]}


def test_multiple_exports_on_separate_lines(tree):
    root = tree(
        {
            "leaf.yml": "a: &one 1\nb: &two 2\n",
            "middle.yml": "#!import leaf.yml as c\n#!export c.one\n#!export c.two\n",
            "top.yml": "#!import middle.yml as m\nv: [*m.one, *m.two]\n",
        }
    )
    assert yaml_io.load(root / "top.yml") == {"v": [1, 2]}


def test_quoted_import_path_with_spaces(tree):
    root = tree(
        {
            "my dir/leaf.yml": "a: &one 1\n",
            "top.yml": '#!import "my dir/leaf.yml" as l\nv: *l.one\n',
        }
    )
    assert yaml_io.load(root / "top.yml") == {"v": 1}


# --------------------------------------------------------------------------
# Import graph shape
# --------------------------------------------------------------------------


def test_diamond_import_is_not_circular(tree):
    """A and B both import D. This previously failed as a false cycle."""
    root = tree(
        {
            "d.yml": "base: &shared {x: 1}\n",
            "b.yml": "#!import d.yml as d\n#!export d.shared\n",
            "c.yml": "#!import d.yml as d\n#!export d.shared\n",
            "a.yml": """
                #!import b.yml as b
                #!import c.yml as c
                left: *b.shared
                right: *c.shared
            """,
        }
    )
    assert yaml_io.load(root / "a.yml") == {
        "left": {"x": 1},
        "right": {"x": 1},
    }


def test_shared_import_is_parsed_only_once(tree, monkeypatch):
    root = tree(
        {
            "d.yml": "base: &shared {x: 1}\n",
            "b.yml": "#!import d.yml as d\n#!export d.shared\n",
            "c.yml": "#!import d.yml as d\n#!export d.shared\n",
            "a.yml": "#!import b.yml as b\n#!import c.yml as c\nv: *b.shared\n",
        }
    )
    reads = []
    real_open = open

    def counting_open(path, *args, **kwargs):
        reads.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", counting_open)
    yaml_io.load(root / "a.yml")
    assert sum(1 for path in reads if path.endswith("d.yml")) == 1


def test_true_circular_import_is_detected(tree):
    root = tree(
        {
            "file1.yml": "#!import file2.yml as f2\na: 1\n",
            "file2.yml": "#!import file1.yml as f1\nb: 2\n",
        }
    )
    with pytest.raises(CircularImportError, match="circular import"):
        yaml_io.load(root / "file1.yml")


def test_self_import_is_detected(tree):
    root = tree({"a.yml": "#!import a.yml as me\nk: 1\n"})
    with pytest.raises(CircularImportError):
        yaml_io.load(root / "a.yml")


def test_circular_import_still_raises_value_error(tree):
    """Back-compat: callers written against 0.1.x caught bare ValueError."""
    root = tree(
        {
            "file1.yml": "#!import file2.yml as f2\na: 1\n",
            "file2.yml": "#!import file1.yml as f1\nb: 2\n",
        }
    )
    with pytest.raises(ValueError):
        yaml_io.load(root / "file1.yml")


# --------------------------------------------------------------------------
# Multi-document streams
# --------------------------------------------------------------------------


def test_load_all_with_imports_in_every_document(tree):
    root = tree(
        {
            "leaf.yml": "a: &one 1\nb: &two 2\n",
            "top.yml": """
                #!import leaf.yml as l
                first: *l.one
                ---
                second: *l.two
            """,
        }
    )
    assert yaml_io.load_all(root / "top.yml") == [
        {"first": 1},
        {"second": 2},
    ]


def test_local_anchors_do_not_leak_between_documents(tree):
    """Standard YAML scoping: an anchor from document one is gone in document two."""
    root = tree({"top.yml": "a: &local 1\n---\nb: *local\n"})
    with pytest.raises(yaml.YAMLError, match="undefined alias"):
        yaml_io.load_all(root / "top.yml")


def test_load_rejects_multi_document_stream(tree):
    root = tree({"top.yml": "a: 1\n---\nb: 2\n"})
    with pytest.raises(yaml.YAMLError, match="expected a single document"):
        yaml_io.load(root / "top.yml")


def test_anchors_from_all_documents_are_exported(tree):
    root = tree(
        {
            "leaf.yml": "a: &one 1\n---\nb: &two 2\n",
            "top.yml": "#!import leaf.yml as l\nv: [*l.one, *l.two]\n",
        }
    )
    assert yaml_io.load(root / "top.yml") == {"v": [1, 2]}


# --------------------------------------------------------------------------
# Errors and diagnostics
# --------------------------------------------------------------------------


def test_unknown_export_raises(tree):
    root = tree(
        {
            "leaf.yml": "a: &one 1\n",
            "top.yml": "#!import leaf.yml as l\n#!export l.nope\n",
        }
    )
    with pytest.raises(ExportError, match="unknown anchor 'l.nope'"):
        yaml_io.load(root / "top.yml")


def test_unknown_local_export_raises(tree):
    root = tree({"top.yml": "a: &one 1\n#!export nope\n"})
    with pytest.raises(ExportError, match="unknown anchor 'nope'"):
        yaml_io.load(root / "top.yml")


def test_missing_import_names_the_importing_file(tree):
    root = tree({"top.yml": "#!import ./missing.yml as m\nk: 1\n"})
    with pytest.raises(ImportResolutionError) as excinfo:
        yaml_io.load(root / "top.yml")
    message = str(excinfo.value)
    assert "missing.yml" in message
    assert "line 1" in message


def test_malformed_directive_raises(tree):
    root = tree({"top.yml": "#!import bad syntax here\nk: 1\n"})
    with pytest.raises(DirectiveError, match="line 1"):
        yaml_io.load(root / "top.yml")


def test_export_collision_raises(tree):
    root = tree(
        {
            "x.yml": "a: &dup 1\n",
            "y.yml": "a: &dup 2\n",
            "top.yml": """
                #!import x.yml as x
                #!import y.yml as y
                #!export x.dup, y.dup
            """,
        }
    )
    with pytest.raises(AnchorCollisionError, match="dup"):
        yaml_io.load(root / "top.yml")


def test_error_line_numbers_match_the_source_file(tree):
    """Directive lines are blanked, not deleted, so line numbers do not shift."""
    root = tree(
        {
            "leaf.yml": "a: &one 1\n",
            "top.yml": """
                #!import leaf.yml as l
                #!export l.one
                key: value
                bad: [unclosed
            """,
        }
    )
    with pytest.raises(yaml.YAMLError) as excinfo:
        yaml_io.load(root / "top.yml")
    message = str(excinfo.value)
    assert "line 4" in message
    assert "top.yml" in message


def test_undefined_alias_reports_the_real_filename(tree):
    root = tree({"top.yml": "a: *nope\n"})
    with pytest.raises(yaml.YAMLError) as excinfo:
        yaml_io.load(root / "top.yml")
    assert "top.yml" in str(excinfo.value)


# --------------------------------------------------------------------------
# Alias grammar
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        "a: &bad.name 1\n",  # dots are not allowed in anchor definitions
        "a: &x 1\nb: *x.y.z\n",  # at most one dot in an alias
        "a: &x 1\nb: *.y\n",  # no leading dot
    ],
)
def test_invalid_anchor_grammar_is_rejected(tree, document):
    root = tree({"top.yml": document})
    with pytest.raises(yaml.YAMLError):
        yaml_io.load(root / "top.yml")


def test_trailing_dot_alias_is_rejected(tree):
    root = tree({"top.yml": "a: &x 1\nb: *x.\n"})
    with pytest.raises(yaml.YAMLError):
        yaml_io.load(root / "top.yml")


def test_hyphens_allowed_in_anchor_names(tree):
    root = tree(
        {
            "leaf.yml": "a: &my-anchor 1\n",
            "top.yml": "#!import leaf.yml as my-pkg\nv: *my-pkg.my-anchor\n",
        }
    )
    assert yaml_io.load(root / "top.yml") == {"v": 1}


def test_directive_inside_a_block_scalar_is_left_alone(tree):
    root = tree(
        {
            "top.yml": """
                script: |
                  #!import not a directive
                  echo hello
                other: 1
            """
        }
    )
    assert yaml_io.load(root / "top.yml") == {
        "script": "#!import not a directive\necho hello\n",
        "other": 1,
    }


# --------------------------------------------------------------------------
# PyYAML integration and isolation
# --------------------------------------------------------------------------


def test_importing_yaml_io_does_not_patch_pyyaml():
    """The 0.1.x monkeypatch broke yaml.safe_load for every other library."""
    assert yaml.safe_load("a: 1") == {"a": 1}
    assert yaml.load("a: 1", Loader=yaml.SafeLoader) == {"a": 1}
    assert list(yaml.safe_load_all("a: 1\n---\nb: 2")) == [{"a": 1}, {"b": 2}]
    assert yaml.full_load("a: 1") == {"a": 1}


def test_plain_pyyaml_still_rejects_dotted_aliases():
    """The extended grammar must not leak out of yaml_io's own loader."""
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("a: &x 1\nb: *x.y\n")


def test_loader_works_through_pyyaml_directly(tree):
    root = tree(
        {
            "leaf.yml": "a: &one 1\n",
            "top.yml": "#!import leaf.yml as l\nv: *l.one\n",
        }
    )
    with open(root / "top.yml", encoding="utf-8") as handle:
        assert yaml.load(handle, Loader=yaml_io.YamlIOLoader) == {"v": 1}


def test_loader_is_safe(tree):
    """YamlIOLoader inherits SafeConstructor and must not build objects."""
    root = tree({"top.yml": "!!python/object/apply:os.system ['echo pwned']\n"})
    with pytest.raises(yaml.YAMLError):
        yaml_io.load(root / "top.yml")


# --------------------------------------------------------------------------
# Backwards compatibility
# --------------------------------------------------------------------------


def test_load_imports_exports_returns_data_and_nodes(tree):
    root = tree({"top.yml": "a: &one 1\nb: 2\n"})
    data, exported = yaml_io.load_imports_exports(str(root / "top.yml"))
    assert data == {"a": 1, "b": 2}
    assert "one" in exported
    assert isinstance(exported["one"], yaml.Node)
