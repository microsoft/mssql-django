"""
ss_loaddata management command, we need to keep close track of changes in
django/core/management/commands/loaddata.py.
"""
import sys
import os
import gzip
import zipfile

from django.core.management.base import BaseCommand
from django.core.management.color import no_style

try:
    set
except NameError:
    from sets import Set as set   # Python 2.3 fallback

try:
    import bz2
    has_bz2 = True
except ImportError:
    has_bz2 = False

class Command(BaseCommand):
    help = 'Installs the named fixture(s) in the database (MS SQL Server-specific).'
    args = "fixture [fixture ...]"

    def __init__(self):
        super(Command, self).__init__()
        self.in_disabled_constraints = False
        self.model_name = None
        self.tables = set()

    def handle(self, *fixture_labels, **options):
        from django.db.models import get_apps
        from django.core import serializers
        from django.db import connection, transaction
        from django.conf import settings

        self.style = no_style()

        verbosity = int(options.get('verbosity', 1))
        show_traceback = options.get('traceback', False)

        # commit is a stealth option - it isn't really useful as
        # a command line option, but it can be useful when invoking
        # loaddata from within another script.
        # If commit=True, loaddata will use its own transaction;
        # if commit=False, the data load SQL will become part of
        # the transaction in place when loaddata was invoked.
        commit = options.get('commit', True)

        # Keep a count of the installed objects and fixtures
        fixture_count = 0
        object_count = 0
        models = set()

        humanize = lambda dirname: dirname and "'%s'" % dirname or 'absolute path'

        # Get a cursor (even though we don't need one yet). This has
        # the side effect of initializing the test database (if
        # it isn't already initialized).
        cursor = connection.cursor()

        # Start transaction management. All fixtures are installed in a
        # single transaction to ensure that all references are resolved.
        if commit:
            transaction.commit_unless_managed()
            transaction.enter_transaction_management()
            transaction.managed(True)

        self.disable_forward_ref_checks()

        class SingleZipReader(zipfile.ZipFile):
            def __init__(self, *args, **kwargs):
                zipfile.ZipFile.__init__(self, *args, **kwargs)
                if settings.DEBUG:
                    assert len(self.namelist()) == 1, "Zip-compressed fixtures must contain only one file."
            def read(self):
                return zipfile.ZipFile.read(self, self.namelist()[0])

        compression_types = {
            None:   file,
            'gz':   gzip.GzipFile,
            'zip':  SingleZipReader
        }
        if has_bz2:
            compression_types['bz2'] = bz2.BZ2File

        app_fixtures = [os.path.join(os.path.dirname(app.__file__), 'fixtures') for app in get_apps()]
        for fixture_label in fixture_labels:
            parts = fixture_label.split('.')

            if len(parts) > 1 and parts[-1] in compression_types:
                compression_formats = [parts[-1]]
                parts = parts[:-1]
            else:
                compression_formats = compression_types.keys()

            if len(parts) == 1:
                fixture_name = parts[0]
                formats = serializers.get_public_serializer_formats()
            else:
                fixture_name, format = '.'.join(parts[:-1]), parts[-1]
                if format in serializers.get_public_serializer_formats():
                    formats = [format]
                else:
                    formats = []

            if formats:
                if verbosity > 1:
                    print "Loading '%s' fixtures..." % fixture_name
            else:
                self.enable_forward_ref_checks(cursor)
                sys.stderr.write(
                    self.style.ERROR("Problem installing fixture '%s': %s is not a known serialization format." %
                        (fixture_name, format)))
                transaction.rollback()
                transaction.leave_transaction_management()
                return

            if os.path.isabs(fixture_name):
                fixture_dirs = [fixture_name]
            else:
                fixture_dirs = app_fixtures + list(settings.FIXTURE_DIRS) + ['']

            for fixture_dir in fixture_dirs:
                if verbosity > 1:
                    print "Checking %s for fixtures..." % humanize(fixture_dir)

                label_found = False
                for format in formats:
                    for compression_format in compression_formats:
                        if compression_format:
                            file_name = '.'.join([fixture_name, format,
                                                  compression_format])
                        else:
                            file_name = '.'.join([fixture_name, format])

                        if verbosity > 1:
                            print "Trying %s for %s fixture '%s'..." % \
                                (humanize(fixture_dir), file_name, fixture_name)
                        full_path = os.path.join(fixture_dir, file_name)
                        open_method = compression_types[compression_format]
                        try:
                            fixture = open_method(full_path, 'r')
                            if label_found:
                                fixture.close()
                                self.enable_forward_ref_checks(cursor)
                                print self.style.ERROR("Multiple fixtures named '%s' in %s. Aborting." %
                                    (fixture_name, humanize(fixture_dir)))
                                transaction.rollback()
                                transaction.leave_transaction_management()
                                return
                            else:
                                fixture_count += 1
                                objects_in_fixture = 0
                                if verbosity > 0:
                                    print "Installing %s fixture '%s' from %s." % \
                                        (format, fixture_name, humanize(fixture_dir))
                                try:
                                    objects = serializers.deserialize(format, fixture)
                                    for obj in objects:
                                        objects_in_fixture += 1
                                        self.handle_ref_checks(cursor, obj)
                                        models.add(obj.object.__class__)
                                        obj.save()
                                    object_count += objects_in_fixture
                                    label_found = True
                                except (SystemExit, KeyboardInterrupt):
                                    self.enable_forward_ref_checks(cursor)
                                    raise
                                except Exception:
                                    import traceback
                                    fixture.close()
                                    self.enable_forward_ref_checks(cursor)
                                    transaction.rollback()
                                    transaction.leave_transaction_management()
                                    if show_traceback:
                                        traceback.print_exc()
                                    else:
                                        sys.stderr.write(
                                            self.style.ERROR("Problem installing fixture '%s': %s\n" %
                                                 (full_path, ''.join(traceback.format_exception(sys.exc_type,
                                                     sys.exc_value, sys.exc_traceback)))))
                                    return
                                fixture.close()

                                # If the fixture we loaded contains 0 objects, assume that an
                                # error was encountered during fixture loading.
                                if objects_in_fixture == 0:
                                    self.enable_forward_ref_checks(cursor)
                                    sys.stderr.write(
                                        self.style.ERROR("No fixture data found for '%s'. (File format may be invalid.)" %
                                            (fixture_name)))
                                    transaction.rollback()
                                    transaction.leave_transaction_management()
                                    return

                        except Exception, e:
                            if verbosity > 1:
                                print "No %s fixture '%s' in %s." % \
                                    (format, fixture_name, humanize(fixture_dir))

        self.enable_forward_ref_checks(cursor)

        # If we found even one object in a fixture, we need to reset the
        # database sequences.
        if object_count > 0:
            sequence_sql = connection.ops.sequence_reset_sql(self.style, models)
            if sequence_sql:
                if verbosity > 1:
                    print "Resetting sequences"
                for line in sequence_sql:
                    cursor.execute(line)

        if commit:
            transaction.commit()
            transaction.leave_transaction_management()

        if object_count == 0:
            if verbosity > 1:
                print "No fixtures found."
        else:
            if verbosity > 0:
                print "Installed %d object(s) from %d fixture(s)" % (object_count, fixture_count)

        # Close the DB connection. This is required as a workaround for an
        # edge case in MySQL: if the same connection is used to
        # create tables, load data, and query, the query can return
        # incorrect results. See Django #7572, MySQL #37735.
        if commit:
            connection.close()

    def disable_forward_ref_checks(self):
        self.in_disabled_constraints = True

    def enable_forward_ref_checks(self, cursor):
        # re-activate constraint checks for any remaining table
        # and force a check
        # See also 'DBCC CHECKCONSTRAINTS(%s) WITH NO_INFOMSGS'
        for t in self.tables:
            cursor.execute('ALTER TABLE [%s] WITH CHECK CHECK CONSTRAINT ALL' % t)
        self.tables.clear()
        self.in_disabled_constraints = False

    def handle_ref_checks(self, cursor, obj):
        mobj = obj.object
        if self.in_disabled_constraints:
            # Should we re-activate constraint checks for any table back?
            #if self.model_name is not None and mobj.__class__ != self.model_name:
            #    for t in self.tables:
            #        cursor.execute('ALTER TABLE [%s] WITH CHECK CHECK CONSTRAINT ALL' % t)
            #    self.tables.clear()

            # A model transition is underway in the fixture
            if self.model_name is None or mobj.__class__ != self.model_name:
                # Should we de-activate constraint checks for any table?. Check
                # if the model has any FK defined
                has_outgoing_fks = False
                for f in mobj._meta.fields:
                    if f.rel:
                        has_outgoing_fks = True
                # Also check for m2m fields and take in account its intermediate tables
                # XXX: What about _meta.many_to_many?
                # XXX: Take in account the m2m with 'through' option case
                for f in mobj._meta.local_many_to_many:
                    cursor.execute('ALTER TABLE [%s] NOCHECK CONSTRAINT ALL' % f.m2m_db_table())
                    self.tables.add(f.m2m_db_table())

                if has_outgoing_fks:
                    cursor.execute('ALTER TABLE [%s] NOCHECK CONSTRAINT ALL' % mobj._meta.db_table)
                    self.tables.add(mobj._meta.db_table)
        self.model_name = mobj.__class__
