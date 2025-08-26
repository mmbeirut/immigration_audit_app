# Immigration Document Audit System

A comprehensive Flask-based web application designed specifically for immigration attorneys to automate the auditing of client files from prior counsel. The system intelligently processes PDF files containing multiple immigration document types, extracts relevant data, validates information, and generates detailed audit reports.

## 🎯 Purpose

When onboarding new immigration clients, attorneys must thoroughly audit files from previous representation. This often involves manually reviewing hundreds of pages containing various document types (I-797 notices, labor certifications, passports, visa stamps, I-94 records, etc.). This system automates that process by:

- **Automatically detecting** different document types within multi-document PDFs
- **Extracting key data** using advanced OCR and AI techniques
- **Cross-referencing information** across documents for the same person
- **Identifying missing documents** and data inconsistencies
- **Generating comprehensive audit reports** with actionable recommendations

## 🚀 Key Features

### Multi-Document Processing
- **Intelligent Page Segmentation**: Automatically identifies where one document ends and another begins
- **Document Type Detection**: Recognizes 15+ immigration document types
- **Continuation Page Handling**: Properly groups multi-page documents

### Advanced Data Extraction
- **Multiple OCR Methods**: PyMuPDF → Azure Form Recognizer → EasyOCR fallback
- **AI-Powered Field Extraction**: Document-specific prompts for Azure OpenAI
- **Structured Data Output**: JSON-formatted results with confidence scoring

### Data Quality & Validation
- **Field Format Validation**: Receipt numbers, I-94 numbers, passport formats, dates
- **Cross-Document Consistency**: Flags name/DOB/citizenship discrepancies
- **Date Logic Validation**: Ensures logical date sequences (issue before expiry)
- **Completeness Analysis**: Identifies missing documents for case types

### Audit-Specific Intelligence
- **Person Cross-Referencing**: Links all documents to the correct individual
- **Case Timeline Generation**: Chronological progression of immigration events
- **Missing Document Detection**: Identifies typically required documents
- **Red Flag Identification**: Highlights potential issues requiring review

### Professional Reporting
- **Executive Summary**: High-level overview with quality scoring
- **Detailed Analysis**: Document-by-document breakdown with validation results
- **Actionable Recommendations**: Specific next steps for case preparation
- **Print-Ready Format**: Clean, professional audit reports

## 📋 Supported Document Types

### USCIS Forms
- **I-797** Notice of Action (Approvals, Denials, RFEs)
- **I-140** Immigrant Petition for Alien Worker
- **I-129** Nonimmigrant Worker Petition

### Department of Labor
- **PERM Labor Certification** (Form 9089)
- **Prevailing Wage Determination** (Form 9141)

### Entry/Travel Documents
- **I-94** Arrival/Departure Records (electronic and paper)
- **US Passports** (regular and diplomatic)
- **Foreign Passports** (all countries)
- **Visa Stamps** (immigrant and nonimmigrant)

### Supporting Documents
- **Birth Certificates**
- **Marriage Certificates**
- **Educational Documents** (diplomas, transcripts)
- **Employment Letters**

## 🛠 Technical Architecture

### Backend Framework
- **Flask 3.0** with modern Python patterns
- **Modular Design** (models, validators, processors)
- **Comprehensive Error Handling** with logging
- **Rate Limiting** for external API calls

### Database Design
- **SQL Server** with normalized schema
- **15 Tables** covering all document types and audit data
- **Views & Stored Procedures** for complex queries
- **Triggers** for data integrity and statistics

### AI Integration
- **Azure OpenAI** for intelligent field extraction
- **Azure Form Recognizer** for structured document analysis
- **Document-Specific Prompts** for higher accuracy
- **Confidence Scoring** for extracted data

### Frontend Experience
- **Bootstrap 5** responsive design
- **Progress Tracking** during processing
- **Interactive Results** with expandable sections
- **Print-Optimized** audit reports

## 📦 Installation

### Prerequisites
- **Python 3.9+** (tested on 3.9, 3.10, 3.11)
- **SQL Server 2019+** or SQL Server Express
- **Azure OpenAI** account with GPT-4 deployment
- **Azure Form Recognizer** account
- **Windows 10/11**, **macOS 12+**, or **Ubuntu 20.04+**

### System Dependencies

#### Windows
```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Poppler for PDF processing
# Download from: https://github.com/oschwartz10612/poppler-windows
# Add to PATH
```

#### macOS
```bash
# Install system dependencies
brew install poppler tesseract

# Install Python dependencies  
pip install -r requirements.txt
```

#### Ubuntu/Debian
```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install tesseract-ocr poppler-utils

# Install Python dependencies
pip install -r requirements.txt
```

### Database Setup

1. **Create Database**
   ```sql
   -- Connect to SQL Server as admin
   CREATE DATABASE ImmigrationAudit;
   USE ImmigrationAudit;
   ```

2. **Run Schema Script**
   ```bash
   # Using sqlcmd
   sqlcmd -S your-server -d ImmigrationAudit -i schema.sql

   # Or using SQL Server Management Studio
   # Open schema.sql and execute
   ```

### Application Setup

1. **Create Directory Structure**
   ```bash
   mkdir immigration_audit_app
   cd immigration_audit_app
   mkdir models templates static static/css static/js uploads logs
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment**
   ```bash
   # Copy template
   cp .env.example .env
   
   # Edit .env with your credentials
   ```

5. **Test Configuration**
   ```bash
   python -c "from models.database import DatabaseManager; db = DatabaseManager()"
   # Should print "Database connection successful"
   ```

### Environment Configuration

Create `.env` file with your specific settings:

```env
# Flask Configuration
FLASK_SECRET_KEY=your-secret-key-change-in-production-to-something-secure
FLASK_DEBUG=False
PORT=5000

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your-azure-openai-api-key
AZURE_OPENAI_DEPLOYMENT=your-gpt4-deployment-name
AZURE_OPENAI_API_VERSION=2024-02-01

# Azure Form Recognizer Configuration  
FORM_RECOGNIZER_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
FORM_RECOGNIZER_KEY=your-form-recognizer-key

# SQL Server Configuration
SQL_DRIVER={ODBC Driver 17 for SQL Server}
SQL_SERVER=your-server-name-or-ip
SQL_DATABASE=ImmigrationAudit
MAX_CONTENT_LENGTH=52428800  # 50MB upload limit
```

> **Note:** Update your production web server or proxy (e.g., Nginx `client_max_body_size`) to allow uploads up to the configured limit.

## 🚀 Usage Guide

### Starting the Application

#### Development Mode
```bash
python app.py
# Access at http://localhost:5000
```

#### Production Mode
```bash
# Using Gunicorn (recommended for production)
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Using Waitress (Windows-friendly)
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

### Processing Workflows

#### Single Document Processing
1. Select **"Single Document Type"** mode
2. Choose document type or use **"Auto-detect"**
3. Upload PDF file (max 50MB by default)
4. Enable validation options
5. Click **"Process Document"**
6. Review extracted data and validation results

#### Multi-Document File Audit (Recommended)
1. Select **"Multi-Document Audit"** mode (default)
2. Configure audit options:
   - ✅ **Check case completeness** - Identifies missing documents
   - ✅ **Cross-reference person data** - Links documents to individuals
   - ✅ **Timeline analysis** - Creates chronological case progression
3. Upload multi-document PDF file
4. Monitor processing progress
5. Review comprehensive audit report

### Understanding Results

#### Processing Summary
- **Total Pages**: Number of pages processed
- **People Identified**: Unique individuals found
- **Documents Found**: Number of document segments identified
- **Red Flags**: Data quality issues requiring attention

#### Person Records
Each identified person shows:
- **Name variations** found across documents
- **Document types** associated with them
- **Timeline** of immigration events
- **Data inconsistencies** flagged for review

#### Document Analysis
For each document:
- **Confidence score** for extraction accuracy
- **Valid/Invalid fields** with specific validation results
- **Key extracted data** in structured format
- **Processing notes** including any issues

#### Audit Recommendations
- **Missing documents** typically required for case type
- **Data inconsistencies** requiring clarification
- **Timeline gaps** in case progression
- **Validation issues** to resolve

## 🔧 Configuration & Customization

### Adding New Document Types

1. **Update Document Detection** (`models/document_processor.py`):
   ```python
   def detect_document_types_on_page(self, page_text: str):
       # Add detection logic for new document type
       if 'new_document_indicator' in text_lower:
           detections.append(('NEW_DOC_TYPE', 0.85))
   ```

2. **Create Extraction Prompt** (`models/validators.py`):
   ```python
   prompts['NEW_DOC_TYPE'] = """
   Extract fields from new document type and return as JSON:
   {
       "field1": "string",
       "field2": "YYYY-MM-DD"
   }
   """
   ```

3. **Add Database Table** (modify `schema.sql`):
   ```sql
   CREATE TABLE new_doc_types (
       id INT IDENTITY(1,1) PRIMARY KEY,
       person_id NVARCHAR(20) NOT NULL,
       -- Add specific fields
       FOREIGN KEY (person_id) REFERENCES persons(person_id)
   );
   ```

## 📊 Monitoring & Maintenance

### Database Health Check
```sql
-- View processing statistics
SELECT 
    COUNT(*) as total_sessions,
    AVG(processing_duration_seconds) as avg_duration
FROM processing_sessions
WHERE processed_at >= DATEADD(day, -30, GETDATE());
```

### Log Analysis
```bash
# View recent errors
tail -f logs/app.log | grep ERROR

# Processing performance
grep "Processing duration" logs/app.log | tail -20
```

## 🛡 Security Considerations

### Production Deployment
- Use strong, unique secret key
- Disable debug in production
- Enable HTTPS
- Implement proper access controls
- Regular security updates

### Data Privacy
- Automatic file cleanup after processing
- Data minimization practices
- Access logging
- Encryption for sensitive data

## 🔍 Troubleshooting

### Common Issues

#### Database Connection Problems
```bash
# Test SQL Server connectivity
sqlcmd -S your-server -E -Q "SELECT @@VERSION"

# Check ODBC drivers
odbcinst -q -d
```

#### Azure Service Errors
- Verify API keys and endpoints
- Check service quotas and billing
- Monitor rate limits

#### OCR Quality Issues
- Try different OCR methods
- Ensure PDFs are not password-protected
- Check document quality and resolution

## 📈 Performance Tips

- Use SSD storage for uploads directory
- Monitor Azure OpenAI quotas
- Implement Redis caching for repeated queries
- Regular database maintenance and index optimization

## 📄 License & Legal

This application is provided for immigration law practice automation. Ensure compliance with:
- Attorney-client privilege requirements
- Data retention policies
- Professional responsibility rules
- Local jurisdiction requirements

## 📞 Support

For technical issues:
1. Check troubleshooting section
2. Review application logs in `logs/` directory
3. Verify environment variables are set correctly
4. Test with simple, single-document PDFs first

---

**Ready to revolutionize your immigration file audits!** 🚀

*This system automates the tedious process of manual file review, allowing attorneys to focus on legal analysis rather than data extraction.*