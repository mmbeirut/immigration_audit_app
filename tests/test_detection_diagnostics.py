import os
import sys
import types
import pytest

# Stub heavy external dependencies before importing DocumentProcessor
sys.modules['fitz'] = types.ModuleType('fitz')

_easyocr = types.ModuleType('easyocr')
class DummyReader:
    def __init__(self, *args, **kwargs):
        pass
    def readtext(self, *args, **kwargs):
        return []
_easyocr.Reader = DummyReader
sys.modules['easyocr'] = _easyocr

_numpy = types.ModuleType('numpy')
_numpy.array = lambda x: x
sys.modules['numpy'] = _numpy

_pdf2image = types.ModuleType('pdf2image')
_pdf2image.convert_from_path = lambda *args, **kwargs: []
sys.modules['pdf2image'] = _pdf2image

_azure = types.ModuleType('azure')
_azure_ai = types.ModuleType('ai')
_fr_mod = types.ModuleType('formrecognizer')
class DummyClient:
    pass
_fr_mod.DocumentAnalysisClient = DummyClient
_azure_ai.formrecognizer = _fr_mod
_azure.core = types.ModuleType('core')
_credentials = types.ModuleType('credentials')
class DummyCred:
    def __init__(self, *args, **kwargs):
        pass
_credentials.AzureKeyCredential = DummyCred
_azure.core.credentials = _credentials
sys.modules['azure'] = _azure
sys.modules['azure.ai'] = _azure_ai
sys.modules['azure.ai.formrecognizer'] = _fr_mod
sys.modules['azure.core'] = _azure.core
sys.modules['azure.core.credentials'] = _credentials

_openai = types.ModuleType('openai')
class DummyOpenAI:
    def __init__(self, *args, **kwargs):
        pass
    class chat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):
                return {}
_openai.AzureOpenAI = DummyOpenAI
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

from models.document_processor import DocumentProcessor


def test_returns_diagnostics_when_no_detection():
    dp = DocumentProcessor.__new__(DocumentProcessor)
    text = "no meaningful content here"
    detections, diagnostics = dp.detect_document_types_on_page(text)
    assert detections == []
    assert diagnostics['page_length'] == len(text)
    assert diagnostics['ocr_used'] is False
    assert 'indicators_checked' in diagnostics
