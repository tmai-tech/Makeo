import base64
import importlib.util
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "notebooks" / "colab_worker.py"
_spec = importlib.util.spec_from_file_location("colab_worker", _SRC)
colab_worker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(colab_worker)
decode_image_field = colab_worker.decode_image_field


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


if __name__ == "__main__":
    unittest.main()
