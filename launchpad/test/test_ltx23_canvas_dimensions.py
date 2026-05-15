#!/usr/bin/env python3
import io
import sys
import types
import unittest
from pathlib import Path

from PIL import Image


SERVERLESS_DIR = Path(__file__).resolve().parents[1] / "serverless"
sys.path.insert(0, str(SERVERLESS_DIR))

sys.modules.setdefault(
    "runpod",
    types.SimpleNamespace(
        serverless=types.SimpleNamespace(start=lambda *args, **kwargs: None)
    ),
)

import rp_handler  # noqa: E402


class Ltx23CanvasDimensionsTest(unittest.TestCase):
    def test_counts_optional_images_for_direct_keyframes(self):
        self.assertEqual(
            rp_handler.count_optional_images(
                {"keyframes": [{"image_url": "a.jpg"}]}
            ),
            0,
        )
        self.assertEqual(
            rp_handler.count_optional_images(
                {"keyframes": [{"image_url": "a.jpg"}, {"image_url": "b.jpg"}]}
            ),
            1,
        )
        self.assertEqual(
            rp_handler.count_optional_images(
                {
                    "keyframes": [
                        {"image_url": "a.jpg"},
                        {"image_url": "b.jpg"},
                        {"image_url": "c.jpg"},
                    ]
                }
            ),
            2,
        )

    def test_counts_optional_images_for_image_array_shape(self):
        self.assertEqual(
            rp_handler.count_optional_images({"images": ["b.jpg", "c.jpg"]}),
            2,
        )

    def test_resolves_explicit_dimensions(self):
        self.assertEqual(
            rp_handler.resolve_canvas_dimensions({"width": "1280", "height": 736}),
            (1280, 736, "1280:736", "custom"),
        )

    def test_requires_width_and_height_together(self):
        with self.assertRaisesRegex(ValueError, "width and height"):
            rp_handler.resolve_canvas_dimensions({"width": 1280})

    def test_resolves_requested_aspect_and_resolution(self):
        self.assertEqual(
            rp_handler.resolve_canvas_dimensions(
                {"aspect_ratio": "9:16", "resolution": "480p"}
            ),
            (480, 864, "9:16", "480p"),
        )

    def test_infers_nearest_supported_ratio_from_image_size(self):
        self.assertEqual(
            rp_handler.resolve_canvas_dimensions({}, (1280, 720)),
            (1280, 736, "16:9", "720p"),
        )
        self.assertEqual(
            rp_handler.resolve_canvas_dimensions({}, (720, 1280)),
            (736, 1280, "9:16", "720p"),
        )
        self.assertEqual(
            rp_handler.resolve_canvas_dimensions({}, (900, 900)),
            (736, 736, "1:1", "720p"),
        )

    def test_returns_none_without_canvas_signal_or_image_size(self):
        self.assertIsNone(rp_handler.resolve_canvas_dimensions({}))

    def test_applies_dimensions_to_canvas_nodes(self):
        workflow = {
            "294": {"inputs": {"width": 736, "height": 1280, "length": 121}},
            "299": {"inputs": {"image": "frame.jpg", "width": 736, "height": 1280}},
            "397": {"inputs": {"image": "frame2.jpg", "width": 736, "height": 1280}},
            "315": {"inputs": {"noise_seed": 42}},
        }

        updated = rp_handler.apply_canvas_dimensions(workflow, 1280, 736)

        self.assertEqual(updated, ["294", "299", "397"])
        self.assertEqual(workflow["294"]["inputs"]["width"], 1280)
        self.assertEqual(workflow["294"]["inputs"]["height"], 736)
        self.assertEqual(workflow["299"]["inputs"]["width"], 1280)
        self.assertEqual(workflow["299"]["inputs"]["height"], 736)
        self.assertEqual(workflow["315"]["inputs"]["noise_seed"], 42)

    def test_probes_image_size(self):
        buffer = io.BytesIO()
        Image.new("RGB", (1280, 720), "black").save(buffer, format="JPEG")

        self.assertEqual(rp_handler.probe_image_size(buffer.getvalue()), (1280, 720))


if __name__ == "__main__":
    unittest.main()
