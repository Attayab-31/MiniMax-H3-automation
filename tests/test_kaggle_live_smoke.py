from kaggle import KaggleApi
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dotenv import load_dotenv

load_dotenv()


class KaggleLiveSmokeTest(unittest.TestCase):
    def test_kaggle_kernel_has_generation_output(self):
        username = os.getenv("KAGGLE_USERNAME")
        key = os.getenv("KAGGLE_KEY")
        kernel_id = os.getenv("KAGGLE_KERNEL_ID")

        self.assertTrue(username, "KAGGLE_USERNAME is missing")
        self.assertTrue(key, "KAGGLE_KEY is missing")
        self.assertTrue(kernel_id, "KAGGLE_KERNEL_ID is missing")

        api = KaggleApi()
        api.authenticate()

        status = api.kernels_status(kernel_id)
        print(f"Kernel status: {status}")
        status_name = status.get("status")
        self.assertIn(status_name, {"queued", "running", "complete"}, status)

        if status_name != "complete":
            self.skipTest(
                f"Kaggle kernel is still {status_name}; output will be checked after completion."
            )

        with TemporaryDirectory(prefix="h3-kaggle-smoke-") as output_dir:
            output = api.kernels_output(kernel_id, path=output_dir)
            print(f"Kernel output: {output}")
            self.assertTrue(
                any(Path(path).name == "automation_manifest.json" for path in output[0]),
                "Kernel completed without writing automation_manifest.json; the notebook likely did not run the generation stage.",
            )


if __name__ == "__main__":
    unittest.main()
