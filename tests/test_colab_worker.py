import base64
import importlib.util
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "notebooks" / "colab_worker.py"
_spec = importlib.util.spec_from_file_location("colab_worker", _SRC)
colab_worker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(colab_worker)
decode_image_field = colab_worker.decode_image_field
parse_tryon_payload = colab_worker.parse_tryon_payload


class DecodeImageField(unittest.TestCase):
    def test_raw_base64(self):
        raw = b"hello-makeo"
        self.assertEqual(decode_image_field(base64.b64encode(raw).decode()), raw)

    def test_data_url(self):
        raw = b"png-bytes"
        payload = "data:image/png;base64," + base64.b64encode(raw).decode()
        self.assertEqual(decode_image_field(payload), raw)

    def test_empty(self):
        with self.assertRaises(ValueError):
            decode_image_field("")


class ParseTryonPayload(unittest.TestCase):
    def test_data_urls(self):
        raw = b"abc"
        b64 = base64.b64encode(raw).decode()
        got = parse_tryon_payload({
            "person": "data:image/jpeg;base64," + b64,
            "garment": b64,
            "category": "tops",
        })
        self.assertEqual(got["person"], raw)
        self.assertEqual(got["garment"], raw)
        self.assertEqual(got["category"], "tops")
        self.assertEqual(got["steps"], 20)

    def test_missing_images(self):
        with self.assertRaises(ValueError):
            parse_tryon_payload({"person": "xxxx"})


class QualityLog(unittest.TestCase):
    def test_writes_inputs_result_and_index(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            png = bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
            )
            meta = colab_worker.write_quality_log(
                person=b"person-bytes",
                garment=b"garment-bytes",
                result_png=png,
                category="one-pieces",
                garment_photo_type="flat-lay",
                steps=20,
                guidance=1.5,
                seed=42,
                elapsed_ms=12,
                root=root,
            )
            dest = root / meta["id"]
            self.assertTrue((dest / "person.jpg").is_file())
            self.assertTrue((dest / "garment.jpg").is_file())
            self.assertTrue((dest / "result.png").is_file())
            self.assertTrue((dest / "meta.json").is_file())
            listed = colab_worker.list_quality_logs(root=root)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["category"], "one-pieces")
            self.assertTrue(listed[0]["ok"])

    def test_failure_is_logged(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            meta = colab_worker.write_quality_log(
                person=b"p", garment=b"g", result_png=None,
                category="tops", garment_photo_type="model",
                steps=10, guidance=1.0, seed=1, error="oom", root=Path(td),
            )
            self.assertFalse(meta["ok"])
            self.assertEqual(meta["error"], "oom")


class WorkerUiPage(unittest.TestCase):
    def test_bridge_page(self):
        html = colab_worker.WORKER_UI_HTML
        self.assertIn("Waiting for Makeo", html)
        self.assertIn("/tryon", html)
        self.assertIn("postMessage", html)
        self.assertIn("tmai-tech.github.io", html)

    def test_dead_url_is_unhealthy(self):
        self.assertFalse(colab_worker._health_ok("http://127.0.0.1:9", timeout=0.2))


if __name__ == "__main__":
    unittest.main()
