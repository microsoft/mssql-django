import django.db


def get_constraints(table_name):
    connection = django.db.connections[django.db.DEFAULT_DB_ALIAS]
    return connection.introspection.get_constraints(
        connection.cursor(),
        table_name=table_name,
    )


def get_constraint_names_where(table_name, **kwargs):
    return [
        name
        for name, details in get_constraints(table_name=table_name).items()
        if all(details[k] == v for k, v in kwargs.items())
    ]
