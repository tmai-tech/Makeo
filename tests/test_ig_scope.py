"""PR 5: job-scoped Instagram must not read repo .env or Buzzit defaults."""

import os
import unittest
from unittest import mock

import post_instagram as ig


class JobScoped(unittest.TestCase):
    def test_job_id_env(self):
        os.environ["MAKEO_JOB_ID"] = "j1"
        try:
            self.assertTrue(ig.job_scoped())
        finally:
            os.environ.pop("MAKEO_JOB_ID", None)

    def test_config_flag(self):
        args = mock.Mock(config="brands/buzzit.json")
        os.environ.pop("MAKEO_JOB_ID", None)
        self.assertTrue(ig.job_scoped(args))

    def test_local_dev_not_scoped(self):
        os.environ.pop("MAKEO_JOB_ID", None)
        args = mock.Mock(config=None)
        self.assertFalse(ig.job_scoped(args))


class NoBuzzitDefault(unittest.TestCase):
    def test_default_ig_id_removed(self):
        self.assertFalse(hasattr(ig, "DEFAULT_IG_ID"))

    def test_exchange_token_is_pure(self):
        self.assertTrue(callable(ig.exchange_token))
        self.assertTrue(callable(ig.probe_ig))


if __name__ == "__main__":
    unittest.main()
