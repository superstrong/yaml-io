import os
import tempfile
import unittest
from yaml_io.loader import load_imports_exports

class TestYAMLIO(unittest.TestCase):
    def create_temp_file(self, content):
        """Helper: create a temporary YAML file with given content."""
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, 'w') as tmp:
            tmp.write(content)
        return path

    def test_simple_yaml(self):
        # A YAML file with no custom directives.
        content = "a: 1\nb: 2\n"
        file_path = self.create_temp_file(content)
        data, exported = load_imports_exports(file_path)
        self.assertEqual(data, {'a': 1, 'b': 2})
        # No anchors defined, so no exports.
        self.assertEqual(exported, {})

    def test_local_anchor_export(self):
        # Test that a locally defined anchor is automatically exported.
        content = (
            "a: &anchor1 1\n"
            "b: 2\n"
            "#!export anchor1\n"
        )
        file_path = self.create_temp_file(content)
        data, exported = load_imports_exports(file_path)
        self.assertEqual(data, {'a': 1, 'b': 2})
        # The local anchor "anchor1" should be exported.
        self.assertIn('anchor1', exported)
        self.assertEqual(exported['anchor1'], 1)

    def test_import_and_export(self):
        # Create a child YAML file that defines an anchor to export.
        child_content = (
            "c: &child_anchor 100\n"
            "#!export child.child_anchor\n"
        )
        # Create a temporary directory to hold both files.
        with tempfile.TemporaryDirectory() as tmpdir:
            child_file = os.path.join(tmpdir, "child.yaml")
            parent_file = os.path.join(tmpdir, "parent.yaml")
            with open(child_file, "w") as f:
                f.write(child_content)
            # Parent file imports the child.
            parent_content = (
                "#!import child.yaml as child\n"
                "d: 2\n"
            )
            with open(parent_file, "w") as f:
                f.write(parent_content)
            data, exported = load_imports_exports(parent_file)
            self.assertEqual(data, {'d': 2})
            self.assertIn('child_anchor', exported)
            self.assertEqual(exported['child_anchor'], 100)

    def test_circular_import(self):
        # Create two files that import each other to test circular import detection.
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "file1.yaml")
            file2 = os.path.join(tmpdir, "file2.yaml")
            content1 = "#!import file2.yaml as file2\na: 1\n"
            content2 = "#!import file1.yaml as file1\nb: 2\n"
            with open(file1, "w") as f:
                f.write(content1)
            with open(file2, "w") as f:
                f.write(content2)
            with self.assertRaises(ValueError):
                load_imports_exports(file1)

if __name__ == "__main__":
    unittest.main()
