import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("build_runtime", Path(__file__).resolve().parents[1] / "build-runtime.py")
build_runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_runtime)


class SourcePatchTests(unittest.TestCase):
    def test_pristine_source_is_patched_once_without_guessing_reverse_direction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("original synthetic source\n")
            patch = root / "change.patch"
            patch.write_text("--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n"
                             "-original synthetic source\n+corrected synthetic source\n")
            build_runtime.patch_source(root, patch)
            self.assertEqual(source.read_text(), "corrected synthetic source\n")
            build_runtime.patch_source(root, patch)
            self.assertEqual(source.read_text(), "corrected synthetic source\n")

    def test_incompatible_source_is_not_silently_reported_as_patched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("different synthetic source\n")
            patch = root / "change.patch"
            patch.write_text("--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-old\n+new\n")
            with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                build_runtime.patch_source(root, patch)
            self.assertEqual(source.read_text(), "different synthetic source\n")


if __name__ == "__main__":
    unittest.main()
