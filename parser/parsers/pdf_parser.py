import io
from typing import Iterator
from parser.record import Record, RecordType, Severity

try:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer, LAParams
    from pdfminer.pdfdocument import PDFEncryptionError
    _PDFMINER = True
except ImportError:
    _PDFMINER = False


def parse_pdf(data: bytes) -> Iterator[Record]:
    if not _PDFMINER:
        yield Record(type=RecordType.ERROR, format="pdf", reason="pdfminer.six is not installed")
        return

    fp = io.BytesIO(data)

    try:
        for page_num, page_layout in enumerate(extract_pages(fp, laparams=LAParams()), start=1):
            page_text = []
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    text = element.get_text().strip()
                    if text:
                        page_text.append(text)

            yield Record(
                type=RecordType.DATA,
                format="pdf",
                content="\n".join(page_text),
                metadata={"page": page_num},
            )

    except PDFEncryptionError:
        yield Record(
            type=RecordType.WARNING,
            format="pdf",
            reason="PDF is encrypted or password-protected; text extraction skipped",
            severity=Severity.MEDIUM,
        )
    except Exception as e:
        yield Record(type=RecordType.ERROR, format="pdf", reason=f"PDF parse error: {e}")