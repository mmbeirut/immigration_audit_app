import os
import sys
import types
import pytest

# Stub external dependencies to keep tests lightweight
sys.modules['fitz'] = types.ModuleType('fitz')

# EasyOCR stub
_easyocr = types.ModuleType('easyocr')
class _DummyReader:
    def __init__(self, *args, **kwargs):
        pass
    def readtext(self, *args, **kwargs):
        return []
_easyocr.Reader = _DummyReader
sys.modules['easyocr'] = _easyocr

# numpy stub
_numpy = types.ModuleType('numpy')
_numpy.array = lambda x: x
sys.modules['numpy'] = _numpy

# pdf2image stub
_pdf2image = types.ModuleType('pdf2image')
_pdf2image.convert_from_path = lambda *args, **kwargs: []
sys.modules['pdf2image'] = _pdf2image

# Azure stubs
_azure = types.ModuleType('azure')
_ai = types.ModuleType('ai')
_fr = types.ModuleType('formrecognizer')
class _DummyClient:
    pass
_fr.DocumentAnalysisClient = _DummyClient
_ai.formrecognizer = _fr
_azure.ai = _ai
_core = types.ModuleType('core')
_cred = types.ModuleType('credentials')
class _DummyCred:
    def __init__(self, *args, **kwargs):
        pass
_cred.AzureKeyCredential = _DummyCred
_core.credentials = _cred
_azure.core = _core
sys.modules['azure'] = _azure
sys.modules['azure.ai'] = _ai
sys.modules['azure.ai.formrecognizer'] = _fr
sys.modules['azure.core'] = _core
sys.modules['azure.core.credentials'] = _cred

# OpenAI stub
_openai = types.ModuleType('openai')
class _DummyOpenAI:
    class chat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):
                class _Resp:
                    choices = [types.SimpleNamespace(message=types.SimpleNamespace(content='{}'))]
                return _Resp()
_openai.AzureOpenAI = _DummyOpenAI
sys.modules['openai'] = _openai

# ratelimit stub
_ratelimit = types.ModuleType('ratelimit')
def limits(calls, period):
    def decorator(func):
        return func
    return decorator
def sleep_and_retry(func):
    return func
_ratelimit.limits = limits
_ratelimit.sleep_and_retry = sleep_and_retry
sys.modules['ratelimit'] = _ratelimit

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.document_processor import DocumentProcessor, DocumentSegment


def create_sample_pdf(tmp_path):
    """Create a tiny placeholder PDF file"""
    pdf_path = tmp_path / 'sample.pdf'
    pdf_path.write_bytes(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF')
    return pdf_path


def test_multi_document_processing(tmp_path):
    pdf_path = create_sample_pdf(tmp_path)

    dp = DocumentProcessor.__new__(DocumentProcessor)

    def fake_analyze(_):
        seg1 = DocumentSegment([1], 'I797', 0.95,
                               'NOTICE OF ACTION\nReceipt Number WAC1234567890\nBeneficiary: John Doe')
        seg2 = DocumentSegment([2], 'I94', 0.90,
                               'I-94 Arrival/Departure Record\nName: Jane Smith\nI-94 Number: 12345678901')
        return [seg1, seg2]

    def fake_process_segment(segment, options):
        if segment.doc_type == 'I797':
            data = {'receipt_number': 'WAC1234567890', 'beneficiary': 'John Doe'}
        elif segment.doc_type == 'I94':
            data = {'first_name': 'Jane', 'last_name': 'Smith'}
        else:
            data = {}
        return {
            'pages': segment.pages,
            'document_type': segment.doc_type,
            'confidence': segment.confidence,
            'extracted_data': data,
            'validation_results': {},
            'processing_notes': []
        }

    dp.analyze_pdf_by_pages = fake_analyze
    dp.process_document_segment = fake_process_segment
    dp.generate_audit_summary = lambda results: {}

    results = dp.process_multi_document_file(str(pdf_path))

    assert results['segments_found'] > 0
    doc_types = [doc['document_type'] for doc in results['documents_processed']]
    assert 'I797' in doc_types
    assert any(doc['extracted_data'].get('receipt_number') == 'WAC1234567890'
               for doc in results['documents_processed'])
    assert any(doc['extracted_data'].get('first_name') == 'Jane'
               for doc in results['documents_processed'])
