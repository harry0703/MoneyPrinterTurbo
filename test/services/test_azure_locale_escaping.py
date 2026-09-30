import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from app.services import voice


class TestAzureLocaleEscaping(unittest.TestCase):
    def test_supplied_v2_voice_cannot_inject_ssml_attributes_or_break_xml(self):
        for locale in ('en-US" data_injected="yes', 'en-US&unexpected'):
            with self.subTest(locale=locale):
                supplied_voice = f"{locale}-AriaNeural-V2-Female"
                captured = {}
                def synthesize(text, voice_name, voice_file, voice_rate):
                    normalized = voice.is_azure_v2_voice(voice_name)
                    captured["ssml"] = voice._build_azure_v2_ssml(text, normalized, voice_rate)
                    return "synthesis sentinel"
                with patch.object(voice, "azure_tts_v2", side_effect=synthesize) as sdk_path:
                    result = voice._single_tts("Hello & goodbye.", supplied_voice, 1, "unused.mp3", 1)
                self.assertEqual(result, "synthesis sentinel")
                sdk_path.assert_called_once()
                document = ET.fromstring(captured["ssml"])
                self.assertEqual(set(document.attrib), {"version", "{http://www.w3.org/XML/1998/namespace}lang"})
                self.assertEqual(document.attrib["{http://www.w3.org/XML/1998/namespace}lang"], locale)
                self.assertEqual(document.find(".//{http://www.w3.org/2001/10/synthesis}prosody").text, "Hello & goodbye.")
