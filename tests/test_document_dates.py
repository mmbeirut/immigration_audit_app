import os
import sys
import types
import pytest

sys.modules['fitz'] = types.ModuleType('fitz')

easyocr_mod = types.ModuleType('easyocr')
class DummyReader:
    def __init__(self, *args, **kwargs):
        pass
    def readtext(self, *args, **kwargs):
        return []
easyocr_mod.Reader = DummyReader
sys.modules['easyocr'] = easyocr_mod

numpy_mod = types.ModuleType('numpy')
numpy_mod.array = lambda x: x
sys.modules['numpy'] = numpy_mod

pdf2image_mod = types.ModuleType('pdf2image')
pdf2image_mod.convert_from_path = lambda *args, **kwargs: []
sys.modules['pdf2image'] = pdf2image_mod

azure_mod = types.ModuleType('azure')
azure_ai = types.ModuleType('ai')
fr_mod = types.ModuleType('formrecognizer')
class DummyClient:
    pass
fr_mod.DocumentAnalysisClient = DummyClient
azure_ai.formrecognizer = fr_mod
azure_mod.ai = azure_ai
azure_core = types.ModuleType('core')
cred_mod = types.ModuleType('credentials')
class DummyCred:
    def __init__(self, *args, **kwargs):
        pass
cred_mod.AzureKeyCredential = DummyCred
azure_core.credentials = cred_mod
azure_mod.core = azure_core
sys.modules['azure'] = azure_mod
sys.modules['azure.ai'] = azure_ai
sys.modules['azure.ai.formrecognizer'] = fr_mod
sys.modules['azure.core'] = azure_core
sys.modules['azure.core.credentials'] = cred_mod

openai_mod = types.ModuleType('openai')
class DummyOpenAI:
    def __init__(self, *args, **kwargs):
        pass
    class chat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):
                return {}
openai_mod.AzureOpenAI = DummyOpenAI
sys.modules['openai'] = openai_mod

ratelimit_mod = types.ModuleType('ratelimit')
def limits(calls, period):
    def decorator(func):
        return func
    return decorator
def sleep_and_retry(func):
    return func
ratelimit_mod.limits = limits
ratelimit_mod.sleep_and_retry = sleep_and_retry
sys.modules['ratelimit'] = ratelimit_mod

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.document_processor import DocumentProcessor
from models.validators import parse_date_flexible


def test_consolidate_person_data_skips_invalid_dates_and_sorts():
    dp = DocumentProcessor.__new__(DocumentProcessor)
    person_records = {}
    segment_valid = {
        'extracted_data': {
            'beneficiary': 'John Doe',
            'notice_date': '2024-01-01',
        },
        'document_type': 'I797',
        'pages': [1],
    }
    segment_invalid = {
        'extracted_data': {
            'beneficiary': 'John Doe',
            'notice_date': 'invalid-date',
        },
        'document_type': 'I797',
        'pages': [2],
    }

    dp.consolidate_person_data(segment_valid, person_records)
    dp.consolidate_person_data(segment_invalid, person_records)

    assert 'John Doe' in person_records
    timeline = person_records['John Doe']['timeline']
    assert len(timeline) == 1
    assert timeline[0]['parsed_date'].isoformat() == '2024-01-01'


def test_get_document_date_range_handles_mixed_dates():
    dp = DocumentProcessor.__new__(DocumentProcessor)
    results = {
        'person_records': {
            'p1': {
                'timeline': [
                    {
                        'date': '2024-01-01',
                        'parsed_date': parse_date_flexible('2024-01-01'),
                        'document': 'A',
                        'event': 'A',
                    },
                    {'date': 'invalid', 'document': 'B', 'event': 'B'},
                    {'date': None, 'document': 'C', 'event': 'C'},
                ]
            },
            'p2': {
                'timeline': [
                    {'date': '03/15/2023', 'document': 'D', 'event': 'D'},
                    {'date': '19DEC1994', 'document': 'E', 'event': 'E'},
                    {'date': None, 'document': 'F', 'event': 'F'},
                ]
            }
        }
    }

    date_range = dp.get_document_date_range(results)
    assert date_range['earliest'] == '1994-12-19'
    assert date_range['latest'] == '2024-01-01'
