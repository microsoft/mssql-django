from django.test.runner import DiscoverRunner
from django.conf import settings

from unittest import skip
import xmlrunner

EXCLUDED_TESTS = getattr(settings, 'EXCLUDED_TESTS', [])
REGEX_TESTS = getattr(settings, 'REGEX_TESTS', [])

ENABLE_REGEX_TESTS = getattr(settings, 'ENABLE_REGEX_TESTS', False)


class ExcludedTestSuiteRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        tests = []
        for case in suite:
            test_name = case._testMethodName
            if ENABLE_REGEX_TESTS:
                if case.id() in EXCLUDED_TESTS:
                    setattr(case, test_name, skip("Not supported")(getattr(case, test_name)))
            else:
                if case.id() in EXCLUDED_TESTS + REGEX_TESTS:
                    setattr(case, test_name, skip("Not supported")(getattr(case, test_name)))
            tests.append(case)
        suite._tests = tests
        return suite

    def run_suite(self, suite):
        kwargs = dict(
            verbosity=1, descriptions=False,
            failfast=self.failfast)

        with open('./result.xml', 'wb') as xml:
            return xmlrunner.XMLTestRunner(
                output=xml, **kwargs).run(suite)
