// static/js/main.js — clean, corrected build
// Notes:
// - Do NOT disable inputs other than the submit button. Disabled fields are not submitted.
// - Works with form id "uploadForm" (also tolerates "upload-form").
// - Progress container id can be "progressContainer" or "progress-container".

document.addEventListener('DOMContentLoaded', () => {
  console.log('Immigration Audit System JS loaded');

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const any = (...ids) => ids.map((i) => $(i)).find(Boolean) || null;

  const uploadForm        = any('uploadForm', 'upload-form');
  const fileInput         = $('file');
  const multiDocRadio     = $('multiDoc');
  const singleDocRadio    = $('singleDoc');
  const multiDocOptions   = $('multiDocOptions');
  const singleDocOptions  = $('singleDocOptions');
  const progressContainer = any('progressContainer', 'progress-container');
  const progressBar       = any('progressBar', 'progress-bar');

  // ---------- mode toggle (single vs multi) ----------
  function toggleOptions() {
    const single = !!(singleDocRadio && singleDocRadio.checked);
    if (multiDocOptions)  multiDocOptions.style.display  = single ? 'none'  : 'block';
    if (singleDocOptions) singleDocOptions.style.display = single ? 'block' : 'none';
    console.log('Mode:', single ? 'single_document' : 'multi_document');
  }
  if (multiDocRadio)  multiDocRadio.addEventListener('change', toggleOptions);
  if (singleDocRadio) singleDocRadio.addEventListener('change', toggleOptions);
  toggleOptions();

  // ---------- file selection validation ----------
  function clearFileValidation() {
    document.querySelectorAll('.file-success-message').forEach(n => n.remove());
  }
  function showFileSuccess(file) {
    const fileSize = (file.size / 1024 / 1024).toFixed(2);
    const msg = document.createElement('div');
    msg.className = 'file-success-message text-success mt-2';
    msg.textContent = `Selected: ${file.name} (${fileSize} MB)`;
    const mount = document.getElementById('fileSection') || fileInput?.parentElement;
    mount?.appendChild(msg);
  }
  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      clearFileValidation();
      if (!file) return;

      const name = (file.name || '').toLowerCase();
      if (!name.endsWith('.pdf')) {
        alert('Please select a PDF file.');
        fileInput.value = '';
        return;
      }
      if (file.size > 16 * 1024 * 1024) {
        alert('File size must be less than 16MB.');
        fileInput.value = '';
        return;
      }
      showFileSuccess(file);
    });
  }

  // ---------- submit handling ----------
  function setSubmittingState() {
    // Only disable the submit button so ALL fields (file, radios, selects) are posted
    const submitBtn = uploadForm?.querySelector('button[type="submit"], input[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      const isBtn = submitBtn.tagName === 'BUTTON';
      if (isBtn) submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing…';
      submitBtn.classList?.remove('btn-primary');
      submitBtn.classList?.add('btn-secondary');
    }
    // Belt & suspenders: ensure file input is enabled
    if (fileInput) fileInput.disabled = false;
  }

  function startProgressAnimation() {
    if (!progressBar) return;
    let width = 10;
    progressBar.style.width = width + '%';
    progressBar.setAttribute('aria-valuenow', width);
    const id = setInterval(() => {
      if (width >= 90) { clearInterval(id); return; }
      width += 2;
      progressBar.style.width = width + '%';
      progressBar.setAttribute('aria-valuenow', width);
    }, 150);
  }

  if (!uploadForm) {
    console.error('Upload form not found (expected id "uploadForm" or "upload-form").');
    return;
  }

  uploadForm.addEventListener('submit', (e) => {
    // Basic file checks
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      e.preventDefault();
      alert('Please select a PDF file before submitting.');
      return;
    }
    const file = fileInput.files[0];
    const name = (file.name || '').toLowerCase();
    if (!name.endsWith('.pdf')) {
      e.preventDefault();
      alert('Please select a PDF file.');
      return;
    }
    if (file.size > 16 * 1024 * 1024) {
      e.preventDefault();
      alert('File size must be less than 16MB.');
      return;
    }

    // Log outgoing form fields (helps confirm processing_mode & document_type are sent)
    try {
      const fd = new FormData(uploadForm);
      const pairs = [];
      for (const [k, v] of fd.entries()) pairs.push(`${k}=${v}`);
      console.log('Submitting with fields:', pairs.join(' | '));
      console.log('file.disabled on submit =', fileInput.disabled); // should be false
    } catch (err) {
      console.warn('FormData log error:', err);
    }

    // Visual feedback
    setSubmittingState();
    if (progressContainer) {
      progressContainer.style.display = 'block';
      startProgressAnimation();
    }
    // allow normal POST (no preventDefault)
  });

  // ---------- optional niceties ----------
  // Collapse toggles (safe no-op if no such elements)
  document.querySelectorAll('[data-bs-toggle="collapse"]').forEach(btn => {
    btn.addEventListener('click', function() {
      const target = document.querySelector(this.getAttribute('data-bs-target'));
      if (!target) return;
      const icon = this.querySelector('i');
      setTimeout(() => {
        if (icon) {
          icon.className = target.classList.contains('show')
            ? 'fas fa-chevron-down'
            : 'fas fa-chevron-right';
        }
      }, 250);
    });
  });

  // Syntax highlight (safe if highlight.js present)
  if (window.hljs) {
    document.querySelectorAll('pre code').forEach(block => {
      try { window.hljs.highlightElement(block); } catch {}
    });
  }

  console.log('Immigration Audit System initialization complete');
});
