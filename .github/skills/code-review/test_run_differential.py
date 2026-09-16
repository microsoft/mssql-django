import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from run_differential import classify_test, make_run_id, run_test, verdict


class ResultClassificationTests(unittest.TestCase):
    def test_pass_requires_an_executed_test(self):
        self.assertEqual(classify_test(0, "Ran 1 test\n\nOK\n"), "pass")
        self.assertEqual(classify_test(0, "Ran 0 tests\n\nOK\n"), "inconclusive")

    def test_non_executed_outcomes_are_inconclusive(self):
        for outcome in ("skipped", "expected failures", "unexpected successes"):
            with self.subTest(outcome=outcome):
                output = f"Ran 1 test\n\nOK ({outcome}=1)\n"
                self.assertEqual(classify_test(0, output), "inconclusive")

    def test_test_failure_and_setup_error_are_distinct(self):
        failure = "Ran 1 test\n\nFAILED (failures=1)\n"
        self.assertEqual(classify_test(1, failure), "fail")
        self.assertEqual(classify_test(1, "database connection failed"), "inconclusive")

    def test_verdicts(self):
        def result(status):
            return {"status": status}

        self.assertEqual(
            verdict(result("pass"), result("fail")),
            "introduced-regression",
        )
        self.assertEqual(
            verdict(result("fail"), result("pass")),
            "confirmed-fix",
        )
        self.assertEqual(
            verdict(result("fail"), result("fail")),
            "pre-existing-or-incomplete",
        )
        self.assertEqual(
            verdict(result("pass"), result("pass")),
            "disproved-in-tested-configuration",
        )
        self.assertEqual(
            verdict(result("inconclusive"), result("pass")),
            "inconclusive",
        )

    @patch("run_differential.execute_test")
    def test_failure_requires_a_matching_rerun(self, execute_test):
        failure = SimpleNamespace(
            returncode=1,
            stdout="Ran 1 test\n\nFAILED (failures=1)\n",
        )
        success = SimpleNamespace(returncode=0, stdout="Ran 1 test\n\nOK\n")
        execute_test.side_effect = [failure, success]

        with tempfile.TemporaryDirectory() as temporary:
            result = run_test(
                "python",
                Path("."),
                "test.label",
                "head",
                Path(temporary) / "test.log",
            )

        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(len(result["attempts"]), 2)

    @patch("run_differential.execute_test")
    def test_repeated_failure_is_deterministic(self, execute_test):
        failure = SimpleNamespace(
            returncode=1,
            stdout="Ran 1 test\n\nFAILED (failures=1)\n",
        )
        execute_test.side_effect = [failure, failure]

        with tempfile.TemporaryDirectory() as temporary:
            result = run_test(
                "python",
                Path("."),
                "test.label",
                "head",
                Path(temporary) / "test.log",
            )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(len(result["attempts"]), 2)

    @patch("run_differential.uuid.uuid4")
    def test_report_id_includes_the_full_probe_configuration(self, uuid4):
        uuid4.return_value = SimpleNamespace(hex="a" * 32)
        arguments = Namespace(
            base_ref="dev",
            head_sha="1" * 40,
            package=[],
            python="python",
            test_label="test.module.Class.test_one",
        )
        first = make_run_id(arguments, arguments.head_sha, Path("test_probe.py"))
        arguments.test_label = "test.module.Class.test_two"
        second = make_run_id(arguments, arguments.head_sha, Path("test_probe.py"))

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
