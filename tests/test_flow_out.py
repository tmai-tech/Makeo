"""PR 4: job-id filenames and --out sidecar source."""

import os
import unittest

import flow_video


class DestName(unittest.TestCase):
    def test_job_id(self):
        os.environ["MAKEO_JOB_ID"] = "abc123"
        try:
            self.assertEqual(flow_video.dest_name(), "flow-abc123.mp4")
        finally:
            os.environ.pop("MAKEO_JOB_ID", None)

    def test_timestamp_without_job(self):
        os.environ.pop("MAKEO_JOB_ID", None)
        self.assertEqual(flow_video.dest_name(now=1700000000), "flow-1700000000.mp4")


if __name__ == "__main__":
    unittest.main()
