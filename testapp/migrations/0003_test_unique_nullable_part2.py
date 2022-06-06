from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0002_test_unique_nullable_part1'),
    ]

    operations = [
        # Run test for issue https://github.com/ESSolutions/django-mssql-backend/issues/38
        # Now remove the null=True to check this transition is correctly handled.
        migrations.AlterField(
            model_name='testuniquenullablemodel',
            name='test_field',
            field=models.CharField(default='', max_length=100, unique=True),
            preserve_default=False,
        ),
    ]
