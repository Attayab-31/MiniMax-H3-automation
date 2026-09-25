import unittest
from pathlib import Path

from app.kaggle_client import _download_kernel_output


class KaggleOutputCompatibilityTests(unittest.TestCase):
    def test_accepts_kaggle_api_list_of_output_paths(self):
        paths = [f"/tmp/output/file-{index}.mp4" for index in range(17)]

        class KaggleApiStub:
            def kernels_output(self, kernel_id, path):
                return paths

        result = _download_kernel_output(
            KaggleApiStub(), "owner/kernel", Path("/tmp/output"), "*.mp4"
        )

        self.assertEqual(result, paths)

    def test_accepts_wrapped_output_result_and_file_filter(self):
        paths = ["/tmp/output/automation_manifest.json"]

        class KaggleApiStub:
            def kernels_output(self, kernel_id, path, file_pattern=None):
                self.file_pattern = file_pattern
                return paths, {"downloaded": len(paths)}

        api = KaggleApiStub()
        result = _download_kernel_output(
            api, "owner/kernel", Path("/tmp/output"), "automation_manifest.json"
        )

        self.assertEqual(result, paths)
        self.assertEqual(api.file_pattern, "automation_manifest.json")


if __name__ == "__main__":
    unittest.main()
