from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0003_test_unique_nullable_part2'),
    ]

    # Issue #45 test prep
    operations = [
        # for case 1:
        migrations.AddField(
            model_name='testuniquenullablemodel',
            name='x',
            field=models.CharField(max_length=10, null=True, unique=True),
        ),

        # for case 2:
        migrations.CreateModel(
            name='TestNullableUniqueTogetherModel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('a', models.CharField(max_length=50, null=True)),
                ('b', models.CharField(max_length=50)),
                ('c', models.CharField(max_length=50)),
            ],
            options={
                'unique_together': {('a', 'b')},
            },
        ),
    ]
