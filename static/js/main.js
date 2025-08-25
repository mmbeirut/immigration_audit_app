// static/main.js — clean build
document.addEventListener('DOMContentLoaded', () => {
  console.log('Immigration Audit System JS loaded');

  // ===== Processing Mode Toggle =====
  const multiDocRadio = document.getElementById('multiDoc');
  const singleDocRadio = document.getElementById('singleDoc');
  const multiDocOptions = document.getElementById('multiDocOptions');
  const singleDocOptions = document.getElementById('singleDocOptions');

  function toggleOptions() {
    const single = singleDocRadio && singleDocRadio.checked;
    if (multiDocOptions) multiDocOptions.style.display = single ? 'none' : 'block';
    if (singleDocOptions) singleDocOptions.style.display = single ? 'block' : 'none';
  }
  if (multiDocRadio && singleDocRadio) {
    multiDocRadio.addEventListener('change', toggleOptions);
    singleDocRadio.addEventListener('change', toggleOptions);
    toggleOptions();
  }

  // ===== File Input & Validation =====
  const uploadForm = document.getElementById('uploadForm');
  const fileInput  = document.getElementById('file');

  function clearFileValidation() {
    document.querySelectorAll('.file-success-message').forEach(n => n.remove());
  }

  function showFileSuccess(file) {
    const fileSize = (file.size / 1024 / 1024).toFixed(2);
    const msg = document.createElement('div');
    msg.className = 'file-success-message alert alert-success mt-2';
    msg.innerHTML = `<i class="fas fa-check-circle"></i>
                     <strong>${file.name}</strong> (${fileSize} MB) - Ready to process`;
    const fileSection = document.getElementById('fileSection');
    if (fileSection) fileSection.appendChild(msg);
  }

  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      clearFileValidation();
      if (!file) return;

      const name = (file.name || '').toLowerCase();
      if (!name.endsWith('.pdf')) { alert('Please select a PDF file.'); fileInput.value = ''; return; }
      if (file.size > 16 * 1024 * 1024) { alert('File size must be less than 16MB.'); fileInput.value = ''; return; }

      showFileSuccess(file);
    });
  }

  // ===== Submit Handling =====
  function showProcessingState() {
    const submitBtn = uploadForm.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing…';
      submitBtn.classList.remove('btn-primary');
      submitBtn.classList.add('btn-secondary');
    }

    // Disable everything EXCEPT the file input and the submit
    uploadForm.querySelectorAll('input, select, textarea, button').forEach(el => {
      const isSubmit = (el.tagName === 'BUTTON' && el.type === 'submit') || (el.tagName === 'INPUT' && el.type === 'submit');
      const isFile   = (el === fileInput) || (el.tagName === 'INPUT' && el.type === 'file');
      if (!isSubmit && !isFile) el.disabled = true;
    });

    // belt & suspenders — keep file enabled
    if (fileInput) fileInput.disabled = false;
    console.log('Processing state applied. file.disabled =', fileInput ? fileInput.disabled : '(no file input)');
  }

  function startProgressAnimation() {
    const progressBar = document.getElementById('progressBar');
    if (!progressBar) return;
    let progress = 0;
    const interval = setInterval(() => {
      progress += Math.random() * 15;
      if (progress > 90) progress = 90;
      progressBar.style.width = progress + '%';
      progressBar.setAttribute('aria-valuenow', progress);
    }, 500);
    setTimeout(() => clearInterval(interval), 10000);
  }

  if (uploadForm) {
    uploadForm.addEventListener('submit', (e) => {
      // Require a file
      if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        e.preventDefault();
        alert('Please select a file to upload.');
        return;
      }
      const file = fileInput.files[0];
      const name = (file.name || '').toLowerCase();
      if (!name.endsWith('.pdf')) { e.preventDefault(); alert('Please select a PDF file.'); return; }
      if (file.size > 16 * 1024 * 1024) { e.preventDefault(); alert('File size must be less than 16MB.'); return; }

      showProcessingState();
      const progressContainer = document.getElementById('progressContainer');
      if (progressContainer) { progressContainer.style.display = 'block'; startProgressAnimation(); }
      // allow normal submit
    });
  }

  // Small dependency: timeline disabled unless cross-ref checked
  const crossRef = document.getElementById('crossRef');
  const timeline = document.getElementById('timeline');
  if (crossRef && timeline) {
    crossRef.addEventListener('change', function () {
      timeline.disabled = !this.checked;
      if (!this.checked) timeline.checked = false;
    });
  }

  console.log('Immigration Audit System initialization complete');
});
