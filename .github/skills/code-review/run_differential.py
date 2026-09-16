#!/usr/bin/env python3
"""Run one unchanged Django test against a pull request head and merge base."""

import argparse
import hashlib
import json
import os
import re
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


def run(command, *, cwd, env=None, capture=False):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def git(repo, *arguments):
    result = run(["git", *arguments], cwd=repo, capture=True)
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


def create_environment(python, environment_dir, source_dir, wheelhouse, packages):
    subprocess.run(
        [python, "-m", "venv", environment_dir],
        check=True,
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
    subprocess.run([*install_prefix, "setuptools", "wheel"], check=True)
    subprocess.run(
        [
            *install_prefix,
            "--no-build-isolation",
            "--editable",
            f"{source_dir}[test]",
        ],
        check=True,
    )
    if packages:
        subprocess.run([*install_prefix, *packages], check=True)
    return environment_python


def classify_test(return_code, output):
    tests_run = re.search(r"Ran (\d+) tests?", output)
    if not tests_run or int(tests_run.group(1)) == 0:
        return "inconclusive"
    if re.search(
        r"(?:skipped|expected failures|unexpected successes)=[1-9]\d*",
        output,
    ):
        return "inconclusive"
    if return_code == 0 and re.search(r"^OK(?:\s|$)", output, re.MULTILINE):
        return "pass"
    if return_code and "FAILED (" in output:
        return "fail"
    return "inconclusive"


def execute_test(python, source_dir, label, environment):
    return run(
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
        capture=True,
    )


def run_test(python, source_dir, label, database_suffix, output_path):
    environment = os.environ.copy()
    environment["MSSQL_DB_NAME"] = f"rp_{database_suffix}"
    environment["MSSQL_DB_NAME_OTHER"] = f"rp_{database_suffix}_other"
    result = execute_test(python, source_dir, label, environment)
    attempts = [
        {
            "exit_code": result.returncode,
            "status": classify_test(result.returncode, result.stdout),
        }
    ]
    output = result.stdout
    status = attempts[0]["status"]
    if status == "fail":
        rerun = execute_test(python, source_dir, label, environment)
        rerun_status = classify_test(rerun.returncode, rerun.stdout)
        attempts.append({"exit_code": rerun.returncode, "status": rerun_status})
        output = f"{output}\n\n--- deterministic rerun ---\n\n{rerun.stdout}"
        if rerun_status != "fail":
            status = "inconclusive"
    output_path.write_text(output, encoding="utf-8")
    return {
        "exit_code": result.returncode,
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


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--test-file", required=True)
    parser.add_argument("--test-label", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--wheelhouse",
        default=os.environ.get("REGRESSION_POLICE_WHEELHOUSE"),
    )
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="Install the same package constraint in both environments.",
    )
    parser.add_argument("--output-dir")
    return parser.parse_args()


def make_run_id(args, head_sha, test_file):
    configuration = json.dumps(
        {
            "base_ref": args.base_ref,
            "head_sha": args.head_sha,
            "packages": args.package,
            "python": args.python,
            "test_file": str(test_file),
            "test_label": args.test_label,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(configuration.encode()).hexdigest()[:12]
    return f"{head_sha[:8]}-{test_file.stem}-{digest}-{uuid.uuid4().hex[:8]}"


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

        git(repo, "check-ref-format", "--branch", args.base_ref)
        base_refspec = (
            f"+refs/heads/{args.base_ref}:refs/remotes/origin/{args.base_ref}"
        )
        subprocess.run(
            ["git", "fetch", "--no-tags", "origin", base_refspec],
            cwd=repo,
            check=True,
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
            base_dir = temporary_path / "base"
            subprocess.run(
                ["git", "worktree", "add", "--detach", base_dir, base_sha],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            try:
                base_test_file = base_dir / test_file
                base_test_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo / test_file, base_test_file)

                head_python = create_environment(
                    args.python,
                    temporary_path / "head-venv",
                    repo,
                    wheelhouse,
                    args.package,
                )
                base_python = create_environment(
                    args.python,
                    temporary_path / "base-venv",
                    base_dir,
                    wheelhouse,
                    args.package,
                )
                head_result = run_test(
                    head_python,
                    repo,
                    args.test_label,
                    f"head_{head_sha[:8]}",
                    head_log,
                )
                base_result = run_test(
                    base_python,
                    base_dir,
                    args.test_label,
                    f"base_{base_sha[:8]}",
                    base_log,
                )
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", base_dir],
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
        "python": args.python,
        "wheelhouse": args.wheelhouse,
        "packages": args.package,
        "test_file": str(test_file),
        "test_label": args.test_label,
        "base_exit_code": base_result["exit_code"],
        "base_status": base_result["status"],
        "base_attempts": base_result.get("attempts", []),
        "head_exit_code": head_result["exit_code"],
        "head_status": head_result["status"],
        "head_attempts": head_result.get("attempts", []),
        "verdict": verdict(base_result, head_result),
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
