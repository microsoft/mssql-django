import os
import subprocess
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace
from unittest.mock import patch

from run_differential import (
    SUPPORTED_DJANGO,
    classify_test,
    failure_signature,
    final_verdict,
    make_run_id,
    run_process_group,
    run_test,
    source_fingerprint,
    verdict,
)


class ResultClassificationTests(unittest.TestCase):
    label = "test.module.Class.test_behavior"
    sentinel = "REGRESSION_POLICE_EXECUTED:test"
    failure = (
        f"{sentinel}:FAIL\n"
        "FAIL: test_behavior (test.module.Class.test_behavior)\n"
        "----------------------------------------------------------------------\n"
        "Traceback (most recent call last):\n"
        '  File "/tmp/test_probe.py", line 12, in test_behavior\n'
        "AssertionError: expected 1, got 2\n"
        "----------------------------------------------------------------------\n"
        "Ran 1 test\n\n"
        "FAILED (failures=1)\n"
    )

    def test_pass_requires_an_executed_test(self):
        self.assertEqual(
            classify_test(
                0,
                f"{self.sentinel}:PASS\nRan 1 test\n\nOK\n",
                self.label,
                self.sentinel,
            ),
            "pass",
        )
        self.assertEqual(
            classify_test(
                0,
                f"{self.sentinel}:PASS\nRan 0 tests\n\nOK\n",
                self.label,
                self.sentinel,
            ),
            "inconclusive",
        )
        self.assertEqual(
            classify_test(0, "Ran 1 test\n\nOK\n", self.label, self.sentinel),
            "inconclusive",
        )

    def test_non_executed_outcomes_are_inconclusive(self):
        for outcome in ("skipped", "expected failures", "unexpected successes"):
            with self.subTest(outcome=outcome):
                output = (
                    f"{self.sentinel}:PASS\n"
                    f"Ran 1 test\n\nOK ({outcome}=1)\n"
                )
                self.assertEqual(
                    classify_test(0, output, self.label, self.sentinel),
                    "inconclusive",
                )

    def test_test_failure_and_setup_error_are_distinct(self):
        fixture_error = (
            "ERROR: setUpClass (test.module.Class)\n"
            "RuntimeError: database unavailable\n"
            "Ran 1 test\n\n"
            "FAILED (errors=1)\n"
        )
        self.assertEqual(
            classify_test(1, self.failure, self.label, self.sentinel),
            "fail",
        )
        self.assertEqual(
            classify_test(1, fixture_error, self.label, self.sentinel),
            "inconclusive",
        )
        self.assertEqual(
            classify_test(
                1,
                "database connection failed",
                self.label,
                self.sentinel,
            ),
            "inconclusive",
        )
        teardown_error = (
            f"{self.sentinel}:PASS\n"
            "ERROR: test_behavior (test.module.Class.test_behavior)\n"
            '  File "/tmp/test_probe.py", line 20, in tearDown\n'
            "RuntimeError: cleanup failed\n"
            "Ran 1 test\n\n"
            "FAILED (errors=1)\n"
        )
        self.assertEqual(
            classify_test(1, teardown_error, self.label, self.sentinel),
            "inconclusive",
        )
        cleanup_error = (
            f"{self.sentinel}:PASS\n"
            "ERROR: test_behavior (test.module.Class.test_behavior)\n"
            '  File "/tmp/test_probe.py", line 25, in cleanup\n'
            "RuntimeError: cleanup failed\n"
            "Ran 1 test\n\n"
            "FAILED (errors=1)\n"
        )
        self.assertEqual(
            classify_test(1, cleanup_error, self.label, self.sentinel),
            "inconclusive",
        )
        method_and_cleanup_failure = self.failure + (
            "\nERROR: test_behavior (test.module.Class.test_behavior)\n"
            '  File "/tmp/test_probe.py", line 25, in cleanup\n'
            "RuntimeError: cleanup failed\n"
        )
        self.assertEqual(
            classify_test(
                1,
                method_and_cleanup_failure,
                self.label,
                self.sentinel,
            ),
            "inconclusive",
        )

    def test_failure_signature_includes_details(self):
        changed_failure = self.failure.replace("got 2", "got 3")
        self.assertNotEqual(
            failure_signature(self.failure, self.label),
            failure_signature(changed_failure, self.label),
        )

    def test_failure_signature_ignores_duration(self):
        first = self.failure.replace("FAIL:", "FAIL [0.10s]:")
        second = self.failure.replace("FAIL:", "FAIL [0.25s]:")
        self.assertEqual(
            failure_signature(first, self.label),
            failure_signature(second, self.label),
        )

    def test_failure_signature_includes_assertion_location(self):
        changed_failure = self.failure.replace("line 12", "line 15")
        self.assertNotEqual(
            failure_signature(self.failure, self.label),
            failure_signature(changed_failure, self.label),
        )

    def test_failure_signature_requires_a_traceback_frame(self):
        no_frame = self.failure.replace(
            '  File "/tmp/test_probe.py", line 12, in test_behavior\n',
            "",
        )
        self.assertIsNone(failure_signature(no_frame, self.label))

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
            stdout=self.failure,
        )
        success = SimpleNamespace(
            returncode=0,
            stdout=f"{self.sentinel}:PASS\nRan 1 test\n\nOK\n",
        )
        execute_test.side_effect = [failure, success]

        with tempfile.TemporaryDirectory() as temporary:
            result = run_test(
                "python",
                Path("."),
                self.label,
                "head",
                Path(temporary) / "test.log",
                300,
                Path(temporary),
                self.sentinel,
            )

        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(len(result["attempts"]), 2)

    @patch("run_differential.execute_test")
    def test_repeated_failure_is_deterministic(self, execute_test):
        failure = SimpleNamespace(
            returncode=1,
            stdout=self.failure,
        )
        execute_test.side_effect = [failure, failure]

        with tempfile.TemporaryDirectory() as temporary:
            result = run_test(
                "python",
                Path("."),
                self.label,
                "head",
                Path(temporary) / "test.log",
                300,
                Path(temporary),
                self.sentinel,
            )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(len(result["attempts"]), 2)

    @patch("run_differential.execute_test")
    def test_different_rerun_failure_is_inconclusive(self, execute_test):
        first = SimpleNamespace(returncode=1, stdout=self.failure)
        second = SimpleNamespace(
            returncode=1,
            stdout=self.failure.replace("got 2", "got 3"),
        )
        execute_test.side_effect = [first, second]

        with tempfile.TemporaryDirectory() as temporary:
            result = run_test(
                "python",
                Path("."),
                self.label,
                "head",
                Path(temporary) / "test.log",
                300,
                Path(temporary),
                self.sentinel,
            )

        self.assertEqual(result["status"], "inconclusive")

    @patch("run_differential.execute_test")
    def test_timeout_is_inconclusive(self, execute_test):
        execute_test.side_effect = TimeoutExpired(["python"], 1)

        with tempfile.TemporaryDirectory() as temporary:
            result = run_test(
                "python",
                Path("."),
                self.label,
                "head",
                Path(temporary) / "test.log",
                1,
                Path(temporary),
                self.sentinel,
            )

        self.assertEqual(result["status"], "inconclusive")
        self.assertTrue(result["attempts"][0]["timed_out"])

    @patch("run_differential.uuid.uuid4")
    def test_report_id_includes_the_full_probe_configuration(self, uuid4):
        uuid4.return_value = SimpleNamespace(hex="a" * 32)
        arguments = Namespace(
            base_ref="dev",
            django="django>=6.1,<6.2",
            head_sha="1" * 40,
            test_label="test.module.Class.test_one",
            timeout_seconds=300,
        )
        first = make_run_id(arguments, arguments.head_sha, Path("test_probe.py"))
        arguments.test_label = "test.module.Class.test_two"
        second = make_run_id(arguments, arguments.head_sha, Path("test_probe.py"))

        self.assertNotEqual(first, second)

    @patch("run_differential.uuid.uuid4")
    def test_report_id_is_unique_for_concurrent_probes(self, uuid4):
        uuid4.side_effect = [
            SimpleNamespace(hex="a" * 32),
            SimpleNamespace(hex="b" * 32),
        ]
        arguments = Namespace(
            base_ref="dev",
            django="django>=6.1,<6.2",
            head_sha="1" * 40,
            test_label="test.module.Class.test_one",
            timeout_seconds=300,
        )
        first = make_run_id(arguments, arguments.head_sha, Path("test_probe.py"))
        second = make_run_id(arguments, arguments.head_sha, Path("test_probe.py"))

        self.assertNotEqual(first, second)

    def test_supported_django_scope(self):
        self.assertEqual(
            SUPPORTED_DJANGO,
            (
                "django>=5.2,<5.3",
                "django>=6.0,<6.1",
                "django>=6.1,<6.2",
            ),
        )

    def test_harness_failure_forces_inconclusive_verdict(self):
        passing = {"status": "pass"}
        self.assertEqual(
            final_verdict("checkout changed", passing, passing),
            "inconclusive",
        )

    def test_source_fingerprint_detects_untracked_files_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            probe = source / "probe.py"
            probe.write_text("pass\n")
            original = source_fingerprint(source, Path("probe.py"))
            (source / "new.py").write_text("ADDED = True\n")
            with_untracked = source_fingerprint(source, Path("probe.py"))
            self.assertNotEqual(original, with_untracked)
            first_target = source / "first-target"
            second_target = source / "second-target"
            first_target.write_text("first\n")
            second_target.write_text("second\n")
            link = source / "link"
            try:
                link.symlink_to(first_target)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            null_link = source_fingerprint(source, Path("probe.py"))
            link.unlink()
            link.symlink_to(second_target)
            zero_link = source_fingerprint(source, Path("probe.py"))
            self.assertNotEqual(null_link, zero_link)

    @unittest.skipIf(os.name == "nt", "POSIX process-group assertion")
    def test_timeout_terminates_descendant_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            pid_file = Path(temporary) / "child.pid"
            script = (
                "import pathlib, subprocess, sys, time; "
                "child=subprocess.Popen([sys.executable, '-c', "
                "'import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(30)']); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
                "time.sleep(30)"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                run_process_group(
                    [sys.executable, "-c", script],
                    cwd=Path(temporary),
                    env=os.environ.copy(),
                    timeout=0.5,
                )
            child_pid = int(pid_file.read_text())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                proc_stat = Path(f"/proc/{child_pid}/stat")
                if proc_stat.exists() and proc_stat.read_text().split()[2] == "Z":
                    break
                time.sleep(0.05)
            else:
                self.fail("descendant process remained running after timeout")

    def test_timeout_with_output_returns_text(self):
        script = "import time; print('started', flush=True); time.sleep(30)"
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            run_process_group(
                [sys.executable, "-c", script],
                cwd=Path.cwd(),
                env=os.environ.copy(),
                timeout=0.5,
            )
        self.assertIsInstance(raised.exception.output, str)
        self.assertIn("started", raised.exception.output)


if __name__ == "__main__":
    unittest.main()
