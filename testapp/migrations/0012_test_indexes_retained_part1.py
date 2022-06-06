from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0011_test_unique_constraints'),
    ]

    # Prep test for issue https://github.com/ESSolutions/django-mssql-backend/issues/58
    operations = [
        migrations.CreateModel(
            name='TestIndexesRetained',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('a', models.IntegerField(db_index=True)),
                ('b', models.IntegerField(db_index=True)),
                ('c', models.IntegerField(db_index=True)),
            ],
        ),
    ]
