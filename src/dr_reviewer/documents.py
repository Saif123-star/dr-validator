from __future__ import annotations

import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree


_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_TEXT_FILE_BYTES = 50 * 1024 * 1024
_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "pre",
    "section",
    "tr",
}


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _archive_members(path: Path) -> ZipFile:
    try:
        archive = ZipFile(path)
    except BadZipFile as exc:
        raise ValueError(f"{path.name} is not a valid ZIP-based document") from exc
    if sum(info.file_size for info in archive.infolist()) > _MAX_ARCHIVE_BYTES:
        archive.close()
        raise ValueError(f"{path.name} expands beyond the supported document size")
    return archive


def _parse_xml(data: bytes, path: Path, member: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(f"{path.name} contains invalid XML in {member}") from exc


def _extract_docx(path: Path) -> str:
    archive = _archive_members(path)
    try:
        names = [
            name
            for name in archive.namelist()
            if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", name)
        ]
        if "word/document.xml" not in names:
            raise ValueError(f"{path.name} is missing word/document.xml")
        ordered_names = ["word/document.xml"] + sorted(
            name for name in names if name != "word/document.xml"
        )
        paragraphs: list[str] = []
        for name in ordered_names:
            root = _parse_xml(archive.read(name), path, name)
            for element in root.iter():
                if _local_name(element.tag) != "p":
                    continue
                text = "".join(
                    child.text or ""
                    for child in element.iter()
                    if _local_name(child.tag) in {"t", "delText"}
                ).strip()
                if text:
                    paragraphs.append(text)
        return "\n".join(paragraphs)
    finally:
        archive.close()


def _extract_xlsx(path: Path) -> str:
    archive = _archive_members(path)
    try:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
            raise ValueError(f"{path.name} is missing workbook metadata")

        workbook = _parse_xml(archive.read("xl/workbook.xml"), path, "xl/workbook.xml")
        relationships = _parse_xml(
            archive.read("xl/_rels/workbook.xml.rels"),
            path,
            "xl/_rels/workbook.xml.rels",
        )
        targets = {
            relation.attrib.get("Id", ""): relation.attrib.get("Target", "")
            for relation in relationships.iter()
            if _local_name(relation.tag) == "Relationship"
        }

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared_root = _parse_xml(
                archive.read("xl/sharedStrings.xml"), path, "xl/sharedStrings.xml"
            )
            shared_strings = [
                "".join(node.text or "" for node in item.iter() if _local_name(node.tag) == "t")
                for item in shared_root.iter()
                if _local_name(item.tag) == "si"
            ]

        output: list[str] = []
        for sheet in workbook.iter():
            if _local_name(sheet.tag) != "sheet":
                continue
            sheet_name = sheet.attrib.get("name", "Unnamed sheet")
            relation_id = next(
                (value for key, value in sheet.attrib.items() if _local_name(key) == "id"),
                "",
            )
            target = targets.get(relation_id)
            if not target:
                raise ValueError(f"{path.name} has no worksheet relationship for {sheet_name}")
            target = target.replace("\\", "/")
            member = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
            if not member.startswith("xl/") or member not in names:
                raise ValueError(f"{path.name} has an invalid worksheet path for {sheet_name}")

            worksheet = _parse_xml(archive.read(member), path, member)
            output.append(f"Sheet: {sheet_name}")
            for row in worksheet.iter():
                if _local_name(row.tag) != "row":
                    continue
                values: list[str] = []
                for cell in row:
                    if _local_name(cell.tag) != "c":
                        continue
                    reference = cell.attrib.get("r", "")
                    cell_type = cell.attrib.get("t", "")
                    value_node = next(
                        (node for node in cell if _local_name(node.tag) == "v"),
                        None,
                    )
                    value = value_node.text if value_node is not None else ""
                    if cell_type == "s" and value:
                        try:
                            value = shared_strings[int(value)]
                        except (ValueError, IndexError) as exc:
                            raise ValueError(
                                f"{path.name} has an invalid shared-string reference"
                            ) from exc
                    elif cell_type == "inlineStr":
                        value = "".join(
                            node.text or ""
                            for node in cell.iter()
                            if _local_name(node.tag) == "t"
                        )
                    if not value:
                        formula = next(
                            (node for node in cell if _local_name(node.tag) == "f"),
                            None,
                        )
                        value = f"={formula.text}" if formula is not None and formula.text else ""
                    if value:
                        values.append(f"{reference}={value}" if reference else value)
                if values:
                    output.append(" | ".join(values))
        return "\n".join(output)
    finally:
        archive.close()


def extract_text(path: Path) -> tuple[str, str]:
    """Return extracted text and an extraction status for a snapshotted file."""
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        text = _extract_docx(path)
        return text, "extracted" if text else "empty"
    if suffix == ".xlsx":
        text = _extract_xlsx(path)
        return text, "extracted" if text else "empty"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}:
        return "", "non_text"
    if suffix in {".pdf", ".doc", ".xls", ".ppt", ".pptx"}:
        return "", "unsupported"
    if path.stat().st_size > _MAX_TEXT_FILE_BYTES:
        raise ValueError(f"{path.name} exceeds the supported text-file size")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path.name} is not valid UTF-8 text") from exc
    if suffix in {".html", ".htm"}:
        parser = _HTMLTextParser()
        parser.feed(text)
        text = "".join(parser.parts)
    return text, "extracted" if text.strip() else "empty"


def normalize_quote(text: str) -> str:
    return " ".join(text.split()).casefold()
