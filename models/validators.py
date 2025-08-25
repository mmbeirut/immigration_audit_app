import re
import logging
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from logging.handlers import RotatingFileHandler


def setup_logging(app):
    """Setup comprehensive logging"""
    if not app.debug:
        file_handler = RotatingFileHandler('logs/app.log', maxBytes=10485760, backupCount=5)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Immigration Audit App startup')


def validate_receipt_number(receipt_number: str) -> bool:
    """Validate USCIS receipt numbers"""
    if not receipt_number:
        return False
    pattern = r'^(MSC|NBC|EAC|WAC|IOE)\d{10}$'
    return bool(re.match(pattern, receipt_number, re.IGNORECASE))


def validate_i94_number(i94_number: str) -> bool:
    """Validate I-94 admission numbers"""
    if not i94_number:
        return False
    cleaned = i94_number.replace('-', '').replace(' ', '')
    return bool(re.match(r'^\d{11}$', cleaned))


def validate_passport_number(passport_num: str, country: str = None) -> bool:
    """Validate passport numbers"""
    if not passport_num:
        return False

    if country and country.upper() == 'USA':
        # US passports: 9 digits or 1 letter + 8 digits
        return bool(re.match(r'^[A-Z]?\d{8,9}$', passport_num.upper()))

    # General validation: 6-12 alphanumeric
    return bool(re.match(r'^[A-Z0-9]{6,12}$', passport_num.upper()))


def validate_date_range(start_date: date, end_date: date) -> bool:
    """Validate date sequence"""
    if start_date and end_date:
        return start_date <= end_date
    return True


def validate_date_reasonable(check_date: date, field_name: str = "") -> bool:
    """Validate date is within reasonable range"""
    if not check_date:
        return True

    current_year = datetime.now().year
    if check_date.year < 1900 or check_date.year > current_year + 10:
        return False

    return True


def validate_segment_data(data: Dict[str, Any], doc_type: str) -> Dict[str, Any]:
    """Validate extracted data for a document segment"""
    validation_results = {
        'valid_fields': [],
        'invalid_fields': [],
        'warnings': [],
        'overall_score': 0.0
    }

    total_fields = 0
    valid_fields = 0

    # USCIS document validation (I-797, I-797C, I-129)
    if doc_type in ['I797', 'I797C', 'I129']:
        receipt_num = data.get('receipt_number')
        if receipt_num:
            total_fields += 1
            if validate_receipt_number(receipt_num):
                validation_results['valid_fields'].append('receipt_number')
                valid_fields += 1
            else:
                validation_results['invalid_fields'].append('receipt_number')

        # Date validations
        notice_date = parse_date_flexible(data.get('notice_date'))
        received_date = parse_date_flexible(data.get('received_date'))

        if notice_date:
            total_fields += 1
            if validate_date_reasonable(notice_date, 'notice_date'):
                validation_results['valid_fields'].append('notice_date')
                valid_fields += 1
            else:
                validation_results['invalid_fields'].append('notice_date')

        if received_date:
            total_fields += 1
            if validate_date_reasonable(received_date, 'received_date'):
                validation_results['valid_fields'].append('received_date')
                valid_fields += 1
            else:
                validation_results['invalid_fields'].append('received_date')

        # Date sequence validation
        if notice_date and received_date:
            if not validate_date_range(received_date, notice_date):
                validation_results['warnings'].append(
                    'Notice date is before received date'
                )

    # I-94 validation
    elif doc_type == 'I94':
        i94_num = data.get('admission_record_number') or data.get('admission_i94_record_number')
        if i94_num:
            total_fields += 1
            if validate_i94_number(i94_num):
                validation_results['valid_fields'].append('admission_record_number')
                valid_fields += 1
            else:
                validation_results['invalid_fields'].append('admission_record_number')

    # Passport validation
    elif doc_type in ['US_PASSPORT', 'FOREIGN_PASSPORT']:
        passport_num = data.get('passport_number')
        country = data.get('issuing_country', 'USA' if doc_type == 'US_PASSPORT' else None)

        if passport_num:
            total_fields += 1
            if validate_passport_number(passport_num, country):
                validation_results['valid_fields'].append('passport_number')
                valid_fields += 1
            else:
                validation_results['invalid_fields'].append('passport_number')

    # EAD validation
    elif doc_type == 'EAD':
        uscis_num = data.get('uscis_number')
        if uscis_num:
            total_fields += 1
            if len(uscis_num) >= 8:  # Basic length check
                validation_results['valid_fields'].append('uscis_number')
                valid_fields += 1
            else:
                validation_results['invalid_fields'].append('uscis_number')

    # Calculate overall score
    if total_fields > 0:
        validation_results['overall_score'] = valid_fields / total_fields
    else:
        validation_results['overall_score'] = 0.0

    return validation_results


def parse_date_flexible(date_str: Optional[str]) -> Optional[date]:
    """Parse date string with multiple format attempts"""
    if not date_str or date_str.lower() in ['null', 'n/a', '']:
        return None

    # Clean the string
    date_str = date_str.strip()

    # Handle formats like "19DEC1994"
    ddmmmyyyy_match = re.match(r'^(\d{1,2})([A-Za-z]{3})(\d{4})$', date_str)
    if ddmmmyyyy_match:
        day, month, year = ddmmmyyyy_match.groups()
        date_str = f"{day}-{month.title()}-{year}"

    # Try various formats
    formats = [
        "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d-%b-%Y", "%d-%B-%Y",
        "%d %b %Y", "%d %B %Y", "%Y %B %d", "%b %d %Y", "%B %d %Y",
        "%m/%d/%y", "%d/%m/%Y"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    # Last attempt: extract date patterns
    ymd_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
    if ymd_match:
        try:
            return datetime.strptime(ymd_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass

    mdy_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', date_str)
    if mdy_match:
        try:
            return datetime.strptime(mdy_match.group(1), "%m/%d/%Y").date()
        except ValueError:
            pass

    return None


def get_document_specific_prompt(doc_type: str) -> str:
    """Get document-specific extraction prompts for all supported document types"""

    prompts = {
        'I797': """
You are processing an I-797 USCIS Notice of Action (including I-140 approvals, I-129 approvals, etc.). Extract key fields and return as JSON:
{
    "receipt_number": "string (e.g., IOE0926970247)",
    "received_date": "YYYY-MM-DD",
    "notice_date": "YYYY-MM-DD", 
    "priority_date": "YYYY-MM-DD",
    "case_type": "string (e.g., I140 - IMMIGRANT PETITION FOR ALIEN WORKER, I129 - PETITION FOR A NONIMMIGRANT WORKER)",
    "petitioner": "string (company name)",
    "beneficiary": "string (person name)",
    "notice_type": "string (e.g., Approval Notice)",
    "classification": "string (e.g., Outstanding Professor, H1B, EB-1, EB-2, etc.)",
    "consulate": "string",
    "eta_case_number": "string",
    "soc_code": "string",
    "class": "string (e.g., H1B)",
    "valid_from": "string (date range)",
    "valid_to": "string (date)",
    "i94_number": "string",
    "country_of_citizenship": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'I797C': """
You are processing an I-797C Receipt Notice (including I-140 receipt notices, I-129 receipt notices, etc.). Extract key fields and return as JSON:
{
    "receipt_number": "string (MSC/NBC/EAC/WAC + 10 digits)",
    "case_type": "string (e.g., I140 - IMMIGRANT PETITION FOR ALIEN WORKER, I129 - PETITION FOR A NONIMMIGRANT WORKER)",
    "received_date": "YYYY-MM-DD",
    "notice_date": "YYYY-MM-DD", 
    "petitioner": "string (company name)",
    "beneficiary": "string (person name)",
    "priority_date": "YYYY-MM-DD",
    "notice_type": "string (typically Receipt Notice)"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'I129': """
You are processing an I-129 Petition for Nonimmigrant Worker. Extract key fields and return as JSON:
{
    "family_name": "string (last name)",
    "given_name": "string (first name)",
    "date_of_birth": "YYYY-MM-DD",
    "male": "string",
    "female": "string",
    "country_of_birth": "string",
    "country_of_citizenship": "string",
    "passport_issue_date": "YYYY-MM-DD",
    "passport_expiry_date": "YYYY-MM-DD",
    "passport_country": "string",
    "street_address": "string",
    "apartment": "string",
    "suite": "string",
    "floor": "string",
    "number": "string",
    "city": "string",
    "state": "string",
    "zip_code": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'PWD': """
You are processing a Prevailing Wage Determination (9141). Extract key fields and return as JSON:
{
    "expiration_date": "YYYY-MM-DD",
    "pwd_case_number": "string",
    "case_status": "string",
    "validity_period": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'PERM': """
You are processing a PERM Labor Certification (9089). Extract key fields and return as JSON:
{
    "expiration_date": "YYYY-MM-DD",
    "perm_case_number": "string",
    "case_status": "string",
    "determination_date": "YYYY-MM-DD"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'LCA': """
You are processing a Labor Condition Application (LCA/ETA-9035). Extract key fields and return as JSON:
{
    "job_title": "string",
    "soc_code": "string",
    "soc_occupation_title": "string",
    "legal_business_name": "string",
    "wage_rate": "string",
    "case_number": "string",
    "case_status": "string",
    "period_of_employment": "string",
    "number_of_workers": "string",
    "secondary_entity": "string",
    "secondary_entity_name": "string",
    "address_1": "string",
    "address_2": "string",
    "city": "string",
    "county": "string",
    "state": "string",
    "postal_code": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'I94': """
You are processing an I-94 Arrival/Departure record. Extract key fields and return as JSON:
{
    "admission_record_number": "string (11 digits)",
    "arrival_date": "YYYY-MM-DD",
    "class_of_admission": "string (visa category)",
    "admit_until_date": "YYYY-MM-DD or 'D/S'",
    "last_name": "string",
    "first_name": "string",
    "birth_date": "YYYY-MM-DD",
    "document_number": "string",
    "country_of_citizenship": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'EAD': """
You are processing an Employment Authorization Document (EAD/I-766). Extract key fields and return as JSON:
{
    "full_name": "string (person's full name)",
    "uscis_number": "string (USCIS number)", 
    "card_number": "string (card number)",
    "category": "string (work authorization category like C09, A05, etc.)",
    "country_of_birth": "string",
    "birth_date": "YYYY-MM-DD",
    "issue_date": "YYYY-MM-DD (date card was issued)",
    "expiration_date": "YYYY-MM-DD (date card expires)",
    "work_authorized": "string (work authorization details)"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'GREEN_CARD': """
You are processing a Permanent Resident Card (Green Card/I-551). Extract key fields and return as JSON:
{
    "full_name": "string (person's full name)",
    "alien_number": "string (A-number like A123456789)",
    "uscis_number": "string (USCIS number)",
    "birth_date": "YYYY-MM-DD",
    "country_of_birth": "string",
    "issue_date": "YYYY-MM-DD (date card was issued)",
    "expiration_date": "YYYY-MM-DD (date card expires)",
    "resident_since": "YYYY-MM-DD (permanent resident since date)",
    "category": "string (immigration category like IR1, F1, etc.)"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'VISA_STAMP': """
You are processing a visa stamp. Extract key fields and return as JSON:
{
    "issuing_post_name": "string",
    "surname": "string",
    "given_name": "string",
    "passport_number": "string",
    "control_number": "string",
    "sex": "string",
    "birth_date": "YYYY-MM-DD",
    "issue_date": "YYYY-MM-DD",
    "expiration_date": "YYYY-MM-DD",
    "visa_type": "string (e.g., H1B)",
    "nationality": "string",
    "petition_expiry": "YYYY-MM-DD"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'US_PASSPORT': """
You are processing a US passport. Extract key fields and return as JSON:
{
    "code": "string (country code)",
    "date_of_issue": "YYYY-MM-DD",
    "date_of_expiry": "YYYY-MM-DD",
    "passport_number": "string",
    "holder_name": "string",
    "birth_date": "YYYY-MM-DD",
    "birth_place": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'FOREIGN_PASSPORT': """
You are processing a foreign passport. Extract key fields and return as JSON:
{
    "code": "string (country code)",
    "date_of_issue": "YYYY-MM-DD",
    "date_of_expiry": "YYYY-MM-DD",
    "passport_number": "string",
    "holder_name": "string",
    "birth_date": "YYYY-MM-DD",
    "birth_place": "string",
    "issuing_country": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """,

        'GENERIC': """
You are processing an immigration-related document. Extract any key fields and return as JSON:
{
    "document_type": "string (best guess at document type)",
    "full_name": "string",
    "birth_date": "YYYY-MM-DD",
    "document_number": "string",
    "issue_date": "YYYY-MM-DD",
    "expiry_date": "YYYY-MM-DD",
    "issuing_authority": "string"
}
Only include fields that are clearly present. Use null for missing fields.
        """
    }

    return prompts.get(doc_type, prompts['GENERIC'])


def check_case_completeness(person_data: Dict) -> Dict:
    """Check what documents are present vs. typically needed"""
    documents = person_data.get('documents', [])
    doc_types = [doc['type'] for doc in documents]

    completeness = {
        'has_petition': any(dt in doc_types for dt in ['I129', 'I797', 'I797C']),
        'has_labor_cert': any(dt in doc_types for dt in ['PERM', 'LCA']),
        'has_passport': any('PASSPORT' in dt for dt in doc_types),
        'has_visa': 'VISA_STAMP' in doc_types,
        'has_entry_record': 'I94' in doc_types,
        'has_work_auth': any(dt in doc_types for dt in ['EAD', 'GREEN_CARD']),
        'missing_documents': [],
        'completeness_score': 0.0
    }

    # Calculate what's typically missing
    if completeness['has_labor_cert'] and not completeness['has_petition']:
        completeness['missing_documents'].append('I-129 petition or I-797 approval notice')

    if completeness['has_petition'] and not completeness['has_entry_record']:
        completeness['missing_documents'].append('I-94 entry record')

    if not completeness['has_passport']:
        completeness['missing_documents'].append('Passport')

    if not completeness['has_work_auth']:
        completeness['missing_documents'].append('Work authorization (EAD or Green Card)')

    # Calculate completeness score
    total_expected = 6  # petition, labor cert, passport, visa, entry record, work auth
    present_count = sum([
        completeness['has_petition'],
        completeness['has_labor_cert'],
        completeness['has_passport'],
        completeness['has_visa'],
        completeness['has_entry_record'],
        completeness['has_work_auth']
    ])

    completeness['completeness_score'] = present_count / total_expected

    return completeness