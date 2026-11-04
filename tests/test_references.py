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
    prepare_source_reference,
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


def test_long_spec_is_accepted_without_truncation_and_context_is_bounded():
    spec = ("Requirement: keep the original specification intact.\n" * 300).encode()
    reference = extract_reference("long-spec.md", encoded("long-spec.md", spec)["data_base64"])
    assert reference["text"] == spec.decode().strip()
    assert reference["text"] in reference_brief([reference])
    with pytest.raises(ValueError, match="100000 characters"):
        extract_reference("huge-spec.md", encoded("huge-spec.md", b"x" * 100_001)["data_base64"])
    with pytest.raises(ValueError, match="180000 characters"):
        prepare_references([encoded("a.md", b"a" * 95_000), encoded("b.md", b"b" * 95_000)])


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


def test_local_source_is_read_only_reference_with_file_paths():
    source = prepare_source_reference(
        [
            {
                "path": "old-game/src/game.ts",
                "data_base64": base64.b64encode(b"export const score = 0;").decode(),
            },
            {
                "path": "old-game/README.md",
                "data_base64": base64.b64encode(b"Keep scores across rounds.").decode(),
            },
        ]
    )
    assert source["kind"] == "source"
    assert source["files_count"] == 2
    assert "[FILE old-game/src/game.ts]" in source["text"]
    assert "export const score = 0;" in reference_brief([source])
    assert "NEW output" in reference_brief([source])
    assert verify_reference_review(
        '{"reference_checks":[{"id":"%s","quote":"Keep scores across rounds.","file":"new.ts","evidence":"localStorage.setItem"}]}'
        % source["id"],
        [source],
        {"new.ts": "localStorage.setItem('score', score)"},
    )


@pytest.mark.parametrize(
    "path",
    ["old/.env", "old/node_modules/a.js", "old/../secret.py", "C:/secret.py", "old/image.png"],
)
def test_unsafe_source_paths_are_rejected(path):
    with pytest.raises(ValueError, match="unsafe source path"):
        prepare_source_reference(
            [{"path": path, "data_base64": base64.b64encode(b"secret").decode()}]
        )
