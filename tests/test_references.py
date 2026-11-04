"""Attached documents must be readable and evidence must match actual source."""

import base64
import io
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from coding_platform.references import (
    extract_reference,
    prepare_references,
    reference_brief,
    verify_reference_review,
)


def encoded(name: str, data: bytes) -> dict[str, str]:
    return {"name": name, "data_base64": base64.b64encode(data).decode()}


def test_text_and_docx_are_extracted_and_injected():
    docx = io.BytesIO()
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Use blue buttons</w:t></w:r></w:p></w:body></w:document>"
    )
    with ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", xml)
    refs = prepare_references(
        [
            encoded("requirements.md", b"The game must keep score."),
            encoded("design.docx", docx.getvalue()),
        ]
    )
    brief = reference_brief(refs)
    assert "The game must keep score." in brief
    assert "Use blue buttons" in brief
    assert all(item["id"] in brief for item in refs)


def test_pdf_text_is_extracted():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 200 Td (Blue button required) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    reference = extract_reference(
        "requirements.pdf", encoded("requirements.pdf", output.getvalue())["data_base64"]
    )
    assert reference["text"] == "Blue button required"


def test_empty_unsupported_and_duplicate_references_are_rejected():
    with pytest.raises(ValueError, match="no readable text"):
        extract_reference("blank.txt", base64.b64encode(b" \n ").decode())
    with pytest.raises(ValueError, match="must be PDF"):
        extract_reference("image.png", base64.b64encode(b"image").decode())
    item = encoded("requirements.md", b"Use blue buttons")
    with pytest.raises(ValueError, match="duplicate"):
        prepare_references([item, item])


def test_review_requires_quote_from_reference_and_evidence_in_real_source():
    ref = extract_reference("requirements.md", base64.b64encode(b"Use blue buttons").decode())
    answer = (
        '{"summary":"done","reference_checks":[{"id":"%s","quote":"blue buttons",'
        '"file":"styles.css","evidence":"background: blue"}]}' % ref["id"]
    )
    assert verify_reference_review(answer, [ref], {"styles.css": "button { background: blue; }"})
    with pytest.raises(ValueError, match="source evidence"):
        verify_reference_review(answer, [ref], {"styles.css": "button { background: red; }"})
    with pytest.raises(ValueError, match="reference quote"):
        verify_reference_review(
            answer.replace("blue buttons", "green buttons"),
            [ref],
            {"styles.css": "button { background: blue; }"},
        )
