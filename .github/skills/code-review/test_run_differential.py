import os
import json
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
    bounded_file_digest,
    classify_test,
    cleanup_databases,
    create_execution_hook,
    failure_signature,
    final_verdict,
    main,
    make_run_id,
    run_process_group,
    run_test,
    source_fingerprint,
    supported_django,
    validate_test_label,
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
        class_cleanup_error = self.failure + (
            "\nERROR: tearDownClass (test.module.Class)\n"
            '  File "/tmp/test_probe.py", line 30, in tearDownClass\n'
            "RuntimeError: class cleanup failed\n"
        )
        self.assertEqual(
            classify_test(
                1,
                class_cleanup_error,
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

    def test_failure_signature_accepts_bare_assertion_error(self):
        bare = self.failure.replace(
            "AssertionError: expected 1, got 2",
            "AssertionError",
        )
        self.assertIsNotNone(failure_signature(bare, self.label))

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

        with tempfile.TemporaryDirectory() as temporary, patch(
            "run_differential.cleanup_databases"
        ):
            Path(temporary, "sitecustomize.py").write_text("hook\n")
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

        with tempfile.TemporaryDirectory() as temporary, patch(
            "run_differential.cleanup_databases"
        ):
            Path(temporary, "sitecustomize.py").write_text("hook\n")
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

        with tempfile.TemporaryDirectory() as temporary, patch(
            "run_differential.cleanup_databases"
        ):
            Path(temporary, "sitecustomize.py").write_text("hook\n")
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

        with tempfile.TemporaryDirectory() as temporary, patch(
            "run_differential.cleanup_databases"
        ):
            Path(temporary, "sitecustomize.py").write_text("hook\n")
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

    @patch("run_differential.execute_test")
    def test_hook_mutation_is_inconclusive(self, execute_test):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "run_differential.cleanup_databases"
        ):
            hook = Path(temporary, "sitecustomize.py")
            hook.write_text("original\n")

            def mutate_hook(*args):
                hook.write_text("mutated\n")
                return SimpleNamespace(
                    returncode=0,
                    stdout=f"{self.sentinel}:PASS\nRan 1 test\n\nOK\n",
                )

            execute_test.side_effect = mutate_hook
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
        self.assertTrue(result["hook_changed"])

    def test_hook_digest_rejects_symlink_and_oversized_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "target"
            target.write_text("hook\n")
            link = directory / "link"
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaises(RuntimeError):
                bounded_file_digest(link)
            oversized = directory / "oversized"
            oversized.write_bytes(b"x" * 16385)
            with self.assertRaises(RuntimeError):
                bounded_file_digest(oversized)

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

    def test_supported_django_comes_from_test_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            workflow = repo / ".github" / "workflows" / "test.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                '- { django-spec: "django>=5.2,<5.3" }\n'
                '- { django-spec: "django>=6.1,<6.2" }\n'
            )
            self.assertEqual(
                supported_django(repo),
                ["django>=5.2,<5.3", "django>=6.1,<6.2"],
            )

    def test_test_label_must_resolve_inside_copied_module(self):
        test_file = Path("testapp/tests/test_probe.py")
        validate_test_label(
            test_file,
            "testapp.tests.test_probe.ProbeTest.test_behavior",
        )
        with self.assertRaises(ValueError):
            validate_test_label(
                test_file,
                "testapp.tests.test_other.OtherTest.test_behavior",
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

    def test_execution_hook_marks_targeted_method_outcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            hook = directory / "hook"
            create_execution_hook(hook)
            script = directory / "probe.py"
            script.write_text(
                "import unittest\n"
                "class Probe(unittest.TestCase):\n"
                "    def test_pass(self):\n"
                "        pass\n"
                "    def test_fail(self):\n"
                "        self.fail('boom')\n"
                "unittest.main(verbosity=2)\n"
            )
            for method, marker, return_code in (
                ("test_pass", "PASS", 0),
                ("test_fail", "FAIL", 1),
            ):
                with self.subTest(method=method):
                    sentinel = f"sentinel-{method}"
                    environment = os.environ.copy()
                    environment["REGRESSION_POLICE_TEST_ID"] = (
                        f"__main__.Probe.{method}"
                    )
                    environment["REGRESSION_POLICE_SENTINEL"] = sentinel
                    environment["PYTHONPATH"] = str(hook)
                    result = run_process_group(
                        [sys.executable, script, f"Probe.{method}"],
                        cwd=directory,
                        env=environment,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, return_code)
                    self.assertIn(f"{sentinel}:{marker}", result.stdout)

    @patch("run_differential.run_process_group")
    def test_cleanup_rejects_unsafe_database_names(self, run_group):
        with self.assertRaises(RuntimeError):
            cleanup_databases(
                "python",
                ["safe", "unsafe]; DROP DATABASE master"],
                os.environ.copy(),
            )
        run_group.assert_not_called()

    @patch("run_differential.run_process_group")
    def test_cleanup_does_not_load_probe_hook(self, run_group):
        run_group.return_value = subprocess.CompletedProcess([], 0, "")
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": "/untrusted/hook",
                "REGRESSION_POLICE_TEST_ID": "test.id",
                "REGRESSION_POLICE_SENTINEL": "sentinel",
            }
        )
        cleanup_databases("python", ["test_rp_safe"], environment)
        cleanup_environment = run_group.call_args.kwargs["env"]
        self.assertNotIn("PYTHONPATH", cleanup_environment)
        self.assertNotIn("REGRESSION_POLICE_TEST_ID", cleanup_environment)
        self.assertNotIn("REGRESSION_POLICE_SENTINEL", cleanup_environment)

    def test_setup_does_not_execute_checkout_package_metadata(self):
        repo = Path(__file__).resolve().parents[3]
        workflow_directory = repo / ".github" / "workflows"
        setup_workflow = (workflow_directory / "copilot-setup-steps.yml").read_text()
        self.assertNotIn('pip install -e ".[test]"', setup_workflow)
        for workflow in workflow_directory.glob("*.yml"):
            lines = workflow.read_text().splitlines()
            for index, line in enumerate(lines):
                if "uses: actions/checkout@" not in line:
                    continue
                checkout_block = "\n".join(lines[index:index + 8])
                self.assertIn(
                    "persist-credentials: false",
                    checkout_block,
                    workflow.name,
                )

    def test_successful_main_orchestration(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            output = Path(temporary) / "output"
            wheelhouse = Path(temporary) / "wheelhouse"
            test_file = Path("testapp/tests/test_probe.py")
            (repo / test_file).parent.mkdir(parents=True)
            (repo / test_file).write_text("probe = True\n")
            workflow = repo / ".github" / "workflows" / "test.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                '- { django-spec: "django>=6.1,<6.2" }\n'
            )
            wheelhouse.mkdir()
            head_sha = "1" * 40
            base_sha = "2" * 40

            def fake_git(_repo, *arguments):
                if arguments == ("rev-parse", "--show-toplevel"):
                    return str(repo)
                if arguments == ("rev-parse", "HEAD"):
                    return head_sha
                if arguments[0] == "merge-base":
                    return base_sha
                if arguments[0] == "diff":
                    return ""
                if arguments[0] == "check-ref-format":
                    return ""
                raise AssertionError(arguments)

            def fake_subprocess(command, **kwargs):
                if command[:3] == ["git", "worktree", "add"]:
                    Path(command[4]).mkdir(parents=True)
                return subprocess.CompletedProcess(command, 0)

            passing = {
                "exit_code": 0,
                "status": "pass",
                "attempts": [],
                "database_names": [],
                "cleanup_error": None,
                "hook_changed": False,
            }
            arguments = [
                "run_differential.py",
                "--base-ref",
                "dev",
                "--head-sha",
                head_sha,
                "--wheelhouse",
                str(wheelhouse),
                "--test-file",
                str(test_file),
                "--test-label",
                "testapp.tests.test_probe.Probe.test_behavior",
                "--output-dir",
                str(output),
            ]
            with (
                patch("run_differential.git", side_effect=fake_git),
                patch("run_differential.subprocess.run", side_effect=fake_subprocess),
                patch("run_differential.source_fingerprint", return_value="stable"),
                patch("run_differential.create_environment", return_value="python"),
                patch("run_differential.verify_import_source"),
                patch(
                    "run_differential.run_test",
                    side_effect=[passing.copy(), passing.copy()],
                ) as run_probe,
                patch.object(sys, "argv", arguments),
            ):
                return_code = main()

            report = json.loads(next(output.glob("*.json")).read_text())
            self.assertEqual(return_code, 0)
            self.assertEqual(
                report["verdict"],
                "disproved-in-tested-configuration",
            )
            self.assertEqual(run_probe.call_count, 2)
            base_call, head_call = run_probe.call_args_list
            self.assertEqual(base_call.args[1].name, "base")
            self.assertEqual(head_call.args[1].name, "head")
            self.assertNotEqual(head_call.args[6], base_call.args[6])

    def test_invalid_label_writes_inconclusive_report(self):
        repo = Path(__file__).resolve().parents[3]
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            text=True,
        ).strip()
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    Path(__file__).resolve().with_name("run_differential.py"),
                    "--base-ref",
                    "dev",
                    "--head-sha",
                    head_sha,
                    "--test-file",
                    ".github/skills/code-review/test_run_differential.py",
                    "--test-label",
                    "wrong.module.Test.test_method",
                    "--output-dir",
                    temporary,
                ],
                cwd=repo,
                check=False,
                text=True,
                capture_output=True,
            )
            report_path = next(Path(temporary).glob("*.json"))
            report = json.loads(report_path.read_text())
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["verdict"], "inconclusive")
        self.assertIn("ValueError", report["failure"])


if __name__ == "__main__":
    unittest.main()
