import os
import json
import logging
from datetime import datetime
from typing import Dict, Any

from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

from models.document_processor import DocumentProcessor  # Updated to use new processor
from models.database import DatabaseManager
from models.validators import setup_logging

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-key-change-in-production')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Setup logging
setup_logging(app)

# Initialize components
db_manager = DatabaseManager()
doc_processor = DocumentProcessor()


@app.route('/', methods=['GET'])
def index():
    """Main upload page"""
    return render_template('upload.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and processing"""
    try:
        app.logger.info("Upload request received")

        if 'file' not in request.files:
            app.logger.error("No file in request")
            flash('No file selected', 'error')
            return redirect(url_for('index'))

        file = request.files['file']
        app.logger.info(f"File received: {file.filename}")

        if file.filename == '':
            app.logger.error("Empty filename")
            flash('No file selected', 'error')
            return redirect(url_for('index'))

        if not file.filename.lower().endswith('.pdf'):
            app.logger.error(f"Invalid file type: {file.filename}")
            flash('Only PDF files are supported', 'error')
            return redirect(url_for('index'))

        # Save uploaded file
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        app.logger.info(f"File saved to: {file_path}")

        # Get processing options
        processing_mode = request.form.get('processing_mode', 'multi_document')
        options = {
            'check_completeness': request.form.get('check_completeness') == 'on',
            'cross_reference': request.form.get('cross_reference') == 'on',
            'timeline_analysis': request.form.get('timeline_analysis') == 'on',
            'validate_fields': request.form.get('validate_fields') == 'on',
            'check_duplicates': request.form.get('check_duplicates') == 'on'
        }
        app.logger.info(f"Processing mode: {processing_mode}, Options: {options}")

        # Process the file
        app.logger.info("Starting file processing...")
        if processing_mode == 'single_document':
            document_type = request.form.get('document_type', 'auto')
            results = doc_processor.process_single_document(file_path, document_type, options)

            # Add missing fields for single document processing to match multi-document format
            if 'processing_summary' not in results:
                # Create basic processing summary
                extracted_data = results.get('extracted_data', {})
                person_name = (
                        extracted_data.get('beneficiary') or
                        extracted_data.get('full_name') or
                        extracted_data.get('holder_name') or
                        f"{extracted_data.get('first_name', '')} {extracted_data.get('last_name', '')}".strip()
                )

                results['processing_summary'] = {
                    'file_overview': {
                        'total_pages': 1,  # Single document
                        'document_types_found': {results.get('document_type', 'UNKNOWN'): 1},
                        'people_identified': 1 if person_name else 0,
                        'date_range': {
                            'earliest': extracted_data.get('notice_date') or extracted_data.get('issue_date'),
                            'latest': extracted_data.get('notice_date') or extracted_data.get('issue_date')
                        }
                    },
                    'completeness_check': {},
                    'red_flags': [],
                    'recommendations': []
                }

            # Convert single document format to match multi-document format
            if 'documents_processed' not in results:
                results['documents_processed'] = [{
                    'pages': [0],  # Single document, page 0
                    'document_type': results.get('document_type', 'UNKNOWN'),
                    'confidence': 0.8,
                    'extracted_data': results.get('extracted_data', {}),
                    'validation_results': results.get('validation_results', {}),
                    'processing_notes': results.get('processing_notes', [])
                }]

            # Create person records if not exist
            if 'person_records' not in results:
                results['person_records'] = {}
                extracted_data = results.get('extracted_data', {})
                person_name = (
                        extracted_data.get('beneficiary') or
                        extracted_data.get('full_name') or
                        extracted_data.get('holder_name') or
                        f"{extracted_data.get('first_name', '')} {extracted_data.get('last_name', '')}".strip()
                )

                if person_name:
                    person_key = f"{person_name}_{extracted_data.get('date_of_birth', '')}"
                    results['person_records'][person_key] = {
                        'name': person_name,
                        'date_of_birth': extracted_data.get('date_of_birth'),
                        'documents': [{
                            'type': results.get('document_type', 'UNKNOWN'),
                            'pages': [0],
                            'data': extracted_data
                        }],
                        'timeline': [],
                        'inconsistencies': []
                    }

                    # Add timeline entry if date available
                    doc_date = (
                            extracted_data.get('notice_date') or
                            extracted_data.get('issue_date') or
                            extracted_data.get('received_date')
                    )
                    if doc_date:
                        results['person_records'][person_key]['timeline'].append({
                            'date': doc_date,
                            'document': results.get('document_type', 'UNKNOWN'),
                            'event': f"{results.get('document_type', 'UNKNOWN')} processed"
                        })

            # Ensure validation_errors exists
            if 'validation_errors' not in results:
                results['validation_errors'] = []

        else:
            results = doc_processor.process_multi_document_file(file_path, options)

        app.logger.info("File processing completed")

        # Store results in database with detailed error handling
        app.logger.info("Storing results in database...")
        try:
            processing_id = db_manager.store_processing_results(results)
            app.logger.info(f"Results stored successfully with ID: {processing_id}")

            # Update results with the processing ID for links
            results['processing_id'] = processing_id

        except Exception as db_error:
            app.logger.error(f"Database storage failed: {str(db_error)}", exc_info=True)

            # Check if it's a connection issue
            if "Invalid object name" in str(db_error):
                app.logger.error("Database tables don't exist. Please run the schema creation script.")
                flash('Database error: Tables not found. Please contact administrator.', 'error')
            elif "Login failed" in str(db_error) or "Cannot open database" in str(db_error):
                app.logger.error("Database connection/authentication failed")
                flash('Database connection failed. Please contact administrator.', 'error')
            else:
                app.logger.error(f"Unexpected database error: {str(db_error)}")
                flash('Database storage failed, but processing completed. Results shown below.', 'warning')

            # Continue to show results even if database storage fails
            results['processing_id'] = None

        # Generate results response
        results_html = render_template('results.html', results=results)

        # Clean up uploaded file AFTER processing
        try:
            os.remove(file_path)
            app.logger.info("Temporary file cleaned up")
        except Exception as cleanup_error:
            app.logger.warning(f"Failed to clean up file: {cleanup_error}")

        return results_html

    except Exception as e:
        app.logger.error(f"Upload processing error: {str(e)}", exc_info=True)
        flash(f'Processing error: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/audit_summary/<result_id>')
def audit_summary(result_id):
    """Display detailed audit summary"""
    try:
        results = db_manager.get_processing_results(result_id)
        if not results:
            flash('Results not found', 'error')
            return redirect(url_for('index'))

        return render_template('audit_summary.html', results=results)
    except Exception as e:
        app.logger.error(f"Audit summary error: {str(e)}")
        flash('Error loading audit summary', 'error')
        return redirect(url_for('index'))


@app.route('/api/progress/<task_id>')
def get_progress(task_id):
    """Get processing progress for AJAX updates"""
    # This would integrate with a task queue like Celery for long-running processes
    return jsonify({'progress': 100, 'status': 'complete'})


@app.route('/test')
def test_upload():
    """Simple test upload page"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple Upload Test</title>
    </head>
    <body>
        <h2>Simple Upload Test</h2>
        <form method="POST" action="/upload" enctype="multipart/form-data">
            <input type="file" name="file" accept=".pdf" required>
            <br><br>
            <input type="hidden" name="processing_mode" value="multi_document">
            <input type="hidden" name="check_completeness" value="on">
            <input type="hidden" name="validate_fields" value="on">
            <br>
            <button type="submit">Upload</button>
        </form>
    </body>
    </html>
    '''


@app.route('/db_test')
def test_database():
    """Test database connectivity"""
    try:
        # Test basic connection
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]

        # Test table existence
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_NAME IN ('processing_sessions', 'persons', 'uscis_forms', 'dol_forms', 'i94_records', 'passports', 'visas')
            """)
            table_count = cursor.fetchone()[0]

        return f"""
        <h2>Database Test Results</h2>
        <p><strong>Connection:</strong> SUCCESS</p>
        <p><strong>SQL Server Version:</strong> {version}</p>
        <p><strong>Required Tables Found:</strong> {table_count}/7</p>
        <p><strong>Connection String:</strong> {db_manager.conn_str}</p>
        <hr>
        <a href="/">Back to Upload</a>
        """

    except Exception as e:
        return f"""
        <h2>Database Test Results</h2>
        <p><strong>Connection:</strong> FAILED</p>
        <p><strong>Error:</strong> {str(e)}</p>
        <p><strong>Connection String:</strong> {db_manager.conn_str}</p>
        <hr>
        <a href="/">Back to Upload</a>
        """


@app.route('/db_check')
def check_database_contents():
    """Check what's actually in the database"""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()

            # Check processing_sessions
            cursor.execute("SELECT COUNT(*) FROM processing_sessions")
            sessions_count = cursor.fetchone()[0]

            # Check persons
            cursor.execute("SELECT COUNT(*) FROM persons")
            persons_count = cursor.fetchone()[0]

            # Check uscis_forms
            cursor.execute("SELECT COUNT(*) FROM uscis_forms")
            uscis_count = cursor.fetchone()[0]

            # Get recent processing sessions
            cursor.execute("""
                SELECT TOP 5 processing_id, file_name, processed_at 
                FROM processing_sessions 
                ORDER BY processed_at DESC
            """)
            recent_sessions = cursor.fetchall()

            # Get recent persons
            cursor.execute("""
                SELECT TOP 5 person_id, name, date_of_birth, created_at 
                FROM persons 
                ORDER BY created_at DESC
            """)
            recent_persons = cursor.fetchall()

            # Get recent USCIS forms
            cursor.execute("""
                SELECT TOP 5 person_id, receipt_number, notice_date, beneficiary, created_at 
                FROM uscis_forms 
                ORDER BY created_at DESC
            """)
            recent_uscis = cursor.fetchall()

        html = f"""
        <h2>Database Contents Check</h2>
        <h3>Record Counts:</h3>
        <ul>
            <li>Processing Sessions: {sessions_count}</li>
            <li>Persons: {persons_count}</li>
            <li>USCIS Forms: {uscis_count}</li>
        </ul>

        <h3>Recent Processing Sessions:</h3>
        <table border="1">
            <tr><th>ID</th><th>File</th><th>Processed At</th></tr>
        """
        for session in recent_sessions:
            html += f"<tr><td>{session[0]}</td><td>{session[1]}</td><td>{session[2]}</td></tr>"

        html += """
        </table>

        <h3>Recent Persons:</h3>
        <table border="1">
            <tr><th>Person ID</th><th>Name</th><th>DOB</th><th>Created At</th></tr>
        """
        for person in recent_persons:
            html += f"<tr><td>{person[0]}</td><td>{person[1]}</td><td>{person[2]}</td><td>{person[3]}</td></tr>"

        html += """
        </table>

        <h3>Recent USCIS Forms:</h3>
        <table border="1">
            <tr><th>Person ID</th><th>Receipt Number</th><th>Notice Date</th><th>Beneficiary</th><th>Created At</th></tr>
        """
        for uscis in recent_uscis:
            html += f"<tr><td>{uscis[0]}</td><td>{uscis[1]}</td><td>{uscis[2]}</td><td>{uscis[3]}</td><td>{uscis[4]}</td></tr>"

        html += """
        </table>
        <hr>
        <a href="/">Back to Upload</a>
        """

        return html

    except Exception as e:
        return f"""
        <h2>Database Check Error</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <hr>
        <a href="/">Back to Upload</a>
        """


@app.route('/debug_extraction')
def debug_extraction():
    """Debug the latest extraction results"""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 1 processing_id, file_name, results_json 
                FROM processing_sessions 
                ORDER BY processed_at DESC
            """)
            result = cursor.fetchone()

            if result:
                processing_id, file_name, results_json = result
                results = json.loads(results_json)

                extracted_data = results.get('extracted_data', {})
                person_records = results.get('person_records', {})

                html = f"""
                <h2>Latest Extraction Debug</h2>
                <p><strong>File:</strong> {file_name}</p>
                <p><strong>Processing ID:</strong> {processing_id}</p>

                <h3>Extracted Data:</h3>
                <pre>{json.dumps(extracted_data, indent=2)}</pre>

                <h3>Person Records:</h3>
                <pre>{json.dumps(person_records, indent=2)}</pre>

                <h3>Document Type:</h3>
                <p>{results.get('document_type', 'Unknown')}</p>

                <h3>Processing Notes:</h3>
                <pre>{json.dumps(results.get('processing_notes', []), indent=2)}</pre>

                <hr>
                <a href="/">Back to Upload</a>
                """
                return html
            else:
                return "No processing sessions found"

    except Exception as e:
        return f"Error: {str(e)}"


@app.route('/debug_text_extraction')
def debug_text_extraction():
    """Debug text extraction from the latest file"""
    try:
        # Get the most recent file from uploads directory
        upload_dir = app.config['UPLOAD_FOLDER']
        files = [f for f in os.listdir(upload_dir) if f.endswith('.pdf')]

        if not files:
            return "No PDF files found in uploads directory"

        # Get the most recent file
        latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(upload_dir, f)))
        file_path = os.path.join(upload_dir, latest_file)

        # Test text extraction
        extraction_result = doc_processor.extract_text_multi_method(file_path)

        # Test document type detection
        segments = doc_processor.analyze_pdf_by_pages(file_path)

        html = f"""
        <h2>Text Extraction Debug</h2>
        <p><strong>File:</strong> {latest_file}</p>

        <h3>Extraction Results:</h3>
        <p><strong>Method Used:</strong> {extraction_result.get('method_used', 'Unknown')}</p>
        <p><strong>Confidence:</strong> {extraction_result.get('confidence', 0)}</p>
        <p><strong>Text Length:</strong> {len(extraction_result.get('text', ''))}</p>

        <h3>First 2000 characters of extracted text:</h3>
        <pre style="background: #f5f5f5; padding: 10px; max-height: 300px; overflow-y: scroll;">
{extraction_result.get('text', 'NO TEXT EXTRACTED')[:2000]}
        </pre>

        <h3>Document Type Detection:</h3>
        <p><strong>Segments Found:</strong> {len(segments)}</p>
        """

        for i, segment in enumerate(segments):
            html += f"""
            <p><strong>Segment {i + 1}:</strong> Type={segment.doc_type}, Confidence={segment.confidence}</p>
            """

        html += """
        <hr>
        <a href="/">Back to Upload</a>
        """

        return html

    except Exception as e:
        return f"Error in text extraction debug: {str(e)}"


@app.route('/debug_azure_openai')
def debug_azure_openai():
    """Test Azure OpenAI connectivity"""
    try:
        # Test a simple LLM call
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say 'Hello, Azure OpenAI is working!'"}
        ]

        response = doc_processor.throttled_llm(messages)
        content = response.choices[0].message.content

        return f"""
        <h2>Azure OpenAI Test</h2>
        <p><strong>Status:</strong> SUCCESS</p>
        <p><strong>Response:</strong> {content}</p>
        <hr>
        <a href="/">Back to Upload</a>
        """

    except Exception as e:
        return f"""
        <h2>Azure OpenAI Test</h2>
        <p><strong>Status:</strong> FAILED</p>
        <p><strong>Error:</strong> {str(e)}</p>
        <hr>
        <a href="/">Back to Upload</a>
        """


@app.route('/debug_extraction_methods')
def debug_extraction_methods():
    """Debug each text extraction method separately"""
    try:
        upload_dir = app.config['UPLOAD_FOLDER']
        files = [f for f in os.listdir(upload_dir) if f.endswith('.pdf')]
        if not files:
            return "No PDF files found"

        latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(upload_dir, f)))
        file_path = os.path.join(upload_dir, latest_file)

        results = {}

        # Test PyMuPDF
        try:
            pymupdf_text = doc_processor.extract_text_pymupdf(file_path)
            results['pymupdf'] = {
                'success': True,
                'length': len(pymupdf_text),
                'sample': pymupdf_text[:200] if pymupdf_text else 'NO TEXT'
            }
        except Exception as e:
            results['pymupdf'] = {'success': False, 'error': str(e)}

        # Test Azure Form Recognizer
        try:
            azure_text = doc_processor.extract_text_azure(file_path)
            results['azure'] = {
                'success': True,
                'length': len(azure_text),
                'sample': azure_text[:200] if azure_text else 'NO TEXT'
            }
        except Exception as e:
            results['azure'] = {'success': False, 'error': str(e)}

        # Test the multi-method function
        try:
            multi_result = doc_processor.extract_text_multi_method(file_path)
            results['multi_method'] = {
                'success': True,
                'method_used': multi_result.get('method_used'),
                'confidence': multi_result.get('confidence'),
                'length': len(multi_result.get('text', '')),
                'sample': multi_result.get('text', '')[:200]
            }
        except Exception as e:
            results['multi_method'] = {'success': False, 'error': str(e)}

        html = f"""
        <h2>Text Extraction Methods Debug</h2>
        <p><strong>File:</strong> {latest_file}</p>
        <p><strong>File exists:</strong> {os.path.exists(file_path)}</p>
        <p><strong>File size:</strong> {os.path.getsize(file_path) if os.path.exists(file_path) else 'N/A'}</p>
        """

        for method, result in results.items():
            html += f"""
            <h3>{method.upper()}</h3>
            <p><strong>Success:</strong> {result.get('success', False)}</p>
            """
            if result.get('success'):
                html += f"""
                <p><strong>Length:</strong> {result.get('length', 0)}</p>
                <p><strong>Method Used:</strong> {result.get('method_used', 'N/A')}</p>
                <p><strong>Confidence:</strong> {result.get('confidence', 'N/A')}</p>
                <p><strong>Sample:</strong></p>
                <pre style="background: #f5f5f5; padding: 10px;">{result.get('sample', 'NO SAMPLE')}</pre>
                """
            else:
                html += f"<p><strong>Error:</strong> {result.get('error')}</p>"

        html += '<hr><a href="/">Back to Upload</a>'
        return html

    except Exception as e:
        return f"Debug error: {str(e)}"


@app.route('/debug_document_detection')
def debug_document_detection():
    """Debug document type detection on latest file"""
    try:
        upload_dir = app.config['UPLOAD_FOLDER']
        files = [f for f in os.listdir(upload_dir) if f.endswith('.pdf')]
        if not files:
            return "No PDF files found"

        latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(upload_dir, f)))
        file_path = os.path.join(upload_dir, latest_file)

        # Extract text and analyze
        extraction_result = doc_processor.extract_text_multi_method(file_path)
        text = extraction_result.get('text', '')

        # Test document detection
        segments = doc_processor.analyze_pdf_by_pages(file_path)

        html = f"""
        <h2>Document Detection Debug</h2>
        <p><strong>File:</strong> {latest_file}</p>
        <p><strong>Text Length:</strong> {len(text)}</p>

        <h3>Text Sample (first 1000 chars):</h3>
        <pre style="background: #f5f5f5; padding: 10px; max-height: 200px; overflow-y: scroll;">
{text[:1000]}
        </pre>

        <h3>Detection Results:</h3>
        <p><strong>Segments Found:</strong> {len(segments)}</p>
        """

        for i, segment in enumerate(segments):
            html += f"""
            <div style="border: 1px solid #ccc; margin: 10px 0; padding: 10px;">
                <h4>Segment {i + 1}</h4>
                <p><strong>Document Type:</strong> {segment.doc_type}</p>
                <p><strong>Confidence:</strong> {segment.confidence}</p>
                <p><strong>Pages:</strong> {segment.pages}</p>
                <p><strong>Text Sample:</strong></p>
                <pre style="background: #f8f8f8; padding: 5px; max-height: 150px; overflow-y: scroll;">
{segment.text[:500]}...
                </pre>
            </div>
            """

        html += '<hr><a href="/">Back to Upload</a>'
        return html

    except Exception as e:
        return f"Debug error: {str(e)}"


@app.route('/debug_llm_extraction')
def debug_llm_extraction():
    """Debug LLM extraction with sample text"""
    try:
        # Sample I-797 text for testing
        sample_text = """
        U.S. Citizenship and Immigration Services

        I-797, Notice of Action

        Receipt Number: IOE0926970247
        Case Type: I129 - PETITION FOR A NONIMMIGRANT WORKER

        Received Date: January 15, 2024
        Notice Date: February 10, 2024

        Petitioner: TECH COMPANY INC
        Beneficiary: JOHN DOE

        This petition has been approved. The approval is valid from 03/01/2024 to 02/28/2027.
        """

        # Test extraction with different prompts
        from models.validators import get_document_specific_prompt

        results = {}

        # Test I-797 prompt
        try:
            prompt = get_document_specific_prompt('I797')
            extracted = doc_processor.extract_with_llm(sample_text, prompt)
            results['I797'] = extracted
        except Exception as e:
            results['I797'] = {'error': str(e)}

        # Test I-797C prompt
        try:
            prompt = get_document_specific_prompt('I797C')
            extracted = doc_processor.extract_with_llm(sample_text, prompt)
            results['I797C'] = extracted
        except Exception as e:
            results['I797C'] = {'error': str(e)}

        html = f"""
        <h2>LLM Extraction Debug</h2>

        <h3>Sample Text:</h3>
        <pre style="background: #f5f5f5; padding: 10px;">
{sample_text}
        </pre>

        <h3>Extraction Results:</h3>
        """

        for doc_type, result in results.items():
            html += f"""
            <h4>{doc_type} Extraction:</h4>
            <pre style="background: #f8f8f8; padding: 10px;">
{json.dumps(result, indent=2)}
            </pre>
            """

        html += '<hr><a href="/">Back to Upload</a>'
        return html

    except Exception as e:
        return f"Debug error: {str(e)}"


@app.route('/debug_system_status')
def debug_system_status():
    """Comprehensive system status check"""
    try:
        status = {
            'timestamp': datetime.now().isoformat(),
            'components': {}
        }

        # Check database
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                status['components']['database'] = {'status': 'OK', 'message': 'Connected'}
        except Exception as e:
            status['components']['database'] = {'status': 'ERROR', 'message': str(e)}

        # Check Azure OpenAI
        try:
            messages = [{"role": "user", "content": "Test"}]
            response = doc_processor.throttled_llm(messages)
            status['components']['azure_openai'] = {'status': 'OK', 'message': 'Connected'}
        except Exception as e:
            status['components']['azure_openai'] = {'status': 'ERROR', 'message': str(e)}

        # Check Azure Form Recognizer
        try:
            # Just check if client is initialized
            if doc_processor.fr_client:
                status['components']['form_recognizer'] = {'status': 'OK', 'message': 'Client initialized'}
            else:
                status['components']['form_recognizer'] = {'status': 'ERROR', 'message': 'Client not initialized'}
        except Exception as e:
            status['components']['form_recognizer'] = {'status': 'ERROR', 'message': str(e)}

        # Check upload directory
        try:
            upload_dir = app.config['UPLOAD_FOLDER']
            if os.path.exists(upload_dir) and os.access(upload_dir, os.W_OK):
                file_count = len([f for f in os.listdir(upload_dir) if f.endswith('.pdf')])
                status['components']['upload_directory'] = {
                    'status': 'OK',
                    'message': f'Writable, contains {file_count} PDF files'
                }
            else:
                status['components']['upload_directory'] = {'status': 'ERROR', 'message': 'Not accessible'}
        except Exception as e:
            status['components']['upload_directory'] = {'status': 'ERROR', 'message': str(e)}

        # Generate HTML report
        html = f"""
        <h2>System Status Report</h2>
        <p><strong>Generated:</strong> {status['timestamp']}</p>

        <table border="1" style="border-collapse: collapse; width: 100%;">
            <tr>
                <th style="padding: 10px;">Component</th>
                <th style="padding: 10px;">Status</th>
                <th style="padding: 10px;">Message</th>
            </tr>
        """

        for component, info in status['components'].items():
            status_color = 'green' if info['status'] == 'OK' else 'red'
            html += f"""
            <tr>
                <td style="padding: 10px;">{component.replace('_', ' ').title()}</td>
                <td style="padding: 10px; color: {status_color}; font-weight: bold;">{info['status']}</td>
                <td style="padding: 10px;">{info['message']}</td>
            </tr>
            """

        html += """
        </table>

        <h3>Environment Variables:</h3>
        <ul>
        """

        # Check key environment variables (without exposing secrets)
        env_vars = [
            'AZURE_OPENAI_ENDPOINT',
            'AZURE_OPENAI_DEPLOYMENT',
            'FORM_RECOGNIZER_ENDPOINT',
            'SQL_SERVER',
            'SQL_DATABASE'
        ]

        for var in env_vars:
            value = os.getenv(var)
            if value:
                # Mask sensitive parts
                if 'key' in var.lower():
                    display_value = value[:8] + '...' if len(value) > 8 else '***'
                else:
                    display_value = value
                html += f"<li><strong>{var}:</strong> {display_value}</li>"
            else:
                html += f"<li><strong>{var}:</strong> <span style='color: red;'>NOT SET</span></li>"

        html += """
        </ul>
        <hr>
        <a href="/">Back to Upload</a>
        """

        return html

    except Exception as e:
        return f"System status error: {str(e)}"


@app.errorhandler(413)
def too_large(e):
    flash('File too large. Maximum size is 16MB.', 'error')
    return redirect(url_for('index'))


@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f'Server Error: {error}')
    flash('An internal error occurred', 'error')
    return redirect(url_for('index'))


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)