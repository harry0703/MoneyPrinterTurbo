from __future__ import annotations

import re
from pathlib import Path


class NarrationSourceService:
    def resolve_text(
        self,
        prompt: str,
        content_source: str = "text",
        pdf_path: str | Path | None = None,
    ) -> str:
        source = (content_source or "text").strip().lower()
        if source == "pdf":
            if not pdf_path:
                raise ValueError("Please upload a PDF to generate the audiobook.")
            return self.extract_pdf_text(pdf_path)

        text = self.normalize_text(prompt)
        if not text:
            raise ValueError("The narration text cannot be empty.")
        return text

    def extract_pdf_text(self, pdf_path: str | Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "Missing pypdf dependency. Install project requirements to use PDF audiobooks."
            ) from exc

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")

        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise ValueError(
                "The PDF could not be read. Verify that it is not damaged or protected."
            ) from exc

        chunks: list[str] = []
        for page in reader.pages:
            text = self.normalize_text(page.extract_text() or "")
            if text:
                chunks.append(text)

        merged = "\n\n".join(chunks).strip()
        if not merged:
            raise ValueError(
                "The PDF does not contain readable text. If it is a scan, run OCR first."
            )
        return merged

    def normalize_text(self, text: str) -> str:
        value = (text or "").replace("\r", "\n").replace("\u00a0", " ")
        lines = [re.sub(r"\s+", " ", line).strip() for line in value.split("\n")]
        paragraphs = [line for line in lines if line]
        return "\n\n".join(paragraphs).strip()