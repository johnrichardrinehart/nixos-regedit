import os
import unittest
from pathlib import Path

from tools.evaluation_matrix import (
    DEFAULT_REPOSITORIES,
    backend_matrix,
    standalone_matrix,
)

RUN_REMOTE_MATRIX = os.environ.get("NIXOS_REGEDIT_REMOTE_MATRIX") == "1"


@unittest.skipUnless(
    RUN_REMOTE_MATRIX,
    "set NIXOS_REGEDIT_REMOTE_MATRIX=1 to run remote backend/standalone flake matrix",
)
class RemoteEvaluationMatrixTests(unittest.TestCase):
    def test_backend_remote_flake_matrix(self):
        results = backend_matrix(DEFAULT_REPOSITORIES, timeout=900)
        self.assertEqual(
            [result["repository"] for result in results],
            DEFAULT_REPOSITORIES,
        )
        for result in results:
            self.assertGreater(result["optionCount"], 0)

    def test_standalone_remote_flake_matrix(self):
        index = Path(os.environ.get("NIXOS_REGEDIT_STANDALONE_INDEX", "result/index.html"))
        results = standalone_matrix(
            DEFAULT_REPOSITORIES,
            index_html=index.resolve(),
            timeout=900,
            port=int(os.environ.get("NIXOS_REGEDIT_REMOTE_MATRIX_PORT", "9230")),
        )
        self.assertEqual(
            [result["repository"] for result in results],
            DEFAULT_REPOSITORIES,
        )
        for result in results:
            self.assertGreater(result["optionCount"], 0)
            self.assertTrue(result["diagnosticsHidden"])


if __name__ == "__main__":
    unittest.main()
