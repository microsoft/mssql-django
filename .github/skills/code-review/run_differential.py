#!/usr/bin/env python3
"""Run one unchanged Django test against a pull request head and merge base."""

import argparse
import hashlib
import json
import os
import re
import signal
import stat
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


DEPENDENCY_FILES = (
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "uv.lock",
)
BASE_PACKAGES = ("pyodbc", "pytz", "unittest-xml-reporting>=3.2.0")
DEFAULT_DJANGO = "django>=6.1,<6.2"
SUPPORTED_DJANGO = (
    "django>=5.2,<5.3",
    "django>=6.0,<6.1",
    DEFAULT_DJANGO,
)
GIT_TIMEOUT = 60
SETUP_TIMEOUT = 300


def run(command, *, cwd, env=None, capture=False, timeout=None):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        timeout=timeout,
    )


def git(repo, *arguments):
    result = run(
        ["git", *arguments],
        cwd=repo,
        capture=True,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode:
        raise RuntimeError(result.stdout.strip())
    return result.stdout.strip()


def validate_test_file(repo, value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("test file must be relative to the repository")
    resolved = (repo / path).resolve()
    try:
        resolved.relative_to(repo.resolve())
    except ValueError as error:
        raise ValueError("test file must be inside the repository") from error
    if not resolved.is_file():
        raise ValueError(f"test file does not exist: {value}")
    return path


def create_environment(python, environment_dir, wheelhouse, django):
    subprocess.run(
        [python, "-m", "venv", environment_dir],
        check=True,
        timeout=SETUP_TIMEOUT,
    )
    executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    environment_python = environment_dir / executable
    install_prefix = [
        environment_python,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--no-index",
        "--find-links",
        wheelhouse,
    ]
    subprocess.run(
        [*install_prefix, "setuptools", "wheel", *BASE_PACKAGES, django],
        check=True,
        timeout=SETUP_TIMEOUT,
    )
    return environment_python


def failure_signature(output, test_label):
    test_name = test_label.rsplit(".", 1)[-1]
    headers = re.findall(
        rf"^(?:FAIL|ERROR)(?: \[[^\]]+\])?: .*{re.escape(test_name)}.*$",
        output,
        re.MULTILINE,
    )
    headers = [re.sub(r" \[[^\]]+\]", "", header) for header in headers]
    details = re.findall(
        r"^(?:[\w.]+(?:Error|Exception|Failure)|AssertionError): .+$",
        output,
        re.MULTILINE,
    )
    frames = [
        {
            "file": Path(path).name,
            "line": int(line),
            "function": function,
        }
        for path, line, function in re.findall(
            r'^\s*File "([^"]+)", line (\d+), in (.+)$',
            output,
            re.MULTILINE,
        )
    ]
    if not headers or not details or not frames:
        return None
    stable = json.dumps(
        {"headers": headers, "details": details, "frames": frames},
        sort_keys=True,
    )
    return hashlib.sha256(stable.encode()).hexdigest()


def has_lifecycle_failure(output):
    return bool(
        re.search(
            r"\bin (?:setUp|tearDown|setUpClass|tearDownClass|"
            r"setUpModule|tearDownModule|_callSetUp|_callTearDown|"
            r"cleanup|_callCleanup|doCleanups|doClassCleanups|"
            r"doModuleCleanups)\b",
            output,
        )
    )


def classify_test(return_code, output, test_label, sentinel):
    tests_run = re.search(r"Ran (\d+) tests?", output)
    executed_once = bool(tests_run and int(tests_run.group(1)) == 1)
    method_passed = f"{sentinel}:PASS" in output
    method_failed = f"{sentinel}:FAIL" in output
    method_executed = method_passed != method_failed
    lifecycle_failed = has_lifecycle_failure(output)
    if not executed_once or not method_executed or lifecycle_failed:
        return "inconclusive"
    if re.search(
        r"(?:skipped|expected failures|unexpected successes)=[1-9]\d*",
        output,
    ):
        return "inconclusive"
    ok_summary = bool(re.search(r"^OK(?:\s|$)", output, re.MULTILINE))
    suite_passed = return_code == 0 and ok_summary
    if method_passed and suite_passed:
        return "pass"
    if method_failed and return_code and failure_signature(output, test_label):
        return "fail"
    return "inconclusive"


def terminate_process_tree(process):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def output_text(output):
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output or ""


def run_process_group(command, *, cwd, env, timeout):
    options = {
        "cwd": cwd,
        "env": env,
        "stderr": subprocess.STDOUT,
        "stdout": subprocess.PIPE,
        "text": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        stdout = output_text(error.stdout)
        terminate_process_tree(process)
        if process.stdout:
            process.stdout.close()
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout,
        ) from error
    return subprocess.CompletedProcess(command, process.returncode, stdout)


def execute_test(python, source_dir, label, environment, timeout):
    return run_process_group(
        [
            python,
            "manage.py",
            "test",
            label,
            "--noinput",
            "--verbosity",
            "2",
        ],
        cwd=source_dir,
        env=environment,
        timeout=timeout,
    )


def execute_attempt(
    python,
    source_dir,
    label,
    environment,
    timeout,
    sentinel,
):
    try:
        result = execute_test(python, source_dir, label, environment, timeout)
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return {
            "exit_code": None,
            "status": "inconclusive",
            "signature": None,
            "timed_out": True,
        }, output
    status = classify_test(result.returncode, result.stdout, label, sentinel)
    return {
        "exit_code": result.returncode,
        "status": status,
        "signature": failure_signature(result.stdout, label)
        if status == "fail"
        else None,
        "timed_out": False,
    }, result.stdout


def run_test(
    python,
    source_dir,
    label,
    database_suffix,
    output_path,
    timeout,
    hook_dir,
    sentinel=None,
):
    environment = os.environ.copy()
    environment["MSSQL_DB_NAME"] = f"rp_{database_suffix}"
    environment["MSSQL_DB_NAME_OTHER"] = f"rp_{database_suffix}_other"
    sentinel = sentinel or f"REGRESSION_POLICE_EXECUTED:{uuid.uuid4().hex}"
    environment["REGRESSION_POLICE_TEST_ID"] = label
    environment["REGRESSION_POLICE_SENTINEL"] = sentinel
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(hook_dir), environment.get("PYTHONPATH")))
    )
    first, output = execute_attempt(
        python,
        source_dir,
        label,
        environment,
        timeout,
        sentinel,
    )
    attempts = [first]
    status = attempts[0]["status"]
    if status == "fail":
        rerun, rerun_output = execute_attempt(
            python,
            source_dir,
            label,
            environment,
            timeout,
            sentinel,
        )
        attempts.append(rerun)
        output = f"{output}\n\n--- deterministic rerun ---\n\n{rerun_output}"
        matching_failure = rerun["status"] == "fail" and (
            rerun["signature"] == first["signature"]
        )
        if not matching_failure:
            status = "inconclusive"
    output_path.write_text(output, encoding="utf-8")
    return {
        "exit_code": first["exit_code"],
        "status": status,
        "attempts": attempts,
    }


def verdict(base_result, head_result):
    outcomes = (base_result["status"], head_result["status"])
    if "inconclusive" in outcomes:
        return "inconclusive"
    return {
        ("pass", "fail"): "introduced-regression",
        ("fail", "pass"): "confirmed-fix",
        ("fail", "fail"): "pre-existing-or-incomplete",
        ("pass", "pass"): "disproved-in-tested-configuration",
    }[outcomes]


def final_verdict(failure, base_result, head_result):
    return "inconclusive" if failure else verdict(base_result, head_result)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--test-file", required=True)
    parser.add_argument("--test-label", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--wheelhouse",
        default=os.environ.get("REGRESSION_POLICE_WHEELHOUSE"),
    )
    parser.add_argument(
        "--django",
        choices=SUPPORTED_DJANGO,
        default=DEFAULT_DJANGO,
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--output-dir")
    return parser.parse_args()


def make_run_id(args, head_sha, test_file):
    configuration = json.dumps(
        {
            "base_ref": args.base_ref,
            "django": args.django,
            "head_sha": args.head_sha,
            "python": sys.executable,
            "test_file": str(test_file),
            "test_label": args.test_label,
            "timeout_seconds": args.timeout_seconds,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(configuration.encode()).hexdigest()[:12]
    return f"{head_sha[:8]}-{test_file.stem}-{digest}-{uuid.uuid4().hex[:8]}"


def create_execution_hook(directory):
    directory.mkdir(parents=True)
    (directory / "sitecustomize.py").write_text(
        "import os\n"
        "import unittest\n"
        "\n"
        "_original = unittest.TestCase._callTestMethod\n"
        "_test_id = os.environ['REGRESSION_POLICE_TEST_ID']\n"
        "_sentinel = os.environ['REGRESSION_POLICE_SENTINEL']\n"
        "\n"
        "def _call_test_method(self, method):\n"
        "    if self.id() != _test_id:\n"
        "        return _original(self, method)\n"
        "    try:\n"
        "        result = _original(self, method)\n"
        "    except BaseException:\n"
        "        print(f'{_sentinel}:FAIL', flush=True)\n"
        "        raise\n"
        "    print(f'{_sentinel}:PASS', flush=True)\n"
        "    return result\n"
        "\n"
        "unittest.TestCase._callTestMethod = _call_test_method\n",
        encoding="utf-8",
    )


def source_fingerprint(source_dir, test_file):
    digest = hashlib.sha256()
    ignored_names = {
        ".coverage",
        ".git",
        "coverage.xml",
        "db.sqlitetest",
        "result.xml",
    }
    ignored_directories = {
        ".mypy_cache",
        ".pytest_cache",
        "__pycache__",
        "logs",
    }
    files = []
    for path in source_dir.rglob("*"):
        relative_path = path.relative_to(source_dir)
        ignored_directory = any(
            part in ignored_directories for part in relative_path.parts
        )
        egg_info = any(
            part.endswith(".egg-info") for part in relative_path.parts
        )
        generated_file = (
            path.name in ignored_names or path.suffix in {".pyc", ".pyo"}
        )
        if ignored_directory or egg_info or generated_file:
            continue
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            files.append((relative_path, path))
    for relative_path, path in sorted(files):
        digest.update(str(relative_path).encode())
        digest.update(b"\0")
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            digest.update(b"symlink:")
            digest.update(os.readlink(path).encode())
        else:
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def verify_import_source(python, source_dir):
    code = (
        "from pathlib import Path; import mssql; "
        f"source=Path({str(source_dir)!r}).resolve(); "
        "loaded=Path(mssql.__file__).resolve(); "
        "loaded.relative_to(source)"
    )
    result = run(
        [python, "-c", code],
        cwd=source_dir,
        capture=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(
            f"mssql did not import from {source_dir}: {result.stdout.strip()}"
        )


def main():
    args = parse_args()
    repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    test_file = validate_test_file(repo, args.test_file)
    head_sha = git(repo, "rev-parse", "HEAD")
    default_output = Path(
        os.environ.get("RUNNER_TEMP", tempfile.gettempdir())
    ).joinpath("regression-police")
    output_root = Path(args.output_dir or default_output)
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = make_run_id(args, head_sha, test_file)
    report_path = output_root / f"{run_id}.json"
    head_log = output_root / f"{run_id}-head.log"
    base_log = output_root / f"{run_id}-base.log"

    base_sha = None
    failure = None
    head_result = {"exit_code": None, "status": "inconclusive"}
    base_result = {"exit_code": None, "status": "inconclusive"}
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.head_sha):
            raise RuntimeError("head SHA from pull request metadata must be 40 lowercase hex digits")
        if head_sha != args.head_sha:
            raise RuntimeError(f"stale checkout: expected {args.head_sha}, found {head_sha}")
        if not args.wheelhouse:
            raise RuntimeError(
                "REGRESSION_POLICE_WHEELHOUSE or --wheelhouse is required"
            )
        wheelhouse = Path(args.wheelhouse).resolve()
        if not wheelhouse.is_dir():
            raise RuntimeError(f"wheelhouse does not exist: {wheelhouse}")
        if args.timeout_seconds < 1:
            raise RuntimeError("timeout must be at least one second")

        git(repo, "check-ref-format", "--branch", args.base_ref)
        base_refspec = (
            f"+refs/heads/{args.base_ref}:refs/remotes/origin/{args.base_ref}"
        )
        subprocess.run(
            ["git", "fetch", "--no-tags", "origin", base_refspec],
            cwd=repo,
            check=True,
            timeout=SETUP_TIMEOUT,
        )
        base_sha = git(repo, "merge-base", head_sha, f"origin/{args.base_ref}")

        changed_dependencies = git(
            repo,
            "diff",
            "--name-only",
            base_sha,
            head_sha,
            "--",
            *DEPENDENCY_FILES,
        ).splitlines()
        if changed_dependencies:
            joined = ", ".join(changed_dependencies)
            raise RuntimeError(
                f"dependency metadata changed ({joined}); "
                "use independently pinned environments"
            )

        with tempfile.TemporaryDirectory(prefix="regression-police-") as temporary:
            temporary_path = Path(temporary)
            head_dir = temporary_path / "head"
            base_dir = temporary_path / "base"
            hook_dir = temporary_path / "hook"
            create_execution_hook(hook_dir)
            subprocess.run(
                ["git", "worktree", "add", "--detach", head_dir, head_sha],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=SETUP_TIMEOUT,
            )
            try:
                subprocess.run(
                    ["git", "worktree", "add", "--detach", base_dir, base_sha],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    timeout=SETUP_TIMEOUT,
                )
                head_test_file = head_dir / test_file
                base_test_file = base_dir / test_file
                head_test_file.parent.mkdir(parents=True, exist_ok=True)
                base_test_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo / test_file, head_test_file)
                shutil.copy2(repo / test_file, base_test_file)
                head_fingerprint = source_fingerprint(head_dir, test_file)
                base_fingerprint = source_fingerprint(base_dir, test_file)

                head_python = create_environment(
                    sys.executable,
                    temporary_path / "head-venv",
                    wheelhouse,
                    args.django,
                )
                base_python = create_environment(
                    sys.executable,
                    temporary_path / "base-venv",
                    wheelhouse,
                    args.django,
                )
                if source_fingerprint(head_dir, test_file) != head_fingerprint:
                    raise RuntimeError("head source changed during environment setup")
                if source_fingerprint(base_dir, test_file) != base_fingerprint:
                    raise RuntimeError("base source changed during environment setup")
                verify_import_source(head_python, head_dir)
                verify_import_source(base_python, base_dir)

                database_token = hashlib.sha256(run_id.encode()).hexdigest()[:12]
                head_result = run_test(
                    head_python,
                    head_dir,
                    args.test_label,
                    f"h_{database_token}",
                    head_log,
                    args.timeout_seconds,
                    hook_dir,
                )
                base_result = run_test(
                    base_python,
                    base_dir,
                    args.test_label,
                    f"b_{database_token}",
                    base_log,
                    args.timeout_seconds,
                    hook_dir,
                )
                if source_fingerprint(head_dir, test_file) != head_fingerprint:
                    raise RuntimeError("head source changed during probe execution")
                if source_fingerprint(base_dir, test_file) != base_fingerprint:
                    raise RuntimeError("base source changed during probe execution")
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", base_dir],
                    cwd=repo,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    ["git", "worktree", "remove", "--force", head_dir],
                    cwd=repo,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        final_head_sha = git(repo, "rev-parse", "HEAD")
        if final_head_sha != head_sha:
            raise RuntimeError(
                f"checkout changed during review: {head_sha} -> {final_head_sha}"
            )
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        failure = f"{type(error).__name__}: {error}"

    report = {
        "base_ref": args.base_ref,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "python": sys.executable,
        "wheelhouse": args.wheelhouse,
        "django": args.django,
        "test_file": str(test_file),
        "test_label": args.test_label,
        "timeout_seconds": args.timeout_seconds,
        "base_exit_code": base_result["exit_code"],
        "base_status": base_result["status"],
        "base_attempts": base_result.get("attempts", []),
        "head_exit_code": head_result["exit_code"],
        "head_status": head_result["status"],
        "head_attempts": head_result.get("attempts", []),
        "verdict": final_verdict(failure, base_result, head_result),
        "failure": failure,
        "base_log": str(base_log),
        "head_log": str(head_log),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"report: {report_path}")
    return 2 if report["verdict"] == "inconclusive" else 0


if __name__ == "__main__":
    raise SystemExit(main())
