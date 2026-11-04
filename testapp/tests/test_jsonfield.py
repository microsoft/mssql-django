# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import json
from unittest import skipUnless
from unittest.mock import patch

from django import VERSION
from django.db import NotSupportedError, connections
from django.db.models import (
    Case, CheckConstraint, Count, FilteredRelation, IntegerField, JSONField, Max, Q, Value, When, Window,
)
from django.db.models.functions import RowNumber
from django.test import TestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext

if VERSION >= (3, 1):
    from ..models import Author, JSONModel, Post


def _check_jsonfield_supported_sqlite():
    # Info about JSONField support in SQLite: https://code.djangoproject.com/wiki/JSON1Extension
    import sqlite3

    try:
        conn = sqlite3.connect(':memory:')
        cursor = conn.cursor()
        cursor.execute('SELECT JSON(\'{"a": "b"}\')')
        return True
    except sqlite3.OperationalError:
        return False


class TestJSONField(TestCase):
    databases = ['default']
    # Django 3.0 and below unit test doesn't handle more than 2 databases in DATABASES correctly
    if VERSION >= (3, 1):
        databases.append('sqlite')

    json = {
        'a': 'b',
        'b': 1,
        'c': '1',
        'd': [],
        'e': [1, 2],
        'f': ['a', 'b'],
        'g': [1, 'a'],
        'h': {},
        'i': {'j': 1},
        'j': False,
        'k': True,
        'l': {
            'foo': 'bar',
            'baz': {'a': 'b', 'c': 'd'},
            'bar': ['foo', 'bar'],
            'bax': {'foo': 'bar'},
        },
    }

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    @skipUnless(
        _check_jsonfield_supported_sqlite(),
        "JSONField not supported by SQLite on this platform and Python version",
    )
    def test_keytransformexact_not_overriding(self):
        # Issue https://github.com/microsoft/mssql-django/issues/82
        json_obj = JSONModel(value=self.json)
        json_obj.save()
        self.assertSequenceEqual(
            JSONModel.objects.filter(value__a='b'),
            [json_obj],
        )
        json_obj.save(using='sqlite')
        self.assertSequenceEqual(
            JSONModel.objects.using('sqlite').filter(value__a='b'),
            [json_obj],
        )

    def test_compile_json_path_special_chars(self):
        path = connections['default'].ops.compile_json_path([
            'owner',
            'role name',
            'a"b',
            "o'reilly",
        ])
        self.assertEqual(path, "$.owner.\"role name\".\"a\\\"b\".\"o'reilly\"")

    def test_compile_json_path_negative_index_not_supported(self):
        with self.assertRaises(NotSupportedError):
            connections['default'].ops.compile_json_path(['items', '-1'])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_has_key_lookup_with_single_quote_key(self):
        obj = JSONModel.objects.create(value={"o'reilly": 1, "safe": True})

        self.assertSequenceEqual(
            JSONModel.objects.filter(value__has_key="o'reilly"),
            [obj],
        )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_exact_complex_value_lookup(self):
        obj = JSONModel.objects.create(
            value={
                "name": "example",
                "flags": {"active": True, "count": 2},
                "items": [1, "two", {"deep": "value"}],
            }
        )

        self.assertSequenceEqual(
            JSONModel.objects.filter(
                value={
                    "name": "example",
                    "flags": {"active": True, "count": 2},
                    "items": [1, "two", {"deep": "value"}],
                }
            ),
            [obj],
        )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_key_transform_exact_lookup(self):
        # Basic key-transform lookup sanity check to ensure JSON path
        # extraction remains stable for simple equality filtering.
        obj = JSONModel.objects.create(value={"message": "alpha-beta", "other": "x"})

        self.assertSequenceEqual(
            JSONModel.objects.filter(value__message="alpha-beta"),
            [obj],
        )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_key_lookups(self):
        present = JSONModel.objects.create(
            value={"nullable": None, "nested": {"nullable": None}}
        )
        non_null = JSONModel.objects.create(
            value={"nullable": "value", "nested": {"nullable": "value"}}
        )
        JSONModel.objects.create(value={})

        self.assertSequenceEqual(JSONModel.objects.filter(value__nullable=None), [present])
        self.assertSequenceEqual(JSONModel.objects.filter(value__nested__nullable=None), [present])
        self.assertSequenceEqual(JSONModel.objects.exclude(value__nullable=None), [non_null])
        self.assertSequenceEqual(
            JSONModel.objects.exclude(value__nested__nullable=None),
            [non_null],
        )
        if VERSION >= (6, 1):
            # iexact=None matches the JSON null value only from Django 6.1, where
            # KeyTransformIExact delegates None to the exact lookup. Pre-6.1 keeps
            # Django's native IS NULL semantics for iexact=None and is left alone.
            self.assertSequenceEqual(
                JSONModel.objects.filter(value__nullable__iexact=None), [present]
            )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    @skipUnless(
        _check_jsonfield_supported_sqlite(),
        "JSONField not supported by SQLite on this platform and Python version",
    )
    def test_json_null_iexact_none_secondary_database_unaffected(self):
        # This backend must not alter iexact=None on a non-SQL-Server database.
        # The fix is scoped to SQL Server, so a secondary database keeps Django's
        # native semantics on every version: pre-6.1 a missing key matches (IS
        # NULL), while 6.1 matches the JSON null value. Assert both the filter and
        # the negated (exclude) direction so a future global patch that leaks into
        # other backends is caught here.
        json_null = JSONModel(value={"nullable": None})
        json_null.save(using='sqlite')
        missing = JSONModel(value={"other": "value"})
        missing.save(using='sqlite')
        present = JSONModel(value={"nullable": "value"})
        present.save(using='sqlite')

        included = JSONModel.objects.using('sqlite').filter(
            value__nullable__iexact=None
        ).order_by('pk')
        excluded = JSONModel.objects.using('sqlite').exclude(
            value__nullable__iexact=None
        ).order_by('pk')
        if VERSION >= (6, 1):
            # 6.1 matches the JSON null value. The missing-key row yields a NULL
            # predicate, so it drops out of both the filter and the exclude.
            self.assertSequenceEqual(included, [json_null])
            self.assertSequenceEqual(excluded, [present])
        else:
            # Pre-6.1 matches a missing key (IS NULL). exclude keeps the rows
            # whose key resolves to a non-null JSON value.
            self.assertSequenceEqual(included, [missing])
            self.assertSequenceEqual(excluded, [json_null, present])

    @skipUnlessDBFeature('supports_json_openjson')
    @skipUnless(VERSION >= (4, 1), 'Q.check() requires Django 4.1 or newer')
    def test_json_null_keys_in_tableless_validation(self):
        for key, values in (
            ('key', [{'key': None}, {'key': 1}, {}]),
            ('nested__key', [{'nested': {'key': None}}, {'nested': {'key': 1}}, {}]),
            ('0', [[None], [1], []]),
            ('items__0', [{'items': [None]}, {'items': [1]}, {}]),
        ):
            for value, expected in zip(values, (True, False, False)):
                with self.subTest(key=key, value=value):
                    # Q.check() returns True after DatabaseError. Check logging
                    # too so an invalid matching query cannot silently pass.
                    with patch('django.db.models.query_utils.logger.warning') as warning:
                        result = Q(**{'value__' + key: None}).check({
                            'value': Value(value, output_field=JSONField()),
                        })
                    warning.assert_not_called()
                    self.assertIs(result, expected)

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_keys_alongside_grouped_aggregates(self):
        for key, values in (
            ('key', [{'key': None}, {'key': 1}, {}]),
            ('nested__key', [{'nested': {'key': None}}, {'nested': {'key': 1}}, {}]),
            ('0', [[None], [1], []]),
            ('items__0', [{'items': [None]}, {'items': [1]}, {}]),
        ):
            with self.subTest(key=key):
                rows = [JSONModel.objects.create(value=value) for value in values]
                condition = Q(**{'value__' + key: None})
                queryset = JSONModel.objects.filter(pk__in=[row.pk for row in rows]).values('pk').annotate(
                    n=Count('pk'), null_count=Count('pk', filter=condition),
                )
                self.assertSequenceEqual(
                    queryset.filter(Q(n__gte=2) | condition).values_list('pk', flat=True), [rows[0].pk],
                )
                flagged = queryset.annotate(flag=Case(
                    When(Q(n__gte=1) & condition, then=Value(1)),
                    default=Value(0), output_field=IntegerField(),
                )).order_by('pk')
                self.assertSequenceEqual(flagged.values_list('flag', flat=True), [1, 0, 0])
                # Aggregate filters use row indicators without splitting the
                # chosen group into separate null/non-null/missing groups.
                grouped = JSONModel.objects.filter(pk__in=[row.pk for row in rows]).annotate(
                    bucket=Value(1, output_field=IntegerField()),
                ).values('bucket').annotate(n=Count('pk'), null_count=Count('pk', filter=condition))
                self.assertSequenceEqual(grouped, [{'bucket': 1, 'n': 3, 'null_count': 1}])

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_grouped_case_inside_aggregate_expression(self):
        for key, values in (
            ('key', [{'key': None}, {'key': 1}, {}]),
            ('nested__key', [{'nested': {'key': None}}, {'nested': {'key': 1}}, {}]),
            ('0', [[None], [1], []]),
            ('items__0', [{'items': [None]}, {'items': [1]}, {}]),
        ):
            with self.subTest(key=key):
                rows = [JSONModel.objects.create(value=value) for value in values]
                condition = Q(**{'value__' + key: None})
                grouped = JSONModel.objects.filter(pk__in=[row.pk for row in rows]).annotate(
                    bucket=Value(1, output_field=IntegerField()),
                ).values('bucket').annotate(n=Count('pk') + Case(
                    When(condition, then=Value(1)), default=Value(0), output_field=IntegerField(),
                ))
                compiler = grouped.query.get_compiler(using='default')
                sql, params = compiler.as_sql()
                self.assertEqual((sql, params), compiler.as_sql())
                # The CASE groups missing and non-null together. Grouping by
                # its raw nullable indicator as well would split that group.
                self.assertTrue(sql.split(' GROUP BY ', 1)[1].endswith('ELSE %s END'))
                self.assertCountEqual(grouped, [{'bucket': 1, 'n': 2}, {'bucket': 1, 'n': 2}])

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_filtered_aggregate_over_materialized_aggregate(self):
        for key, values in (
            ('key', [{'key': None}, {'key': 1}, {}]),
            ('nested__key', [{'nested': {'key': None}}, {'nested': {'key': 1}}, {}]),
            ('0', [[None], [1], []]),
            ('items__0', [{'items': [None]}, {'items': [1]}, {}]),
        ):
            with self.subTest(key=key):
                rows = [JSONModel.objects.create(value=value) for value in values]
                queryset = JSONModel.objects.filter(pk__in=[row.pk for row in rows]).values('pk').annotate(
                    payload=Max('value', output_field=JSONField()),
                )
                condition = Q(**{'payload__' + key: None})
                self.assertEqual(queryset.aggregate(
                    null_count=Count('payload', filter=condition),
                    non_null_count=Count('payload', filter=~condition),
                ), {'null_count': 1, 'non_null_count': 1})

    @skipUnless(VERSION >= (4, 2), 'Filtering against window functions requires Django 4.2')
    @skipUnlessDBFeature('supports_json_openjson', 'supports_over_clause')
    def test_json_null_keys_across_window_filter_rewrites(self):
        for key, values in (
            ('key', [{'key': None}, {'key': 1}, {}, {'key': 'null'}]),
            ('nested__key', [{'nested': {'key': None}}, {'nested': {'key': 1}}, {}, {'nested': {'key': 'null'}}]),
            ('0', [[None], [1], [], ['null']]),
            ('items__0', [{'items': [None]}, {'items': [1]}, {}, {'items': ['null']}]),
        ):
            with self.subTest(key=key):
                rows = [JSONModel.objects.create(value=value) for value in values]
                queryset = JSONModel.objects.filter(pk__in=[row.pk for row in rows]).annotate(
                    rn=Window(RowNumber(), order_by='pk'),
                )
                condition = Q(**{'value__' + key: None})
                # The OR forces the JSON predicate into the outer window
                # filtering query. Mask the document to exercise extra selects.
                included = queryset.filter(Q(rn__lte=0) | condition).values_list('pk', flat=True)
                compiler = included.query.get_compiler(using='default')
                self.assertEqual(compiler.as_sql(), compiler.as_sql())
                self.assertSequenceEqual(included, [rows[0].pk])
                if VERSION >= (6, 1):
                    self.assertSequenceEqual(
                        queryset.filter(
                            Q(rn__lte=0) | Q(**{'value__' + key + '__iexact': None}),
                        ).values_list('pk', flat=True),
                        [rows[0].pk],
                    )
                self.assertSequenceEqual(
                    queryset.filter(Q(rn__lte=0) | ~condition).order_by('pk').values_list('pk', flat=True),
                    [rows[1].pk, rows[3].pk],
                )
                window_payload = queryset.annotate(
                    payload=Window(Max('value', output_field=JSONField()), partition_by='pk'),
                )
                self.assertSequenceEqual(
                    window_payload.filter(**{'payload__' + key: None}).values_list('pk', flat=True),
                    [rows[0].pk],
                )

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_keys_in_check_constraints_not_supported(self):
        schema_editor = connections['default'].schema_editor()
        for lookup in ('value__key', 'value__nested__key', 'value__0', 'value__items__0'):
            with self.subTest(lookup=lookup):
                condition = Q(**{lookup: None})
                kwargs = {'condition' if VERSION >= (5, 1) else 'check': condition}
                constraint = CheckConstraint(name='json_null_key', **kwargs)
                with self.assertRaisesMessage(
                    NotSupportedError,
                    'JSON-null key lookups are not supported in SQL Server CHECK constraints.',
                ):
                    constraint._get_check_sql(JSONModel, schema_editor)

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_keys_in_join_predicates(self):
        for key, values in (
            ('key', [{'key': None}, {'key': 1}, {}]),
            ('nested__key', [{'nested': {'key': None}}, {'nested': {'key': 1}}, {}]),
            ('0', [[None], [1], []]),
            ('items__0', [{'items': [None]}, {'items': [1]}, {}]),
        ):
            with self.subTest(key=key):
                authors = [Author.objects.create(name=str(index)) for index in range(3)]
                for author, value in zip(authors, values):
                    Post.objects.create(author=author, title=json.dumps(value))
                # Exercise JSON transforms in a real related table's ON clause
                # using JSON text in the existing title field.
                with patch.object(Post._meta.get_field('title'), 'get_transform', JSONField().get_transform):
                    queryset = Author.objects.filter(pk__in=[author.pk for author in authors]).annotate(
                        null_post=FilteredRelation('post', condition=Q(**{'post__title__' + key: None})),
                    ).filter(null_post__isnull=False)
                    self.assertSequenceEqual(queryset, authors[:1])

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_keys_in_aggregate_dependent_lookups(self):
        for key, values in (
            ('key', [{'key': None}, {'key': 1}, {}]),
            ('nested__key', [{'nested': {'key': None}}, {'nested': {'key': 1}}, {}]),
            ('0', [[None], [1], []]),
            ('items__0', [{'items': [None]}, {'items': [1]}, {}]),
        ):
            with self.subTest(key=key):
                rows = [JSONModel.objects.create(value=value) for value in values]
                queryset = JSONModel.objects.filter(pk__in=[row.pk for row in rows]).values('pk').annotate(
                    payload=Max('value', output_field=JSONField()),
                )
                condition = {'payload__' + key: None}
                self.assertSequenceEqual(queryset.filter(**condition).values_list('pk', flat=True), [rows[0].pk])
                self.assertSequenceEqual(queryset.exclude(**condition).values_list('pk', flat=True), [rows[1].pk])

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_keys_preserve_trailing_spaces(self):
        for key in ('key', 'café', '💡', "o'reilly"):
            for nested in (False, True):
                with self.subTest(key=key, nested=nested):
                    values = [
                        {key: None, key + ' ': 1},
                        {key: 1, key + ' ': None},
                        {key + ' ': None},
                        {},
                    ]
                    rows = [JSONModel.objects.create(
                        value={'nested': value} if nested else value
                    ) for value in values]
                    queryset = JSONModel.objects.filter(pk__in=[row.pk for row in rows])
                    prefix = 'value__nested__' if nested else 'value__'
                    lookup = {prefix + key: None}
                    spaced_lookup = {prefix + key + ' ': None}
                    self.assertSequenceEqual(queryset.filter(**lookup), [rows[0]])
                    self.assertSequenceEqual(queryset.exclude(**lookup), [rows[1]])
                    self.assertSequenceEqual(
                        queryset.filter(**spaced_lookup).order_by('pk'), rows[1:3]
                    )
                    self.assertSequenceEqual(queryset.exclude(**spaced_lookup), [rows[0]])

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_keys_in_filtered_aggregates(self):
        cases = [
            ('value__key', [{'key': None}, {'key': 1}, {}]),
            ('value__nested__key', [
                {'nested': {'key': None}}, {'nested': {'key': 1}}, {'nested': {}}
            ]),
            ('value__0', [[None], [1], []]),
            ('value__items__0', [{'items': [None]}, {'items': [1]}, {'items': []}]),
        ]
        for lookup_name, values in cases:
            with self.subTest(lookup=lookup_name):
                rows = [JSONModel.objects.create(value=value) for value in values]
                queryset = JSONModel.objects.filter(pk__in=[row.pk for row in rows])
                condition = Q(**{lookup_name: None})
                for source in (queryset, queryset.distinct(), queryset.order_by('pk')[:3]):
                    self.assertEqual(source.aggregate(
                        null_count=Count('pk', filter=condition),
                        non_null_count=Count('pk', filter=~condition),
                    ), {'null_count': 1, 'non_null_count': 1})
                self.assertEqual(queryset.annotate(
                    payload=Value({'key': None}, output_field=JSONField())
                ).aggregate(n=Count('pk', filter=Q(payload__key=None))), {'n': 3})

    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_keys_in_grouped_case_annotations(self):
        cases = [
            ('value__key', [{'key': None}, {'key': 1}, {}]),
            ('value__nested__key', [
                {'nested': {'key': None}}, {'nested': {'key': 1}}, {'nested': {}}
            ]),
            ('value__0', [[None], [1], []]),
            ('value__items__0', [{'items': [None]}, {'items': [1]}, {'items': []}]),
        ]
        for lookup_name, values in cases:
            with self.subTest(lookup=lookup_name):
                rows = [JSONModel.objects.create(value=value) for value in values]
                queryset = JSONModel.objects.filter(pk__in=[row.pk for row in rows])
                grouped = queryset.annotate(flag=Case(
                    When(Q(**{lookup_name: None}), then=Value(1)),
                    default=Value(0), output_field=IntegerField(),
                )).values('flag').annotate(n=Count('pk')).order_by('flag')
                compiler = grouped.query.get_compiler(using='default')
                self.assertEqual(compiler.as_sql(), compiler.as_sql())
                self.assertSequenceEqual(
                    grouped, [{'flag': 0, 'n': 2}, {'flag': 1, 'n': 1}]
                )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    @skipUnlessDBFeature('supports_json_openjson')
    def test_json_null_numeric_key_uses_array_index_semantics(self):
        array_null = JSONModel.objects.create(value=[None])
        nested_array_null = JSONModel.objects.create(value={"items": [None]})
        JSONModel.objects.create(value={"0": None})
        JSONModel.objects.create(value={"items": {"0": None}})
        JSONModel.objects.create(value=["value"])

        self.assertSequenceEqual(JSONModel.objects.filter(value__0=None), [array_null])
        self.assertSequenceEqual(
            JSONModel.objects.filter(value__items__0=None),
            [nested_array_null],
        )

        with self.assertRaises(NotSupportedError):
            list(JSONModel.objects.filter(**{"value__-1": None}))

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_numeric_json_key_ascending(self):
        # Regression coverage for compiler ORDER BY rewrite:
        # JSON key transforms should sort numerically (not lexicographically)
        # when numeric-like payloads are present.
        rows = [
            JSONModel.objects.create(value={"ord": 93, "name": "bar"}),
            JSONModel.objects.create(value={"ord": 22.1, "name": "foo"}),
            JSONModel.objects.create(value={"ord": -1, "name": "baz"}),
            JSONModel.objects.create(value={"ord": 21.931902, "name": "spam"}),
            JSONModel.objects.create(value={"ord": -100291029, "name": "eggs"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by("value__ord")
        self.assertSequenceEqual(queryset, [rows[4], rows[2], rows[3], rows[1], rows[0]])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_numeric_json_key_descending(self):
        # Descending path exercises the same rewrite branch with DESC handling.
        rows = [
            JSONModel.objects.create(value={"ord": 5, "name": "a"}),
            JSONModel.objects.create(value={"ord": -2.5, "name": "b"}),
            JSONModel.objects.create(value={"ord": 11, "name": "c"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by("-value__ord")
        self.assertSequenceEqual(queryset, [rows[2], rows[0], rows[1]])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_non_numeric_json_key_fallback(self):
        # Mixed non-numeric content should still be deterministic and should not
        # fail conversion: backend falls back to text ordering as secondary key.
        rows = [
            JSONModel.objects.create(value={"ord": "b", "name": "first"}),
            JSONModel.objects.create(value={"ord": "a", "name": "second"}),
            JSONModel.objects.create(value={"ord": "c", "name": "third"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by("value__ord")
        self.assertSequenceEqual(queryset, [rows[1], rows[0], rows[2]])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_duplicate_numeric_json_key_deduplicated(self):
        # Regression for fast-path ordering rewrite + dedupe interaction.
        # Duplicate order_by entries must not produce duplicate ORDER BY
        # expressions, otherwise SQL Server can fail with error 169.
        rows = [
            JSONModel.objects.create(value={"ord": 3, "name": "c"}),
            JSONModel.objects.create(value={"ord": 1, "name": "a"}),
            JSONModel.objects.create(value={"ord": 2, "name": "b"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by(
            "value__ord", "value__ord"
        )

        # Execute once and inspect SQL text generated by compiler to assert
        # de-duplication happened on transformed ORDER BY fragments.
        with CaptureQueriesContext(connections['default']) as captured:
            result = list(queryset)

        self.assertSequenceEqual(result, [rows[1], rows[2], rows[0]])

        # The numeric conversion expression should appear only once even though
        # the same order clause is requested twice.
        select_sql = captured[-1]["sql"]
        self.assertEqual(select_sql.upper().count("TRY_CONVERT(FLOAT"), 1)
