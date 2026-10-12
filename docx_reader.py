"""In-memory DOCX body extraction with paragraph/table locations, never page numbers."""
from io import BytesIO
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from docx import Document
from docx.text.paragraph import Paragraph

MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2000
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_LOCATIONS = 10000
WORD_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'


class DocxError(ValueError):
    """A safe message that contains no uploaded content."""


def check_package(contents):
    """Validate the OOXML package and bound ZIP expansion before python-docx reads it.

    Never unzip to disk or fetch external relationships. Macro-enabled packages and
    XML DTDs/entities are unsupported, even if someone renames their extension.
    """
    if not contents.startswith(b'PK\x03\x04'):
        raise DocxError('This file is not a valid DOCX. Save it as a Word Document (.docx).')
    try:
        with ZipFile(BytesIO(contents)) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(members) > MAX_ARCHIVE_MEMBERS or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
                raise DocxError('This DOCX expands beyond the safe processing limit. Please use a smaller document.')
            if len(set(names)) != len(names) or any(m.flag_bits & 1 for m in members):
                raise DocxError('Encrypted or duplicate-entry DOCX packages are not supported.')
            if any('vbaproject' in name.lower() for name in names):
                raise DocxError('Macro-enabled Word files are not supported. Save a macro-free .docx copy.')
            if not {'[Content_Types].xml', 'word/document.xml', '_rels/.rels'}.issubset(names):
                raise DocxError('This file is not a valid DOCX document package.')
            for member in members:
                if member.filename.lower().endswith(('.xml', '.rels')):
                    xml = archive.read(member)
                    # Also catches UTF-16 XML declarations; rejects rather than interpreting entities.
                    declarations = xml.replace(b'\x00', b'').lower()
                    if b'<!doctype' in declarations or b'<!entity' in declarations:
                        raise DocxError('DOCX XML declarations with DTDs or entities are not supported.')
            types = ElementTree.fromstring(archive.read('[Content_Types].xml'))
            main_types = [node.get('ContentType') for node in types
                          if node.get('PartName') == '/word/document.xml']
            if main_types != [WORD_CONTENT_TYPE]:
                raise DocxError('This is not a macro-free Word document (.docx).')
    except DocxError:
        raise
    except (BadZipFile, RuntimeError, ValueError, KeyError, OSError, ElementTree.ParseError):
        raise DocxError('This DOCX is invalid or damaged and could not be read.') from None


def extract_docx(contents):
    check_package(contents)
    try:
        document = Document(BytesIO(contents))
        locations = []
        text_bytes = 0

        def walk(container, prefix='docx', label='', depth=0):
            nonlocal text_bytes
            if depth > 10:
                raise DocxError('This DOCX contains tables nested too deeply to process safely.')
            paragraph_number = table_number = 0
            for block in container.iter_inner_content():
                if isinstance(block, Paragraph):
                    paragraph_number += 1
                    text = block.text
                    text_bytes += len(text.encode('utf-8'))
                    if text_bytes > MAX_TEXT_BYTES or len(locations) >= MAX_LOCATIONS:
                        raise DocxError('This DOCX exceeds the 2 MB extracted-text or 10000-location processing limit. Nothing was truncated; please use a smaller document.')
                    locations.append({'location_id': f'{prefix}-p{paragraph_number}',
                                      'location_label': f'{label}Paragraph {paragraph_number}',
                                      'text': text})
                else:
                    table_number += 1
                    table_id = f'{prefix}-t{table_number}'
                    table_label = f'{label}Table {table_number}, '
                    seen_cells = set()
                    for row_number, row in enumerate(block.rows, 1):
                        for cell_number, cell in enumerate(row.cells, row.grid_cols_before + 1):
                            # Merged cells are aliases of the same XML cell, not repeated source text.
                            if cell._tc in seen_cells:
                                continue
                            seen_cells.add(cell._tc)
                            walk(cell, f'{table_id}-r{row_number}-c{cell_number}',
                                 f'{table_label}row {row_number}, cell {cell_number}, ', depth + 1)

        walk(document)
        if not any(location['text'].strip() for location in locations):
            raise DocxError('This DOCX has no extractable body text. Images are not read; use text paragraphs or tables.')
        return locations
    except DocxError:
        raise
    except Exception:
        # Do not echo XML, package names, document text, or internal parser diagnostics.
        raise DocxError('This DOCX is invalid or damaged and could not be read.') from None


def located_results(result, locations):
    """Translate legacy detector ordinals to explicit DOCX locations at the boundary.

    The unchanged detectors use an integer field called page for each input chunk.
    Here those integers are private chunk indices only; neither the API nor AI
    receives invented DOCX pages. All result page fields are replaced immediately.
    """
    if isinstance(result, dict):
        converted = {key: located_results(value, locations) for key, value in result.items() if key != 'page'}
        if 'page' in result:
            source = locations[result['page'] - 1]
            converted.update(location_id=source['location_id'], location_label=source['location_label'])
        return converted
    if isinstance(result, list):
        return [located_results(value, locations) for value in result]
    return result
