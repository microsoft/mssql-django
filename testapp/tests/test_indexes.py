import django.db
from django.test import TestCase

from ..models import (
    TestIndexesRetainedRenamed
)


class TestIndexesRetained(TestCase):
    """
    Indexes dropped during a migration should be re-created afterwards
    assuming the field still has `db_index=True` (issue #58)
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Pre-fetch which indexes exist for the relevant test model
        # now that all the test migrations have run
        connection = django.db.connections[django.db.DEFAULT_DB_ALIAS]
        cls.constraints = connection.introspection.get_constraints(
            connection.cursor(),
            table_name=TestIndexesRetainedRenamed._meta.db_table
        )
        cls.indexes = {k: v for k, v in cls.constraints.items() if v['index'] is True}

    def _assert_index_exists(self, columns):
        matching = {k: v for k, v in self.indexes.items() if set(v['columns']) == columns}
        assert len(matching) == 1, (
            "Expected 1 index for columns %s but found %d %s" % (
                columns,
                len(matching),
                ', '.join(matching.keys())
            )
        )

    def test_field_made_nullable(self):
        # Issue #58 case (a)
        self._assert_index_exists({'a'})

    def test_field_renamed(self):
        # Issue #58 case (b)
        self._assert_index_exists({'b_renamed'})

    def test_table_renamed(self):
        # Issue #58 case (c)
        self._assert_index_exists({'c'})
