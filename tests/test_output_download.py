import os
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend.server.app import _resolve_output_download_path


class OutputDownloadPathTest(unittest.TestCase):
    def test_resolves_file_inside_outputs_with_outputs_prefix(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                output_file = Path("outputs") / "report.html"
                output_file.parent.mkdir()
                output_file.write_text("<html></html>", encoding="utf-8")

                resolved = _resolve_output_download_path("outputs/report.html")

                self.assertEqual(resolved, output_file.resolve())
            finally:
                os.chdir(original_cwd)

    def test_rejects_path_traversal_outside_outputs(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                Path("outputs").mkdir()
                Path("secret.html").write_text("<html></html>", encoding="utf-8")

                with self.assertRaises(HTTPException) as error:
                    _resolve_output_download_path("../secret.html")

                self.assertEqual(error.exception.status_code, 400)
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
