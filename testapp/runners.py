from django.test.runner import DiscoverRunner
from django.conf import settings

EXCLUDED_TESTS = getattr(settings, 'EXCLUDED_TESTS', [])
REGEX_TESTS = getattr(settings, 'REGEX_TESTS', [])

ENABLE_REGEX_TESTS = getattr(settings, 'ENABLE_REGEX_TESTS', False)


class ExcludedTestSuiteRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        tests = []
        for case in suite:
            if ENABLE_REGEX_TESTS:
                if not case.id() in EXCLUDED_TESTS:
                    tests.append(case)
            else:
                if not case.id() in EXCLUDED_TESTS + REGEX_TESTS:
                    tests.append(case)
        suite._tests = tests
        return suite
