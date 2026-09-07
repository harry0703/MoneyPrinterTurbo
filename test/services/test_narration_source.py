import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.narration_source import NarrationSourceService


class TestNarrationSourceService(unittest.TestCase):
    def test_resolve_text_normalizes_manual_text(self):
        service = NarrationSourceService()
        resolved = service.resolve_text("Linea uno\n\n  Linea dos  ")
        self.assertEqual(resolved, "Linea uno\n\nLinea dos")

    def test_extract_pdf_text_reads_long_pdf_text(self):
        service = NarrationSourceService()
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "book.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            fake_pages = [
                type("FakePage", (), {"extract_text": lambda self: "Capitulo uno\n\nTexto largo del audiolibro"})(),
                type("FakePage", (), {"extract_text": lambda self: "Capitulo dos\n\nMas contenido"})(),
            ]
            fake_reader = type("FakeReader", (), {"pages": fake_pages})

            with patch("pypdf.PdfReader", return_value=fake_reader):
                extracted = service.extract_pdf_text(pdf_path)

            self.assertIn("Capitulo uno", extracted)
            self.assertIn("Texto largo del audiolibro", extracted)
            self.assertIn("Capitulo dos", extracted)


if __name__ == "__main__":
    unittest.main()