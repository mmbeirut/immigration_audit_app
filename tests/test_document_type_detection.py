import pytest
from models.document_processor import DocumentProcessor

def test_detect_document_types_returns_diagnostics_when_none():
    processor = DocumentProcessor.__new__(DocumentProcessor)
    sample_text = "This page has no known immigration document identifiers."
    detections, diagnostics = processor.detect_document_types_on_page(sample_text, ocr_used=True)
    assert detections == []
    assert diagnostics is not None
    assert diagnostics["page_length"] == len(sample_text)
    assert diagnostics["ocr_used"] is True
    assert "indicators_checked" in diagnostics
