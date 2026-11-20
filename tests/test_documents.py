from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from dr_reviewer.documents import extract_text


class DocumentExtractionTests(unittest.TestCase):
    def test_extracts_docx_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.docx"
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="urn:test"><w:body>'
                '<w:p><w:r><w:t>Business rule</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>must be traceable</w:t></w:r></w:p>'
                "</w:body></w:document>"
            )
            with ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)

            text, status = extract_text(path)

        self.assertEqual(status, "extracted")
        self.assertEqual(text, "Business rule\nmust be traceable")

    def test_extracts_xlsx_shared_strings_and_sheet_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.xlsx"
            with ZipFile(path, "w") as archive:
                archive.writestr(
                    "xl/workbook.xml",
                    '<workbook xmlns:r="urn:rel"><sheets>'
                    '<sheet name="Requirements" r:id="rId1"/>'
                    "</sheets></workbook>",
                )
                archive.writestr(
                    "xl/_rels/workbook.xml.rels",
                    '<Relationships><Relationship Id="rId1" '
                    'Target="worksheets/sheet1.xml"/></Relationships>',
                )
                archive.writestr(
                    "xl/sharedStrings.xml",
                    "<sst><si><t>BR-001</t></si><si><t>Required field</t></si></sst>",
                )
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    '<worksheet><sheetData><row r="1">'
                    '<c r="A1" t="s"><v>0</v></c>'
                    '<c r="B1" t="s"><v>1</v></c>'
                    "</row></sheetData></worksheet>",
                )

            text, status = extract_text(path)

        self.assertEqual(status, "extracted")
        self.assertIn("Sheet: Requirements", text)
        self.assertIn("A1=BR-001", text)
        self.assertIn("B1=Required field", text)

    def test_marks_images_as_non_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wireframe.png"
            path.write_bytes(b"image bytes")
            text, status = extract_text(path)

        self.assertEqual(text, "")
        self.assertEqual(status, "non_text")


if __name__ == "__main__":
    unittest.main()
