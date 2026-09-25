"""Exercise the normal squashmigrations CLI without preloading the backend."""

import os
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent

from django.conf import settings
from django.db import migrations
from django.test import SimpleTestCase


class SquashMigrationsCommandTests(SimpleTestCase):
    databases = {"default"}

    def test_cli_preserves_renamed_index_and_constraint(self):
        database = {
            key: value
            for key, value in settings.DATABASES["default"].items()
            if key != "TEST"
        }
        fixtures = {
            "squash_cli_settings.py": f"""
                SECRET_KEY = "squash-cli-test"
                INSTALLED_APPS = ["squash_cli_app"]
                DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
                DATABASES = {{"default": {database!r}}}
            """,
            "squash_cli_app/__init__.py": "",
            "squash_cli_app/models.py": """
                from django.db import models

                class Record(models.Model):
                    aa = models.CharField(max_length=20, null=True)
                    b = models.CharField(max_length=20)

                    class Meta:
                        db_table = "squash_cli_record"
                        indexes = [models.Index(fields=["aa"], name="record_idx")]
                        constraints = [
                            models.UniqueConstraint(
                                fields=["b"], include=["aa"],
                                condition=models.Q(aa__isnull=False),
                                name="record_uq",
                            ),
                        ]
            """,
            "squash_cli_app/migrations/__init__.py": "",
            "squash_cli_app/migrations/0001_initial.py": """
                from django.db import migrations, models

                class Migration(migrations.Migration):
                    initial = True
                    dependencies = []
                    operations = [
                        migrations.CreateModel(
                            name="Record",
                            fields=[
                                ("id", models.AutoField(primary_key=True)),
                                ("a", models.CharField(max_length=20, null=True)),
                                ("b", models.CharField(max_length=20)),
                            ],
                            options={
                                "db_table": "squash_cli_record",
                                "indexes": [
                                    models.Index(fields=["a"], name="record_idx"),
                                ],
                                "constraints": [
                                    models.UniqueConstraint(
                                        fields=["b"], include=["a"],
                                        condition=models.Q(a__isnull=False),
                                        name="record_uq",
                                    ),
                                ],
                            },
                        ),
                    ]
            """,
            "squash_cli_app/migrations/0002_rename.py": """
                from django.db import migrations

                class Migration(migrations.Migration):
                    dependencies = [("squash_cli_app", "0001_initial")]
                    operations = [
                        migrations.RenameField(
                            model_name="record", old_name="a", new_name="aa",
                        ),
                    ]
            """,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in fixtures.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(dedent(source), encoding="utf-8")

            # Use this checkout, not an installed backend or the parent's
            # already-patched Django objects. Leave normal CLI checks enabled.
            env = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "squash_cli_settings",
                "PYTHONPATH": os.pathsep.join([
                    str(Path(__file__).resolve().parents[2]), str(root),
                ]),
            }
            result = subprocess.run(
                [
                    sys.executable, "-m", "django", "squashmigrations",
                    "squash_cli_app", "0002_rename", "--no-input",
                    "--squashed-name=cli",
                ],
                cwd=root, env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            generated = root / "squash_cli_app/migrations/0001_cli.py"
            self.assertTrue(generated.is_file(), result.stdout + result.stderr)
            operations = runpy.run_path(str(generated))["Migration"].operations
            self.assertEqual(len(operations), 1)
            self.assertIsInstance(operations[0], migrations.CreateModel)
            create = operations[0]
            self.assertIn("aa", dict(create.fields))
            self.assertNotIn("a", dict(create.fields))
            index, = create.options["indexes"]
            self.assertEqual(index.name, "record_idx")
            self.assertEqual(index.fields, ["aa"])
            constraint, = create.options["constraints"]
            self.assertEqual(constraint.name, "record_uq")
            self.assertEqual(constraint.fields, ("b",))
            self.assertEqual(constraint.include, ("aa",))
            self.assertEqual(constraint.condition.children, [("aa__isnull", False)])
