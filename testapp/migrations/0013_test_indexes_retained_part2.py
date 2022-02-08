from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0012_test_indexes_retained_part1'),
    ]

    # Run test for issue https://github.com/microsoft/mssql-django/issues/14
    # where the following operations should leave indexes intact
    operations = [
        migrations.AlterField(
            model_name='testindexesretained',
            name='a',
            field=models.IntegerField(db_index=True, null=True),
        ),
        migrations.RenameField(
            model_name='testindexesretained',
            old_name='b',
            new_name='b_renamed',
        ),
        migrations.RenameModel(
            old_name='TestIndexesRetained',
            new_name='TestIndexesRetainedRenamed',
        ),
    ]
