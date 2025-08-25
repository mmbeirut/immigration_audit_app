import os
import pyodbc
import json
import uuid
from datetime import datetime
from contextlib import contextmanager
from typing import Dict, Any, Optional, List


class DatabaseManager:
    def __init__(self):
        self.setup_connection()

    def setup_connection(self):
        """Setup database connection string"""
        self.conn_str = (
            f"DRIVER={os.getenv('SQL_DRIVER')};"
            f"SERVER={os.getenv('SQL_SERVER')};"
            f"DATABASE={os.getenv('SQL_DATABASE')};"
            f"Trusted_Connection=yes"
        )

        # Test connection
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                print("Database connection successful")
        except Exception as e:
            print(f"Database connection error: {e}")

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = pyodbc.connect(self.conn_str)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """Context manager for database transactions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
                print("Transaction committed successfully")
            except Exception as e:
                conn.rollback()
                print(f"Transaction rolled back due to error: {e}")
                raise e
            finally:
                cursor.close()

    def store_processing_results(self, results: Dict[str, Any]) -> str:
        """Store complete processing results"""
        processing_id = results.get('processing_id', str(uuid.uuid4()))

        print(f"DEBUG: Starting to store processing results for ID: {processing_id}")
        print(f"DEBUG: Results keys: {list(results.keys())}")
        print(f"DEBUG: Person records count: {len(results.get('person_records', {}))}")
        print(f"DEBUG: Documents processed count: {len(results.get('documents_processed', []))}")

        try:
            with self.transaction() as cursor:
                # Store processing session
                print("DEBUG: Storing processing session...")
                processed_at = datetime.fromisoformat(results.get('processed_at').replace('Z', '+00:00'))

                cursor.execute("""
                    INSERT INTO processing_sessions 
                    (processing_id, file_name, processed_at, results_json, summary_json)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    processing_id,
                    results.get('file_path'),
                    processed_at,
                    json.dumps(results),
                    json.dumps(results.get('processing_summary', {}))
                ))
                print("DEBUG: Processing session stored successfully")

                # Store person records
                person_count = 0
                for person_key, person_data in results.get('person_records', {}).items():
                    print(f"DEBUG: Processing person: {person_key}")
                    print(f"DEBUG: Person data: {person_data}")

                    person_id = self.store_or_update_person(cursor, person_data, processing_id)
                    print(f"DEBUG: Person stored with ID: {person_id}")
                    person_count += 1

                    # Store documents for this person
                    doc_count = 0
                    for doc in person_data.get('documents', []):
                        print(f"DEBUG: Storing document type: {doc.get('type')}")
                        print(f"DEBUG: Document data keys: {list(doc.get('data', {}).keys())}")

                        self.store_document(cursor, doc, person_id, processing_id)
                        doc_count += 1
                        print(f"DEBUG: Document {doc_count} stored successfully")

                print(f"DEBUG: Successfully stored {person_count} persons and their documents")

        except Exception as e:
            print(f"DEBUG: Error in store_processing_results: {str(e)}")
            print(f"DEBUG: Error type: {type(e)}")
            raise e

        return processing_id

    def store_or_update_person(self, cursor, person_data: Dict, processing_id: str) -> str:
        """Store or update person record"""
        print(f"DEBUG: Looking for existing person: {person_data.get('name')}, DOB: {person_data.get('date_of_birth')}")

        person_id = self.find_existing_person(
            cursor,
            person_data.get('name'),
            person_data.get('date_of_birth')
        )

        if not person_id:
            person_id = self.generate_person_id()
            print(f"DEBUG: Creating new person with ID: {person_id}")

            cursor.execute("""
                INSERT INTO persons 
                (person_id, name, date_of_birth, created_at, processing_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                person_id,
                person_data.get('name'),
                self.parse_date(person_data.get('date_of_birth')),
                datetime.utcnow(),
                processing_id
            ))
            print(f"DEBUG: New person inserted successfully")
        else:
            print(f"DEBUG: Found existing person with ID: {person_id}")

        return person_id

    def find_existing_person(self, cursor, name: str, dob: str) -> Optional[str]:
        """Find existing person by name and DOB"""
        if not name:
            print("DEBUG: No name provided for person lookup")
            return None

        print(f"DEBUG: Searching for person: name='{name}', dob='{dob}'")

        if dob:
            parsed_dob = self.parse_date(dob)
            print(f"DEBUG: Parsed DOB: {parsed_dob}")
            cursor.execute(
                "SELECT person_id FROM persons WHERE name=? AND date_of_birth=?",
                (name, parsed_dob)
            )
        else:
            cursor.execute(
                "SELECT TOP 1 person_id FROM persons WHERE name=?",
                (name,)
            )

        result = cursor.fetchone()
        found_id = result[0] if result else None
        print(f"DEBUG: Person lookup result: {found_id}")
        return found_id

    def store_document(self, cursor, doc_data: Dict, person_id: str, processing_id: str):
        """Store document based on type"""
        doc_type = doc_data.get('type')
        extracted_data = doc_data.get('data', {})

        print(f"DEBUG: Storing document type: {doc_type}")
        print(f"DEBUG: Extracted data: {extracted_data}")

        if doc_type in ['I797', 'I140']:
            print("DEBUG: Storing as USCIS document")
            self.store_uscis_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type in ['PERM', 'PWD']:
            print("DEBUG: Storing as DOL document")
            self.store_dol_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type == 'I94':
            print("DEBUG: Storing as I94 document")
            self.store_i94_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type in ['US_PASSPORT', 'FOREIGN_PASSPORT']:
            print("DEBUG: Storing as passport document")
            self.store_passport_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type == 'VISA_STAMP':
            print("DEBUG: Storing as visa document")
            self.store_visa_document(cursor, extracted_data, person_id, processing_id)
        else:
            print(f"DEBUG: Unknown document type: {doc_type}, skipping storage")

    def store_uscis_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store USCIS document"""
        print(f"DEBUG: USCIS document data: {data}")

        if not self.has_meaningful_data(data):
            print("DEBUG: No meaningful data in USCIS document, skipping")
            return

        # Parse dates
        notice_date = self.parse_date(data.get('notice_date'))
        received_date = self.parse_date(data.get('received_date'))
        priority_date = self.parse_date(data.get('priority_date'))
        valid_from = self.parse_date(data.get('valid_from'))
        valid_to = self.parse_date(data.get('valid_to'))

        print(f"DEBUG: Parsed dates - notice: {notice_date}, received: {received_date}, priority: {priority_date}")

        cursor.execute("""
            INSERT INTO uscis_forms 
            (person_id, processing_id, receipt_number, notice_date, received_date, 
             priority_date, case_type, notice_type, petitioner, beneficiary, 
             valid_from, valid_to, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id, processing_id,
            data.get('receipt_number'),
            notice_date,
            received_date,
            priority_date,
            data.get('case_type'),
            data.get('notice_type'),
            data.get('petitioner'),
            data.get('beneficiary'),
            valid_from,
            valid_to,
            datetime.utcnow()
        ))
        print("DEBUG: USCIS document stored successfully")

    def store_dol_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store DOL document"""
        print(f"DEBUG: DOL document data: {data}")

        if not self.has_meaningful_data(data):
            print("DEBUG: No meaningful data in DOL document, skipping")
            return

        cursor.execute("""
            INSERT INTO dol_forms 
            (person_id, processing_id, case_number, case_status, 
             determination_date, valid_from, valid_until, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id, processing_id,
            data.get('case_number'),
            data.get('case_status'),
            self.parse_date(data.get('determination_date')),
            self.parse_date(data.get('valid_from')),
            self.parse_date(data.get('valid_until')),
            datetime.utcnow()
        ))
        print("DEBUG: DOL document stored successfully")

    def store_i94_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store I-94 document"""
        print(f"DEBUG: I94 document data: {data}")

        if not self.has_meaningful_data(data):
            print("DEBUG: No meaningful data in I94 document, skipping")
            return

        cursor.execute("""
            INSERT INTO i94_records 
            (person_id, processing_id, admission_record_number, arrival_date, 
             class_of_admission, admit_until_date, port_of_entry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id, processing_id,
            data.get('admission_record_number'),
            self.parse_date(data.get('arrival_date')),
            data.get('class_of_admission'),
            self.parse_date(data.get('admit_until_date')),
            data.get('port_of_entry'),
            datetime.utcnow()
        ))
        print("DEBUG: I94 document stored successfully")

    def store_passport_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store passport document"""
        print(f"DEBUG: Passport document data: {data}")

        if not self.has_meaningful_data(data):
            print("DEBUG: No meaningful data in passport document, skipping")
            return

        cursor.execute("""
            INSERT INTO passports 
            (person_id, processing_id, passport_number, issuing_country, 
             issue_date, expiry_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id, processing_id,
            data.get('passport_number'),
            data.get('issuing_country'),
            self.parse_date(data.get('issue_date')),
            self.parse_date(data.get('expiry_date')),
            datetime.utcnow()
        ))
        print("DEBUG: Passport document stored successfully")

    def store_visa_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store visa document"""
        print(f"DEBUG: Visa document data: {data}")

        if not self.has_meaningful_data(data):
            print("DEBUG: No meaningful data in visa document, skipping")
            return

        cursor.execute("""
            INSERT INTO visas 
            (person_id, processing_id, visa_number, visa_type, visa_class, 
             issue_date, expiry_date, issuing_post, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id, processing_id,
            data.get('visa_number'),
            data.get('visa_type'),
            data.get('visa_class'),
            self.parse_date(data.get('issue_date')),
            self.parse_date(data.get('expiry_date')),
            data.get('issuing_post'),
            datetime.utcnow()
        ))
        print("DEBUG: Visa document stored successfully")

    def get_processing_results(self, processing_id: str) -> Optional[Dict]:
        """Retrieve processing results by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT results_json FROM processing_sessions 
                WHERE processing_id = ?
            """, (processing_id,))

            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None

    def generate_person_id(self) -> str:
        """Generate unique person ID"""
        return "FN" + str(uuid.uuid4())[:6].upper()

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime object"""
        if not date_str or date_str == 'null':
            return None

        try:
            # Try various date formats
            formats = [
                "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y",
                "%d %B %Y", "%B %d %Y", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"
            ]

            for fmt in formats:
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    print(f"DEBUG: Successfully parsed date '{date_str}' using format '{fmt}' -> {parsed}")
                    return parsed
                except ValueError:
                    continue

            print(f"DEBUG: Could not parse date: '{date_str}'")
            return None
        except Exception as e:
            print(f"DEBUG: Error parsing date '{date_str}': {e}")
            return None

    def has_meaningful_data(self, data: Dict) -> bool:
        """Check if data dict has meaningful values"""
        meaningful = any(v is not None and v != "" and v != "null" for v in data.values())
        print(f"DEBUG: Data has meaningful content: {meaningful}")
        print(f"DEBUG: Data values: {list(data.values())}")
        return meaningful