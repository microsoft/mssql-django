# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

# Settings for the parallel-cloning smoke test: identical to testapp.settings
# but using Django's stock DiscoverRunner instead of the project's custom
# XML/expected-failure runner, which does not support parallel workers. Driven
# by testapp.tests.test_creation_cloning.DatabaseCloningTests.
from testapp.settings import *  # noqa: F401,F403

TEST_RUNNER = "django.test.runner.DiscoverRunner"
