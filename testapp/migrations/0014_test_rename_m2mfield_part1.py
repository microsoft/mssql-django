from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0013_test_indexes_retained_part2'),
    ]

    operations = [
        # Prep test for issue https://github.com/microsoft/mssql-django/issues/86
        migrations.CreateModel(
            name='M2MOtherModel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=10)),
            ],
        ),
        migrations.CreateModel(
            name='TestRenameManyToManyFieldModel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('others', models.ManyToManyField(to='testapp.M2MOtherModel')),
            ],
        ),
    ]
