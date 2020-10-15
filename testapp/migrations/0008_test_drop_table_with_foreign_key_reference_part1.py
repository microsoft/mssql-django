from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testapp', '0007_test_remove_onetoone_field_part2'),
    ]

    operations = [
        migrations.CreateModel(
            name="Pony",
            fields=[
                ("id", models.AutoField(primary_key=True)),
            ]),
        migrations.CreateModel(
            name="Rider",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("pony", models.ForeignKey("testapp.Pony", models.CASCADE)),
            ]),
    ]
