import os
import sys
import types
import re
import pytest

# Stub modules required by DocumentProcessor
sys.modules['fitz'] = types.ModuleType('fitz')

_easyocr = types.ModuleType('easyocr')
class _DummyReader:
    def __init__(self, *args, **kwargs):
        pass
    def readtext(self, *args, **kwargs):
        return []
_easyocr.Reader = _DummyReader
sys.modules['easyocr'] = _easyocr

_numpy = types.ModuleType('numpy')
_numpy.array = lambda x: x
sys.modules['numpy'] = _numpy

_pdf2image = types.ModuleType('pdf2image')
_pdf2image.convert_from_path = lambda *args, **kwargs: []
sys.modules['pdf2image'] = _pdf2image

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

_openai = types.ModuleType('openai')
class _DummyOpenAI:
    def __init__(self, *args, **kwargs):
        pass
    class chat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):
                msg = types.SimpleNamespace(content="{}")
                choice = types.SimpleNamespace(message=msg)
                return types.SimpleNamespace(choices=[choice])
_openai.AzureOpenAI = _DummyOpenAI
sys.modules['openai'] = _openai

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


@pytest.fixture
def sample_pdf(tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.1\n%EOF")
    return path


def test_process_multi_document_file(sample_pdf):
    dp = DocumentProcessor.__new__(DocumentProcessor)

    def fake_analyze(self, file_path):
        text1 = (
            "I-797 Notice of Action\n"
            "Receipt Number ABC1234567890\n"
            "Beneficiary: John Doe"
        )
        text2 = (
            "I-94 Arrival/Departure Record\n"
            "Name: John Doe"
        )
        return [
            DocumentSegment(pages=[0], doc_type="I797", confidence=0.95, text=text1),
            DocumentSegment(pages=[1], doc_type="I94", confidence=0.90, text=text2),
        ]
    dp.analyze_pdf_by_pages = fake_analyze.__get__(dp, DocumentProcessor)

    def fake_extract_with_llm(self, text, prompt):
        data = {}
        m = re.search(r"Receipt Number\s+([A-Z0-9]+)", text)
        if m:
            data["receipt_number"] = m.group(1)
        m = re.search(r"Beneficiary:\s*(.+)", text)
        if m:
            data["beneficiary"] = m.group(1).strip()
        m = re.search(r"Name:\s*(.+)", text)
        if m and "beneficiary" not in data:
            data["name"] = m.group(1).strip()
        return data
    dp.extract_with_llm = fake_extract_with_llm.__get__(dp, DocumentProcessor)

    results = dp.process_multi_document_file(str(sample_pdf))

    assert results["segments_found"] > 0
    assert any(seg["document_type"] for seg in results["documents_processed"])

    i797 = next(seg for seg in results["documents_processed"] if seg["document_type"] == "I797")
    assert i797["extracted_data"]["receipt_number"] == "ABC1234567890"
    assert i797["extracted_data"]["beneficiary"] == "John Doe"

    i94 = next(seg for seg in results["documents_processed"] if seg["document_type"] == "I94")
    assert i94["extracted_data"]["name"] == "John Doe"
