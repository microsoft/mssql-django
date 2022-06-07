# TODO:
#
# * m2m_through_regress
# * many_to_one_null

set -e

DJANGO_VERSION="$(python -m django --version)"

cd django
git fetch --depth=1 origin +refs/tags/*:refs/tags/*
git checkout $DJANGO_VERSION
pip install -r tests/requirements/py3.txt

coverage run tests/runtests.py --settings=testapp.settings --noinput \
    aggregation \
    aggregation_regress \
    annotations \
    backends \
    basic \
    bulk_create \
    constraints \
    custom_columns \
    custom_lookups \
    custom_managers \
    custom_methods \
    custom_migration_operations \
    custom_pk \
    datatypes \
    dates \
    datetimes \
    db_functions \
    db_typecasts \
    db_utils \
    dbshell \
    defer \
    defer_regress \
    delete \
    delete_regress \
    distinct_on_fields \
    empty \
    expressions \
    expressions_case \
    expressions_window \
    extra_regress \
    field_deconstruction \
    field_defaults \
    field_subclassing \
    filtered_relation \
    fixtures \
    fixtures_model_package \
    fixtures_regress \
    force_insert_update \
    foreign_object \
    from_db_value \
    generic_relations \
    generic_relations_regress \
    get_earliest_or_latest \
    get_object_or_404 \
    get_or_create \
    indexes \
    inspectdb \
    introspection \
    invalid_models_tests \
    known_related_objects \
    lookup \
    m2m_and_m2o \
    m2m_intermediary \
    m2m_multiple \
    m2m_recursive \
    m2m_regress \
    m2m_signals \
    m2m_through \
    m2o_recursive \
    managers_regress \
    many_to_many \
    many_to_one \
    max_lengths \
    migrate_signals \
    migration_test_data_persistence \
    migrations \
    migrations2 \
    model_fields \
    model_indexes \
    model_options \
    mutually_referential \
    nested_foreign_keys \
    null_fk \
    null_fk_ordering \
    null_queries \
    one_to_one \
    or_lookups \
    order_with_respect_to \
    ordering \
    pagination \
    prefetch_related \
    queries \
    queryset_pickle \
    raw_query \
    reverse_lookup \
    save_delete_hooks \
    schema \
    select_for_update \
    select_related \
    select_related_onetoone \
    select_related_regress \
    serializers \
    timezones \
    transaction_hooks \
    transactions \
    update \
    update_only_fields

python -m coverage xml --include '*mssql*' --omit '*virtualenvs*' -o coverage.xml

