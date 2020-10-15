from django.db import migrations, models


class Migration(migrations.Migration):
    '''
    Sql server will generate a error if drop a table that is referenced by a foreign key constraint.
    This test is to check if the table can be dropped correctly. 
    '''
    dependencies = [
        ('testapp', '0008_test_drop_table_with_foreign_key_reference_part1'),
    ]

    operations = [
        migrations.DeleteModel("Pony"),
        migrations.DeleteModel("Rider"),
    ]
