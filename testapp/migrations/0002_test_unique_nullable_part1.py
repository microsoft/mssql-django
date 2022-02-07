from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0001_initial'),
    ]

    operations = [
        # Prep test for issue https://github.com/ESSolutions/django-mssql-backend/issues/38
        # Create with a field that is unique *and* nullable so it is implemented with a filtered unique index.
        migrations.CreateModel(
            name='TestUniqueNullableModel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('test_field', models.CharField(max_length=100, null=True, unique=True)),
                ('y', models.IntegerField(unique=True, null=True)),
            ],
        ),
    ]
