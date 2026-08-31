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


if __name__ == "__main__":
    unittest.main()
