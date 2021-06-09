from django.test.runner import DiscoverRunner
from django.conf import settings

import xmlrunner

EXCLUDED_TESTS = getattr(settings, 'EXCLUDED_TESTS', [])
REGEX_TESTS = getattr(settings, 'REGEX_TESTS', [])

ENABLE_REGEX_TESTS = getattr(settings, 'ENABLE_REGEX_TESTS', False)


def MarkexpectedFailure():
    def decorator(test_item):
        def wrapper():
            raise "Expected Failure"
        wrapper.__unittest_expecting_failure__ = True
        return wrapper
    return decorator

class ExcludedTestSuiteRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        tests = []
        for case in suite:
            test_name = case._testMethodName
            if ENABLE_REGEX_TESTS:
                if case.id() in EXCLUDED_TESTS:
                    test_method = getattr(case, test_name)
                    setattr(case, test_name, MarkexpectedFailure()(test_method))
            else:
                if case.id() in EXCLUDED_TESTS + REGEX_TESTS:
                    test_method = getattr(case, test_name)
                    setattr(case, test_name, MarkexpectedFailure()(test_method))
            tests.append(case)
        suite._tests = tests
        return suite

    def run_suite(self, suite):
        kwargs = dict(verbosity=1, descriptions=False)

        with open('./result.xml', 'wb') as xml:
            return xmlrunner.XMLTestRunner(
                output=xml, **kwargs).run(suite)
