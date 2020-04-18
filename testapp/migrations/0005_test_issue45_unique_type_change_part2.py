from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0004_test_issue45_unique_type_change_part1'),
    ]

    # Issue #45 test
    operations = [
        # Case 1: changing max_length changes the column type - the filtered UNIQUE INDEX which implements
        # the nullable unique constraint, should be correctly reinstated after this change of column type
        # (see also the specific unit test which checks that multiple rows with NULL are allowed)
        migrations.AlterField(
            model_name='testuniquenullablemodel',
            name='x',
            field=models.CharField(max_length=11, null=True, unique=True),
        ),

        # Case 2: the filtered UNIQUE INDEX implementing the partially nullable `unique_together` constraint
        # should be correctly reinstated after this column type change
        migrations.AlterField(
            model_name='testnullableuniquetogethermodel',
            name='a',
            field=models.CharField(max_length=51, null=True),
        ),
        # ...similarly adding another field to the `unique_together` should preserve the constraint correctly
        migrations.AlterUniqueTogether(
            name='testnullableuniquetogethermodel',
            unique_together={('a', 'b', 'c')},
        ),
    ]
