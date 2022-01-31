from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0014_test_rename_m2mfield_part1'),
    ]

    operations = [
        # Run test for issue https://github.com/microsoft/mssql-django/issues/86
        # Must be in a separate migration so that the unique index was created
        # (deferred after the previous migration) before we do the rename.
        migrations.RenameField(
            model_name='testrenamemanytomanyfieldmodel',
            old_name='others',
            new_name='others_renamed',
        ),
    ]
