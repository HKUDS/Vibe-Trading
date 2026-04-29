import tempfile
import unittest
from pathlib import Path

from agent.backtest import validation


class ParseRunDirArgTests(unittest.TestCase):
    def test_rejects_blank_run_dir(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            validation._parse_run_dir(["validation", "   "])

        self.assertEqual(str(exc.exception), "run_dir must be a non-empty path")

    def test_rejects_malformed_run_dir(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            validation._parse_run_dir(["validation", "\0bad"])

        self.assertIn("Invalid run_dir path:", str(exc.exception))

    def test_rejects_missing_directory(self) -> None:
        missing_dir = Path(tempfile.gettempdir()) / "validation-cli-missing-dir"

        with self.assertRaises(SystemExit) as exc:
            validation._parse_run_dir(["validation", str(missing_dir)])

        self.assertEqual(str(exc.exception), f"run_dir does not exist: {missing_dir}")

    def test_accepts_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as run_dir:
            parsed = validation._parse_run_dir(["validation", run_dir])

        self.assertEqual(parsed, Path(run_dir))


if __name__ == "__main__":
    unittest.main()
