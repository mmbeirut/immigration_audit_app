# This will be a very large file with all the document types and field mappings
# Let me create the core structure first and then add all the specific implementations

import os
import re
import time
import uuid
import json
import logging
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional, Any

import fitz  # PyMuPDF
import easyocr
import numpy as np
from pdf2image import convert_from_path
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from ratelimit import limits, sleep_and_retry

from .validators import *


logger = logging.getLogger(__name__)


class DocumentSegment:
    def __init__(self, pages: List[int], doc_type: str, confidence: float, text: str):
        self.pages = pages
        self.doc_type = doc_type
        self.confidence = confidence
        self.text = text
        self.extracted_data = {}


class DocumentProcessor:
    def __init__(self):
        self.setup_clients()
        self.easyocr_reader = easyocr.Reader(['en'], gpu=False)

    def setup_clients(self):
        """Initialize Azure clients"""
        # Azure OpenAI
        self.llm = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )

        # Azure Form Recognizer
        self.fr_client = DocumentAnalysisClient(
            endpoint=os.getenv("FORM_RECOGNIZER_ENDPOINT"),
            credential=AzureKeyCredential(os.getenv("FORM_RECOGNIZER_KEY"))
        )

    @sleep_and_retry
    @limits(calls=20, period=60)
    def throttled_llm(self, messages):
        """Rate-limited LLM calls"""
        return self.llm.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=messages,
            temperature=0.1
        )

    def extract_text_multi_method(self, file_path: str) -> Dict[str, Any]:
        """Extract text using Azure Form Recognizer with EasyOCR fallback."""
        import time
        print("=== EXTRACT_TEXT_MULTI_METHOD DEBUG ===")
        print(f"Timestamp: {time.time()}")
        print(f"File path: {file_path}")
        print(f"File exists: {os.path.exists(file_path)}")
        if os.path.exists(file_path):
            print(f"File size: {os.path.getsize(file_path)}")
        print(f"Current working directory: {os.getcwd()}")
        print("=" * 50)

        file_path = os.path.abspath(file_path)

        all_results: Dict[str, str] = {}
        method_used = "azure"
        confidence = 0.0

        # Attempt Azure extraction
        try:
            text = self.extract_text_azure(file_path)
            all_results["azure"] = text
            print(f"DEBUG: Azure extracted {len(text)} characters")
        except Exception as e:
            print(f"DEBUG: Azure extraction failed: {e}")
            text = ""

        # Fallback to EasyOCR if Azure result is empty
        if not text.strip():
            method_used = "easyocr"
            text = self.extract_text_easyocr(file_path)
            all_results["easyocr"] = text
            confidence = 0.6 if len(text) > 100 else 0.2
        else:
            confidence = 0.8 if len(text) > 100 else 0.3

        return {
            "text": text,
            "method_used": method_used,
            "confidence": confidence,
            "all_results": all_results,
        }

    def extract_text_easyocr(self, file_path: str) -> str:
        """Extract text from each page using EasyOCR."""
        text = ""
        images = convert_from_path(file_path)
        for image in images:
            result = self.easyocr_reader.readtext(np.array(image))
            page_text = "\n".join([item[1] for item in result])
            text += page_text + "\n"
        return text.strip()

    def extract_text_azure(self, file_path: str) -> str:
        """Extract text using Azure Form Recognizer"""
        with open(file_path, "rb") as fd:
            poller = self.fr_client.begin_analyze_document("prebuilt-layout", fd)
            result = poller.result()

        text = ""
        for page in result.pages:
            for line in page.lines:
                text += line.content + "\n"
        return text.strip()

    def extract_text_pymupdf(self, file_path: str) -> str:
        """Extract text using PyMuPDF as fallback"""
        text = ""
        with fitz.open(file_path) as pdf:
            for page in pdf:
                text += page.get_text() + "\n"
        return text.strip()

    def get_page_text(self, page, page_num: int, min_length: int = 20) -> str:
        """Get text from a page using PyMuPDF with EasyOCR fallback."""
        text = page.get_text()
        if len(text.strip()) < min_length:
            pix = page.get_pixmap()
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n > 3:
                img = img[:, :, :3]
            ocr_result = self.easyocr_reader.readtext(img)
            text = "\n".join([item[1] for item in ocr_result])
            print(f"DEBUG: Page {page_num + 1} text extracted using EasyOCR")
        else:
            print(f"DEBUG: Page {page_num + 1} text extracted using PyMuPDF")
        return text

    def analyze_pdf_by_pages(self, file_path: str) -> Tuple[List[DocumentSegment], List[Dict]]:
        """Break PDF into logical document segments (returns segments + per-page diagnostics)."""
        segments: List[DocumentSegment] = []

        with fitz.open(file_path) as pdf:
            page_analyses: List[Dict] = []

            # First pass: analyze each page
            for page_num in range(len(pdf)):
                page = pdf[page_num]
                page_text = self.get_page_text(page, page_num)

                detected_types, diagnostics = self.detect_document_types_on_page(page_text)

                if not detected_types:
                    logger.debug(
                        "No document types detected on page %s: %s",
                        page_num,
                        diagnostics,
                    )

                page_analyses.append({
                    'page_num': page_num,
                    'text': page_text,
                    'detected_types': detected_types,
                    'diagnostics': diagnostics,
                    'is_continuation': self.is_continuation_page(page_text)
                })

            # Second pass: group pages into document segments
            segments = self.group_pages_into_documents(page_analyses)

        page_diagnostics = [
            {
                'page_num': analysis['page_num'],
                'detected_types': analysis['detected_types'],
                'diagnostics': analysis['diagnostics'],
            }
            for analysis in page_analyses
        ]

        return segments, page_diagnostics

    def detect_document_types_on_page(
        self, page_text: str, ocr_used: bool = False
    ) -> Tuple[List[Tuple[str, float]], Dict[str, Any]]:
        """Detect multiple document types on a single page - ENHANCED VERSION"""
        text_lower = page_text.lower()
        text_upper = page_text.upper()
        detections: List[Tuple[str, float]] = []
        indicators: Dict[str, Any] = {}

        print("DEBUG: Analyzing page text for document type detection...")
        print(f"DEBUG: First 200 chars: {page_text[:200]}")

        # I-797 Notice of Action - Enhanced detection (includes I-140 approvals)
        i797_indicators = [
            'notice of action' in text_lower,
            'i-797' in text_lower,
            '1-797' in text_lower,
            'I-797' in page_text,
            '1-797' in page_text,
            'uscis' in text_lower,
            'department of homeland security' in text_lower,
            'u.s. citizenship and immigration services' in text_lower,
            bool(re.search(r'receipt number.*[A-Z]{3}\d{10}', page_text, re.IGNORECASE)),
            ('approval notice' in text_lower and any(case in text_lower for case in ['i-140', 'i-129']))
        ]
        indicators['I797'] = i797_indicators
        if any(i797_indicators):
            confidence = 0.9
            if re.search(r'receipt number.*[A-Z]{3}\d{10}', page_text, re.IGNORECASE):
                confidence = 0.95
            detections.append(('I797', confidence))
            print(f"DEBUG: Detected I-797 with confidence {confidence}")

        # I-797C (Receipt Notice) - includes I-140 receipt notices
        i797c_indicators = [
            ('i-797c' in text_lower or '1-797c' in text_lower),
            ('notice of action' in text_lower and 'receipt' in text_lower),
            ('receipt notice' in text_lower),
            (
                'receipt number' in text_lower
                and any(case in text_lower for case in ['i-140', 'i-129'])
                and 'approval' not in text_lower
            ),
        ]
        indicators['I797C'] = i797c_indicators
        if any(i797c_indicators):
            confidence = 0.85
            if re.search(r'receipt number.*[A-Z]{3}\d{10}', page_text, re.IGNORECASE):
                confidence = 0.9
            detections.append(('I797C', confidence))
            print(f"DEBUG: Detected I-797C with confidence {confidence}")

        # I-129 Petition (standalone petitions, not notices)
        i129_indicators = [
            'i-129' in text_lower,
            'petition for a nonimmigrant worker' in text_lower,
            'notice of action' not in text_lower,
        ]
        indicators['I129'] = i129_indicators
        if all(i129_indicators):
            detections.append(('I129', 0.85))
            print("DEBUG: Detected I-129")

        # Labor Certification (PERM) - 9089
        perm_indicators = [
            phrase in text_lower for phrase in ['labor certification', 'form 9089', 'perm']
        ]
        indicators['PERM'] = perm_indicators
        if any(perm_indicators):
            detections.append(('PERM', 0.9))
            print("DEBUG: Detected PERM")

        # Prevailing Wage Determination - 9141
        pwd_indicators = [
            phrase in text_lower for phrase in ['prevailing wage', 'form 9141', 'pwd']
        ]
        indicators['PWD'] = pwd_indicators
        if any(pwd_indicators):
            detections.append(('PWD', 0.85))
            print("DEBUG: Detected PWD")

        # LCA Form 9035
        lca_phrases = [
            phrase in text_lower
            for phrase in ['eta-9035', 'eta 9035', 'labor condition application', 'lca', 'form 9035']
        ]
        lca_dol = 'department of labor' in text_lower
        indicators['LCA'] = lca_phrases + [lca_dol]
        if any(lca_phrases):
            confidence = 0.9
            if lca_dol:
                confidence = 0.95
            detections.append(('LCA', confidence))
            print(f"DEBUG: Detected LCA with confidence {confidence}")

        # I-94
        i94_indicators = [
            bool(re.search(r'i[-\s]?94', text_lower)),
            any(phrase in text_lower for phrase in ['arrival departure', 'admission number']),
        ]
        indicators['I94'] = i94_indicators
        if any(i94_indicators):
            detections.append(('I94', 0.8))
            print("DEBUG: Detected I-94")

        # EAD (Employment Authorization Document)
        ead_phrase = any(
            phrase in text_lower for phrase in ['employment authorization', 'ead', 'work permit', 'i-766']
        )
        ead_number = bool(re.search(r'uscis number.*[A-Z0-9]{9,}', page_text, re.IGNORECASE))
        indicators['EAD'] = [ead_phrase, ead_number]
        if ead_phrase:
            confidence = 0.85
            if ead_number:
                confidence = 0.9
            detections.append(('EAD', confidence))
            print(f"DEBUG: Detected EAD with confidence {confidence}")

        # Green Card (Permanent Resident Card)
        gc_phrase = any(
            phrase in text_lower for phrase in ['permanent resident card', 'green card', 'i-551']
        )
        gc_number = bool(re.search(r'uscis.*[A-Z0-9]{9,}', page_text, re.IGNORECASE))
        indicators['GREEN_CARD'] = [gc_phrase, gc_number]
        if gc_phrase:
            confidence = 0.9
            if gc_number:
                confidence = 0.95
            detections.append(('GREEN_CARD', confidence))
            print(f"DEBUG: Detected Green Card with confidence {confidence}")

        # Passport
        us_passport = bool(re.search(r'passport.*united states|type.*p\b', page_text, re.IGNORECASE))
        foreign_passport = 'passport' in text_lower
        indicators['US_PASSPORT'] = [us_passport]
        indicators['FOREIGN_PASSPORT'] = [foreign_passport]
        if us_passport:
            detections.append(('US_PASSPORT', 0.8))
            print("DEBUG: Detected US Passport")
        elif foreign_passport:
            detections.append(('FOREIGN_PASSPORT', 0.7))
            print("DEBUG: Detected Foreign Passport")

        # Visa stamp
        visa_indicators = [
            any(phrase in text_lower for phrase in ['visa', 'embassy', 'consulate']),
            any(phrase in text_lower for phrase in ['immigrant', 'nonimmigrant']),
        ]
        indicators['VISA_STAMP'] = visa_indicators
        if all(visa_indicators):
            detections.append(('VISA_STAMP', 0.8))
            print("DEBUG: Detected Visa Stamp")

        print(f"DEBUG: Final detections: {detections}")
        diagnostics = {
            'page_length': len(page_text),
            'ocr_used': ocr_used,
            'indicators_checked': indicators,
        }
        return sorted(detections, key=lambda x: x[1], reverse=True), diagnostics

    def is_continuation_page(self, page_text: str) -> bool:
        """Determine if page is continuation of previous document"""
        text_lower = page_text.lower()

        continuation_indicators = [
            r'page \d+', r'page \d+ of \d+', 'continued', r'\(continued\)',
            'attachment', 'exhibit'
        ]

        for indicator in continuation_indicators:
            if re.search(indicator, text_lower):
                return True

        # Short pages likely continuations
        if len(page_text.strip()) < 200:
            return True

        # Pages without headers likely continuations
        header_indicators = ['form', 'department', 'certificate', 'notice']
        if not any(indicator in text_lower for indicator in header_indicators):
            return True

        return False

    def group_pages_into_documents(self, page_analyses: List[Dict]) -> List[DocumentSegment]:
        """Group pages into logical document segments"""
        segments = []
        current_segment_pages = []
        current_doc_type = None
        current_confidence = 0

        for page_analysis in page_analyses:
            page_num = page_analysis['page_num']
            detected_types = page_analysis['detected_types']
            is_continuation = page_analysis['is_continuation']

            if not detected_types and not is_continuation:
                # Finish current segment
                if current_segment_pages:
                    segments.append(self.create_segment(
                        current_segment_pages, current_doc_type,
                        current_confidence, page_analyses
                    ))
                    current_segment_pages = []

                # Single page unknown segment
                segments.append(self.create_segment(
                    [page_num], 'UNKNOWN', 0.3, page_analyses
                ))

            elif detected_types and not is_continuation:
                # New document starts
                if current_segment_pages:
                    segments.append(self.create_segment(
                        current_segment_pages, current_doc_type,
                        current_confidence, page_analyses
                    ))

                # Start new segment
                current_segment_pages = [page_num]
                current_doc_type = detected_types[0][0]
                current_confidence = detected_types[0][1]

            else:
                # Continuation page
                current_segment_pages.append(page_num)

        # Final segment
        if current_segment_pages:
            segments.append(self.create_segment(
                current_segment_pages, current_doc_type,
                current_confidence, page_analyses
            ))

        return segments

    def create_segment(self, page_numbers: List[int], doc_type: str,
                       confidence: float, page_analyses: List[Dict]) -> DocumentSegment:
        """Create DocumentSegment from page numbers"""
        combined_text = ""
        for page_num in page_numbers:
            combined_text += page_analyses[page_num]['text'] + "\n\n"

        return DocumentSegment(page_numbers, doc_type, confidence, combined_text.strip())

    def process_multi_document_file(self, file_path: str, options: Dict = None) -> Dict:
        """Process file that may contain multiple document types"""
        if options is None:
            options = {}

        results = {
            'processing_id': str(uuid.uuid4()),
            'file_path': os.path.basename(file_path),
            'processed_at': datetime.utcnow().isoformat(),
            'segments_found': 0,
            'documents_processed': [],
            'person_records': {},
            'validation_errors': [],
            'processing_summary': {}
        }

        try:
            # Segment the file
            segments, page_diagnostics = self.analyze_pdf_by_pages(file_path)
            results['segments_found'] = len(segments)
            if options.get('include_page_diagnostics'):
                results['page_diagnostics'] = page_diagnostics

            # Process each segment
            for segment in segments:
                segment_result = self.process_document_segment(segment, options)
                results['documents_processed'].append(segment_result)

                # Cross-reference person data
                self.consolidate_person_data(segment_result, results['person_records'])

            # Generate audit summary
            results['processing_summary'] = self.generate_audit_summary(results)

        except Exception as e:
            results['validation_errors'].append(f"Processing error: {str(e)}")
            results['processing_summary'] = {
                'file_overview': {
                    'total_pages': 0,
                    'document_types_found': {},
                    'people_identified': 0,
                    'date_range': {'earliest': None, 'latest': None},
                },
                'completeness_check': {},
                'red_flags': [],
                'recommendations': []
            }

        return results

    def process_document_segment(self, segment: DocumentSegment, options: Dict) -> Dict:
        """Process single document segment"""
        segment_result = {
            'pages': segment.pages,
            'document_type': segment.doc_type,
            'confidence': segment.confidence,
            'extracted_data': {},
            'validation_results': {},
            'processing_notes': []
        }

        print(f"DEBUG: Processing segment - Type: {segment.doc_type}, Confidence: {segment.confidence}")

        # Extract data based on document type
        try:
            if segment.doc_type in ['I797', 'I797C']:
                print("DEBUG: Extracting USCIS I-797 form data...")
                segment_result['extracted_data'] = self.extract_uscis_form_data(segment.text)
            elif segment.doc_type == 'I129':
                print("DEBUG: Extracting I-129 form data...")
                segment_result['extracted_data'] = self.extract_i129_data(segment.text)
            elif segment.doc_type in ['PERM', 'PWD']:
                print("DEBUG: Extracting DOL form data...")
                segment_result['extracted_data'] = self.extract_dol_form_data(segment.text)
            elif segment.doc_type == 'LCA':
                print("DEBUG: Extracting LCA form data...")
                segment_result['extracted_data'] = self.extract_lca_data(segment.text)
            elif segment.doc_type == 'I94':
                print("DEBUG: Extracting I-94 data...")
                segment_result['extracted_data'] = self.extract_i94_data(segment.text)
            elif segment.doc_type == 'EAD':
                print("DEBUG: Extracting EAD data...")
                segment_result['extracted_data'] = self.extract_ead_data(segment.text)
            elif segment.doc_type == 'GREEN_CARD':
                print("DEBUG: Extracting Green Card data...")
                segment_result['extracted_data'] = self.extract_green_card_data(segment.text)
            elif segment.doc_type in ['US_PASSPORT', 'FOREIGN_PASSPORT']:
                print("DEBUG: Extracting passport data...")
                segment_result['extracted_data'] = self.extract_passport_data(segment.text)
            elif segment.doc_type == 'VISA_STAMP':
                print("DEBUG: Extracting visa data...")
                segment_result['extracted_data'] = self.extract_visa_data(segment.text)
            else:
                print(f"DEBUG: Unknown document type: {segment.doc_type}, using generic extraction")
                segment_result['extracted_data'] = self.extract_generic_data(segment.text)
                segment_result['processing_notes'].append(
                    "Unknown document type - used generic extraction"
                )

            print(f"DEBUG: Extraction result: {segment_result['extracted_data']}")

        except Exception as e:
            print(f"DEBUG: Extraction error: {str(e)}")
            segment_result['processing_notes'].append(f"Extraction error: {str(e)}")

        # Validate data if requested
        if options.get('validate_fields', True):
            segment_result['validation_results'] = validate_segment_data(
                segment_result['extracted_data'], segment.doc_type
            )

        return segment_result

    # Document-specific extraction methods
    def extract_uscis_form_data(self, text: str) -> Dict:
        """Extract USCIS form data (I-797, I-797C) using LLM"""
        print("DEBUG: Getting USCIS prompt...")
        # Determine if it's I-797 or I-797C based on content
        if 'receipt notice' in text.lower() or 'i-797c' in text.lower():
            prompt = get_document_specific_prompt('I797C')
        else:
            prompt = get_document_specific_prompt('I797')
        print("DEBUG: Calling LLM for USCIS extraction...")
        result = self.extract_with_llm(text, prompt)
        print(f"DEBUG: LLM extraction result: {result}")
        return result

    def extract_i129_data(self, text: str) -> Dict:
        """Extract I-129 form data"""
        prompt = get_document_specific_prompt('I129')
        return self.extract_with_llm(text, prompt)

    def extract_dol_form_data(self, text: str) -> Dict:
        """Extract DOL form data (PERM/PWD)"""
        if 'perm' in text.lower() or '9089' in text:
            prompt = get_document_specific_prompt('PERM')
        else:
            prompt = get_document_specific_prompt('PWD')
        return self.extract_with_llm(text, prompt)

    def extract_lca_data(self, text: str) -> Dict:
        """Extract LCA form data"""
        prompt = get_document_specific_prompt('LCA')
        return self.extract_with_llm(text, prompt)

    def extract_i94_data(self, text: str) -> Dict:
        """Extract I-94 data"""
        prompt = get_document_specific_prompt('I94')
        return self.extract_with_llm(text, prompt)

    def extract_ead_data(self, text: str) -> Dict:
        """Extract EAD data"""
        prompt = get_document_specific_prompt('EAD')
        return self.extract_with_llm(text, prompt)

    def extract_green_card_data(self, text: str) -> Dict:
        """Extract Green Card data"""
        prompt = get_document_specific_prompt('GREEN_CARD')
        return self.extract_with_llm(text, prompt)

    def extract_passport_data(self, text: str) -> Dict:
        """Extract passport data"""
        if 'united states' in text.lower() or 'usa' in text.lower():
            prompt = get_document_specific_prompt('US_PASSPORT')
        else:
            prompt = get_document_specific_prompt('FOREIGN_PASSPORT')
        return self.extract_with_llm(text, prompt)

    def extract_visa_data(self, text: str) -> Dict:
        """Extract visa stamp data"""
        prompt = get_document_specific_prompt('VISA_STAMP')
        return self.extract_with_llm(text, prompt)

    def extract_generic_data(self, text: str) -> Dict:
        """Extract generic immigration data"""
        prompt = get_document_specific_prompt('GENERIC')
        return self.extract_with_llm(text, prompt)

    def extract_with_llm(self, text: str, prompt: str) -> Dict:
        """Extract data using LLM with structured output"""
        try:
            print(f"DEBUG: Preparing LLM call with text length: {len(text)}")
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Extract key fields from this text:\n\n{text[:4000]}"}
            ]

            print("DEBUG: Making LLM API call...")
            response = self.throttled_llm(messages)
            content = response.choices[0].message.content or ""
            print(f"DEBUG: LLM response: {content}")

            # Parse the structured output
            parsed_result = self.parse_llm_output(content)
            print(f"DEBUG: Parsed result: {parsed_result}")
            return parsed_result

        except Exception as e:
            print(f"DEBUG: LLM extraction failed: {str(e)}")
            return {"error": f"LLM extraction failed: {str(e)}"}

    def parse_llm_output(self, content: str) -> Dict:
        """Parse LLM output into structured data - FIXED VERSION"""
        print(f"DEBUG: Parsing LLM content: {content[:200]}...")

        # Clean the content - remove markdown code blocks
        content = content.strip()
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]

        content = content.strip()
        print(f"DEBUG: Cleaned content: {content[:200]}...")

        # Try to parse JSON first
        try:
            parsed = json.loads(content)
            print(f"DEBUG: Successfully parsed JSON: {parsed}")
            return parsed
        except json.JSONDecodeError as e:
            print(f"DEBUG: JSON parsing failed: {e}")
            print(f"DEBUG: Falling back to regex parsing...")

        # Fall back to field parsing
        data = {}
        lines = [line.strip() for line in content.split('\n') if line.strip()]

        for line in lines:
            # Match **Field:** value or Field: value
            match = re.match(r'^\*\*(.+?)\*\*:\s*(.+)', line)
            if not match:
                match = re.match(r'^(.+?):\s*(.+)', line)

            if match:
                key = match.group(1).strip().lower().replace(' ', '_')
                value = match.group(2).strip()
                value = value.strip('"').strip("'").rstrip(',')
                if value and value != 'null' and value != 'N/A':
                    data[key] = value

        print(f"DEBUG: Final parsed data: {data}")
        return data

    def consolidate_person_data(self, segment_result: Dict, person_records: Dict):
        """Cross-reference person data across segments"""
        extracted_data = segment_result['extracted_data']

        print(f"DEBUG: Consolidating person data from extracted_data: {extracted_data}")

        # Enhanced person name extraction for different document types
        document_type = segment_result['document_type']
        person_name = None

        # Try different field combinations based on document type
        if document_type == 'I94':
            first = (extracted_data.get('first_name') or
                     extracted_data.get('first_given_name') or
                     extracted_data.get('given_name', '')).strip()
            last = (extracted_data.get('last_name') or
                    extracted_data.get('lastsurname') or
                    extracted_data.get('surname', '')).strip()
            if first and last:
                person_name = f"{first} {last}"
            elif first:
                person_name = first
            elif last:
                person_name = last

        elif document_type in ['I797', 'I797C']:
            person_name = extracted_data.get('beneficiary')

        elif document_type == 'I129':
            given = extracted_data.get('given_name') or extracted_data.get('given_name_first_name', '')
            family = extracted_data.get('family_name') or extracted_data.get('family_name_last_name', '')
            if given and family:
                person_name = f"{given} {family}"

        elif document_type in ['EAD', 'GREEN_CARD']:
            person_name = extracted_data.get('full_name')

        elif document_type in ['US_PASSPORT', 'FOREIGN_PASSPORT']:
            person_name = extracted_data.get('holder_name')

        elif document_type == 'VISA_STAMP':
            given = extracted_data.get('given_name', '')
            surname = extracted_data.get('surname', '')
            if given and surname:
                person_name = f"{given} {surname}"

        if not person_name:
            person_name = (
                extracted_data.get('beneficiary') or
                extracted_data.get('full_name') or
                extracted_data.get('holder_name') or
                f"{extracted_data.get('first_name', '')} {extracted_data.get('last_name', '')}".strip() or
                f"{extracted_data.get('given_name', '')} {extracted_data.get('surname', '')}".strip() or
                None
            )

        dob = (extracted_data.get('date_of_birth') or
               extracted_data.get('birth_date') or
               extracted_data.get('date_of_birth_mmddyyyy'))

        print(f"DEBUG: Extracted person name: '{person_name}', DOB: '{dob}'")
        print(f"DEBUG: Document type: {document_type}")
        print(f"DEBUG: Available fields: {list(extracted_data.keys())}")

        if not person_name:
            print("DEBUG: No person name found, skipping person record creation")
            return

        person_key = f"{person_name}_{dob}" if dob else person_name

        if person_key not in person_records:
            person_records[person_key] = {
                'name': person_name,
                'date_of_birth': dob,
                'documents': [],
                'timeline': [],
                'inconsistencies': []
            }
            print(f"DEBUG: Created new person record for: {person_key}")

        person_record = person_records[person_key]

        person_record['documents'].append({
            'type': segment_result['document_type'],
            'pages': segment_result['pages'],
            'data': extracted_data
        })

        doc_date_raw = (
            extracted_data.get('notice_date') or
            extracted_data.get('issue_date') or
            extracted_data.get('received_date') or
            extracted_data.get('arrival_date') or
            extracted_data.get('arrivalissued_date') or
            extracted_data.get('expiration_date')
        )

        parsed_doc_date = parse_date_flexible(doc_date_raw)

        if parsed_doc_date:
            person_record['timeline'].append({
                'date': doc_date_raw,
                'parsed_date': parsed_doc_date,
                'document': segment_result['document_type'],
                'event': f"{segment_result['document_type']} processed"
            })

            person_record['timeline'].sort(
                key=lambda x: x.get('parsed_date') or date.min
            )

        self.check_person_data_consistency(person_record)

        print(f"DEBUG: Updated person record: {person_record}")

    def check_person_data_consistency(self, person_record: Dict):
        """Check for data inconsistencies across documents"""
        inconsistencies = []
        documents = person_record['documents']

        if len(documents) < 2:
            return

        # Check name consistency
        names = []
        for doc in documents:
            name = (doc['data'].get('beneficiary') or
                    doc['data'].get('full_name') or
                    doc['data'].get('holder_name'))
            if name:
                names.append(name)

        unique_names = set(filter(None, names))
        if len(unique_names) > 1:
            inconsistencies.append(f"Name variations: {', '.join(unique_names)}")

        # Check DOB consistency
        dobs = []
        for doc in documents:
            dob = (doc['data'].get('date_of_birth') or
                   doc['data'].get('birth_date'))
            if dob:
                dobs.append(dob)

        unique_dobs = set(filter(None, dobs))
        if len(unique_dobs) > 1:
            inconsistencies.append(f"DOB variations: {', '.join(map(str, unique_dobs))}")

        # Check citizenship consistency
        countries = []
        for doc in documents:
            country = (doc['data'].get('country_of_citizenship') or
                       doc['data'].get('country_of_birth') or
                       doc['data'].get('nationality'))
            if country:
                countries.append(country)

        unique_countries = set(filter(None, countries))
        if len(unique_countries) > 1:
            inconsistencies.append(f"Country variations: {', '.join(unique_countries)}")

        person_record['inconsistencies'] = inconsistencies

    def generate_audit_summary(self, results: Dict) -> Dict:
        """Generate comprehensive audit summary"""
        summary = {
            'file_overview': {
                'total_pages': sum(len(doc['pages']) for doc in results['documents_processed']),
                'document_types_found': {},
                'people_identified': len(results['person_records']),
                'date_range': self.get_document_date_range(results),
            },
            'completeness_check': {},
            'red_flags': [],
            'recommendations': []
        }

        for doc in results['documents_processed']:
            doc_type = doc['document_type']
            summary['file_overview']['document_types_found'][doc_type] = \
                summary['file_overview']['document_types_found'].get(doc_type, 0) + 1

        for person_key, person_data in results['person_records'].items():
            completeness = check_case_completeness(person_data)
            summary['completeness_check'][person_key] = completeness

            if person_data['inconsistencies']:
                summary['red_flags'].extend([
                    f"{person_key}: {inconsistency}"
                    for inconsistency in person_data['inconsistencies']
                ])

        summary['recommendations'] = self.generate_audit_recommendations(summary, results)

        return summary

    def get_document_date_range(self, results: Dict) -> Dict:
        """Get date range of all documents"""
        all_dates: List[date] = []

        for person_data in results['person_records'].values():
            for timeline_entry in person_data['timeline']:
                parsed = timeline_entry.get('parsed_date')
                if not parsed:
                    parsed = parse_date_flexible(timeline_entry.get('date'))
                if parsed:
                    all_dates.append(parsed)

        if not all_dates:
            return {'earliest': None, 'latest': None}

        all_dates.sort()
        return {
            'earliest': all_dates[0].isoformat(),
            'latest': all_dates[-1].isoformat()
        }

    def generate_audit_recommendations(self, summary: Dict, results: Dict) -> List[str]:
        """Generate audit recommendations"""
        recommendations = []

        for person_key, completeness in summary['completeness_check'].items():
            if completeness.get('missing_documents'):
                recommendations.append(
                    f"{person_key}: Consider obtaining {', '.join(completeness['missing_documents'])}"
                )

        if summary['red_flags']:
            recommendations.append("Review flagged data inconsistencies before proceeding")

        return recommendations

    def process_single_document(self, file_path: str, document_type: str, options: Dict) -> Dict:
        """Process file as single document type"""
        results = {
            'processing_id': str(uuid.uuid4()),
            'file_path': os.path.basename(file_path),
            'processed_at': datetime.utcnow().isoformat(),
            'document_type': document_type,
            'extracted_data': {},
            'validation_results': {},
            'processing_notes': [],
            'segments_found': 1,
            'documents_processed': [],
            'person_records': {},
            'validation_errors': []
        }

        print(f"DEBUG: Processing single document, type: {document_type}")

        try:
            extraction_result = self.extract_text_multi_method(file_path)
            text = extraction_result['text']
            print(f"DEBUG: Extracted text length: {len(text)}")

            if document_type == 'auto':
                print("DEBUG: Auto-detecting document type...")
                segments, _ = self.analyze_pdf_by_pages(file_path)
                if segments:
                    document_type = segments[0].doc_type
                    text = segments[0].text
                    results['document_type'] = document_type
                    print(f"DEBUG: Auto-detected document type: {document_type}")

            print(f"DEBUG: Processing document as type: {document_type}")
            if document_type in ['I797', 'I797C']:
                results['extracted_data'] = self.extract_uscis_form_data(text)
            elif document_type == 'I129':
                results['extracted_data'] = self.extract_i129_data(text)
            elif document_type in ['PERM', 'PWD']:
                results['extracted_data'] = self.extract_dol_form_data(text)
            elif document_type == 'LCA':
                results['extracted_data'] = self.extract_lca_data(text)
            elif document_type == 'I94':
                results['extracted_data'] = self.extract_i94_data(text)
            elif document_type == 'EAD':
                results['extracted_data'] = self.extract_ead_data(text)
            elif document_type == 'GREEN_CARD':
                results['extracted_data'] = self.extract_green_card_data(text)
            elif document_type in ['US_PASSPORT', 'FOREIGN_PASSPORT']:
                results['extracted_data'] = self.extract_passport_data(text)
            elif document_type == 'VISA_STAMP':
                results['extracted_data'] = self.extract_visa_data(text)
            else:
                results['extracted_data'] = self.extract_generic_data(text)

            print(f"DEBUG: Final extracted data: {results['extracted_data']}")

            if options.get('validate_fields', True):
                results['validation_results'] = validate_segment_data(
                    results['extracted_data'], document_type
                )

            results['documents_processed'] = [{
                'pages': [0],
                'document_type': document_type,
                'confidence': 0.8,
                'extracted_data': results['extracted_data'],
                'validation_results': results['validation_results'],
                'processing_notes': results['processing_notes']
            }]

            extracted_data = results['extracted_data']

            person_name = None
            if document_type == 'I94':
                first = (extracted_data.get('first_name') or
                         extracted_data.get('first_given_name') or
                         extracted_data.get('given_name', '')).strip()
                last = (extracted_data.get('last_name') or
                        extracted_data.get('lastsurname') or
                        extracted_data.get('surname', '')).strip()
                if first and last:
                    person_name = f"{first} {last}"
                elif first:
                    person_name = first
                elif last:
                    person_name = last

            elif document_type in ['I797', 'I797C']:
                person_name = extracted_data.get('beneficiary')

            elif document_type == 'I129':
                given = extracted_data.get('given_name') or extracted_data.get('given_name_first_name', '')
                family = extracted_data.get('family_name') or extracted_data.get('family_name_last_name', '')
                if given and family:
                    person_name = f"{given} {family}"

            elif document_type in ['EAD', 'GREEN_CARD']:
                person_name = extracted_data.get('full_name')

            elif document_type in ['US_PASSPORT', 'FOREIGN_PASSPORT']:
                person_name = extracted_data.get('holder_name')

            elif document_type == 'VISA_STAMP':
                given = extracted_data.get('given_name', '')
                surname = extracted_data.get('surname', '')
                if given and surname:
                    person_name = f"{given} {surname}"

            if not person_name:
                person_name = (
                    extracted_data.get('beneficiary') or
                    extracted_data.get('full_name') or
                    extracted_data.get('holder_name') or
                    f"{extracted_data.get('first_name', '')} {extracted_data.get('last_name', '')}".strip() or
                    f"{extracted_data.get('given_name', '')} {extracted_data.get('surname', '')}".strip() or
                    None
                )

            print("DEBUG: Person name components:")
            print(f"  beneficiary: {extracted_data.get('beneficiary')}")
            print(f"  full_name: {extracted_data.get('full_name')}")
            print(f"  first_name: {extracted_data.get('first_name')}")
            print(f"  last_name: {extracted_data.get('last_name')}")
            print(f"  given_name: {extracted_data.get('given_name')}")
            print(f"  surname: {extracted_data.get('surname')}")
            print(f"  final person_name: '{person_name}'")

            if person_name:
                dob = (extracted_data.get('date_of_birth') or
                       extracted_data.get('birth_date') or
                       extracted_data.get('date_of_birth_mmddyyyy'))

                person_key = f"{person_name}_{dob}" if dob else person_name
                results['person_records'][person_key] = {
                    'name': person_name,
                    'date_of_birth': dob,
                    'documents': [{
                        'type': document_type,
                        'pages': [0],
                        'data': extracted_data
                    }],
                    'timeline': [],
                    'inconsistencies': []
                }

                doc_date_raw = (
                    extracted_data.get('notice_date') or
                    extracted_data.get('issue_date') or
                    extracted_data.get('received_date') or
                    extracted_data.get('arrival_date') or
                    extracted_data.get('expiration_date')
                )
                parsed_doc_date = parse_date_flexible(doc_date_raw)
                if parsed_doc_date:
                    results['person_records'][person_key]['timeline'].append({
                        'date': doc_date_raw,
                        'parsed_date': parsed_doc_date,
                        'document': document_type,
                        'event': f"{document_type} processed"
                    })

                print(f"DEBUG: Created person record: {results['person_records'][person_key]}")

            results['processing_summary'] = {
                'file_overview': {
                    'total_pages': 1,
                    'document_types_found': {document_type: 1},
                    'people_identified': len(results['person_records']),
                    'date_range': self.get_document_date_range(results)
                },
                'completeness_check': {},
                'red_flags': [],
                'recommendations': []
            }

            for person_key, person_data in results['person_records'].items():
                completeness = check_case_completeness(person_data)
                results['processing_summary']['completeness_check'][person_key] = completeness

            results['processing_summary']['recommendations'] = self.generate_audit_recommendations(
                results['processing_summary'], results
            )

            print(
                f"DEBUG: Final results summary - People: {len(results['person_records'])}, Documents: {len(results['documents_processed'])}")

        except Exception as e:
            print(f"DEBUG: Processing error: {str(e)}")
            results['processing_notes'].append(f"Processing error: {str(e)}")
            results['validation_errors'].append(f"Processing error: {str(e)}")

        return results
