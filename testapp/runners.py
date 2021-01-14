from django.test.runner import DiscoverRunner
from django.conf import settings

EXCLUDED_TESTS = getattr(settings, 'EXCLUDED_TESTS', [])


class ExcludedTestSuiteRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        tests = []
        for case in suite:
            if not case.id() in EXCLUDED_TESTS:
                tests.append(case)
        suite._tests = tests
        return suite
