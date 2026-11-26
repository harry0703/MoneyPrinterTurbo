# -*- coding: utf-8 -*-
import unittest

from app.services.personal_studio import script
from app.services.personal_studio.presets import (
    ASPECT_SIZES,
    NARRATION_STYLES,
    PLATFORMS,
    PRODUCTION_MODES,
    QUALITY_PROFILES,
)


class TestPresets(unittest.TestCase):
    def test_all_platforms_map_to_a_known_aspect(self):
        for key, value in PLATFORMS.items():
            self.assertIn(value["aspect"], ASPECT_SIZES, key)
            self.assertGreater(value["max_seconds"], 0)

    def test_quality_profiles_keep_required_render_fields(self):
        for profile in QUALITY_PROFILES.values():
            for field in ("max_height", "fps", "crf", "preset", "work_width", "verified"):
                self.assertIn(field, profile)

    def test_seven_production_modes(self):
        self.assertEqual(len(PRODUCTION_MODES), 7)
        self.assertTrue(all(mode["kind"] in {"video", "audio"} for mode in PRODUCTION_MODES.values()))

    def test_ten_narration_styles(self):
        self.assertGreaterEqual(len(NARRATION_STYLES), 10)
        for style in NARRATION_STYLES.values():
            self.assertIn("pacing", style)


class TestScriptPreparation(unittest.TestCase):
    def test_expands_thousands_percent_and_decimals(self):
        text = script.expand_numbers(
            "Cuesta $49.900, sube 15% y mide 4.5 puntos. El año 2026 tiene 123 casos."
        )
        self.assertIn("cuarenta y nueve mil novecientos pesos", text)
        self.assertIn("quince por ciento", text)
        self.assertIn("cuatro coma cinco", text)
        self.assertIn("dos mil veintiséis", text)
        self.assertIn("ciento veintitrés", text)

    def test_does_not_capture_trailing_punctuation(self):
        self.assertEqual(script.expand_numbers("Son 3."), "Son tres.")
        self.assertEqual(script.expand_numbers("Son 3, luego 4"), "Son tres, luego cuatro")

    def test_glossary_is_conservative_and_optional(self):
        self.assertIn("wifi", script.apply_glossary("Configura el Wi-Fi", True))
        self.assertIn("Wi-Fi", script.apply_glossary("Configura el Wi-Fi", False))

    def test_segmentation_adds_pauses_and_splits_long_text(self):
        segments = script.segment_script(
            "Buenos días. " + "Esta frase es muy larga y debe dividirse en partes claras, "
            "sin perder el sentido, aunque el estilo sea pausado. ¿Necesitas ayuda?",
            "educativo",
        )
        self.assertGreaterEqual(len(segments), 3)
        self.assertTrue(all(item["text"] for item in segments))
        self.assertTrue(all(0.0 < item["pause_after"] <= 0.6 for item in segments[:-1]))
        self.assertTrue(segments[0]["text"].endswith("."))

    def test_empty_script_is_rejected(self):
        with self.assertRaises(ValueError):
            script.segment_script("   ", "profesional")

    def test_estimate_duration_is_positive(self):
        segments = script.segment_script("Hola mundo.", "conversacional")
        self.assertGreaterEqual(script.estimate_duration(segments), 1.0)


if __name__ == "__main__":
    unittest.main()
