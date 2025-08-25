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
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                cursor.close()

    def store_processing_results(self, results: Dict[str, Any]) -> str:
        """Store complete processing results"""
        processing_id = results.get('processing_id', str(uuid.uuid4()))

        with self.transaction() as cursor:
            # Store processing session
            cursor.execute("""
                INSERT INTO processing_sessions 
                (processing_id, file_name, processed_at, results_json, summary_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                processing_id,
                results.get('file_path'),
                datetime.fromisoformat(results.get('processed_at')),
                json.dumps(results),
                json.dumps(results.get('processing_summary', {}))
            ))

            # Store person records
            for person_key, person_data in results.get('person_records', {}).items():
                person_id = self.store_or_update_person(cursor, person_data, processing_id)

                # Store documents for this person
                for doc in person_data.get('documents', []):
                    self.store_document(cursor, doc, person_id, processing_id)

        return processing_id

    def store_or_update_person(self, cursor, person_data: Dict, processing_id: str) -> str:
        """Store or update person record"""
        person_id = self.find_existing_person(
            cursor,
            person_data.get('name'),
            person_data.get('date_of_birth')
        )

        if not person_id:
            person_id = self.generate_person_id()
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

        return person_id

    def find_existing_person(self, cursor, name: str, dob: str) -> Optional[str]:
        """Find existing person by name and DOB"""
        if not name:
            return None

        if dob:
            cursor.execute(
                "SELECT person_id FROM persons WHERE name=? AND date_of_birth=?",
                (name, self.parse_date(dob))
            )
        else:
            cursor.execute(
                "SELECT TOP 1 person_id FROM persons WHERE name=?",
                (name,)
            )

        result = cursor.fetchone()
        return result[0] if result else None

    def store_document(self, cursor, doc_data: Dict, person_id: str, processing_id: str):
        """Store document based on type"""
        doc_type = doc_data.get('type')
        extracted_data = doc_data.get('data', {})

        if doc_type in ['I797', 'I140']:
            self.store_uscis_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type in ['PERM', 'PWD']:
            self.store_dol_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type == 'I94':
            self.store_i94_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type in ['US_PASSPORT', 'FOREIGN_PASSPORT']:
            self.store_passport_document(cursor, extracted_data, person_id, processing_id)
        elif doc_type == 'VISA_STAMP':
            self.store_visa_document(cursor, extracted_data, person_id, processing_id)

    def store_uscis_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store USCIS document"""
        if not self.has_meaningful_data(data):
            return

        cursor.execute("""
            INSERT INTO uscis_forms 
            (person_id, processing_id, receipt_number, notice_date, received_date, 
             priority_date, case_type, notice_type, petitioner, beneficiary, 
             valid_from, valid_to, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id, processing_id,
            data.get('receipt_number'),
            self.parse_date(data.get('notice_date')),
            self.parse_date(data.get('received_date')),
            self.parse_date(data.get('priority_date')),
            data.get('case_type'),
            data.get('notice_type'),
            data.get('petitioner'),
            data.get('beneficiary'),
            self.parse_date(data.get('valid_from')),
            self.parse_date(data.get('valid_to')),
            datetime.utcnow()
        ))

    def store_dol_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store DOL document"""
        if not self.has_meaningful_data(data):
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

    def store_i94_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store I-94 document"""
        if not self.has_meaningful_data(data):
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

    def store_passport_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store passport document"""
        if not self.has_meaningful_data(data):
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

    def store_visa_document(self, cursor, data: Dict, person_id: str, processing_id: str):
        """Store visa document"""
        if not self.has_meaningful_data(data):
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
                "%d %B %Y", "%B %d %Y"
            ]

            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue

            return None
        except:
            return None

    def has_meaningful_data(self, data: Dict) -> bool:
        """Check if data dict has meaningful values"""
        return any(v is not None and v != "" and v != "null" for v in data.values())