// Speech Studio client scripts. All server-supplied text is inserted with
// textContent (never innerHTML) so it cannot inject markup.

const SpeechStudio = (() => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  /** POST form data and return parsed JSON; throws Error with a readable message. */
  async function post(url, formData) {
    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrfToken },
      });
    } catch (err) {
      throw new Error('Could not reach the server. Is it still running?');
    }
    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      // fall through to the generic message below
    }
    if (!response.ok || !data || !data.success) {
      throw new Error((data && data.error) || `Request failed (HTTP ${response.status}).`);
    }
    return data;
  }

  function showSttError(message) {
    const box = document.getElementById('stt-error');
    if (!box) return;
    box.textContent = message;
    box.classList.toggle('d-none', !message);
  }

  function showSttResult(data) {
    showSttError('');
    document.getElementById('transcription-text').value = data.transcription;
    const player = document.getElementById('stt-audio-player');
    if (player) {
      player.src = data.audio_url;
      player.load();
    }
    document.getElementById('stt-download-source').href = data.audio_url;
    document.getElementById('stt-download-txt').href = data.txt_url;
    document.getElementById('stt-download-pdf').href = data.pdf_url;
    const container = document.getElementById('stt-result-container');
    container.classList.remove('d-none');
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function setBusy(button, textEl, spinnerEl, busy) {
    button.disabled = busy;
    textEl.classList.toggle('d-none', busy);
    spinnerEl.classList.toggle('d-none', !busy);
    button.setAttribute('aria-busy', busy ? 'true' : 'false');
  }

  return { post, showSttError, showSttResult, setBusy };
})();

document.addEventListener('DOMContentLoaded', () => {
  initCharCount();
  initTtsForm();
  initUpload();
  initCopyButton();
  initHistoryPage();
});

function initCharCount() {
  const textarea = document.getElementById('text');
  const counter = document.getElementById('char-count');
  if (!textarea || !counter) return;
  const sync = () => { counter.textContent = textarea.value.length; };
  textarea.addEventListener('input', sync);
  sync();
}

function initTtsForm() {
  const form = document.getElementById('tts-form');
  if (!form) return;
  const button = document.getElementById('btn-tts-submit');
  const btnText = document.getElementById('btn-text');
  const spinner = document.getElementById('btn-spinner');
  const errorBox = document.getElementById('text-error');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorBox.textContent = '';
    SpeechStudio.setBusy(button, btnText, spinner, true);
    try {
      const data = await SpeechStudio.post('/tts', new FormData(form));
      const player = document.getElementById('tts-audio-player');
      player.src = data.audio_url;
      player.load();
      document.getElementById('result-text-preview').textContent = data.text;
      document.getElementById('download-mp3').href = data.audio_url;
      document.getElementById('download-txt').href = data.txt_url;
      document.getElementById('download-pdf').href = data.pdf_url;
      const container = document.getElementById('tts-result-container');
      container.classList.remove('d-none');
      container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
      errorBox.textContent = err.message;
    } finally {
      SpeechStudio.setBusy(button, btnText, spinner, false);
    }
  });
}

function initUpload() {
  const dropZone = document.getElementById('file-drop-zone');
  const fileInput = document.getElementById('audio_file');
  const form = document.getElementById('stt-upload-form');
  if (!dropZone || !fileInput || !form) return;

  const details = document.getElementById('selected-file-details');
  const nameSpan = document.getElementById('file-name-span');
  const sizeSpan = document.getElementById('file-size-span');
  const languageSelect = document.getElementById('language');
  const hiddenLang = document.getElementById('upload-lang-hidden');

  function showSelection() {
    const file = fileInput.files && fileInput.files[0];
    if (!file) { details.classList.add('d-none'); return; }
    nameSpan.textContent = file.name;
    sizeSpan.textContent = `(${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
    details.classList.remove('d-none');
  }

  fileInput.addEventListener('change', showSelection);
  ['dragenter', 'dragover'].forEach((name) =>
    dropZone.addEventListener(name, (e) => { e.preventDefault(); dropZone.classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach((name) =>
    dropZone.addEventListener(name, (e) => { e.preventDefault(); dropZone.classList.remove('dragging'); }));
  dropZone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      showSelection();
    }
  });
  document.getElementById('btn-clear-file').addEventListener('click', () => {
    fileInput.value = '';
    showSelection();
  });

  languageSelect.addEventListener('change', () => { hiddenLang.value = languageSelect.value; });
  hiddenLang.value = languageSelect.value;

  const button = document.getElementById('btn-upload-submit');
  const btnText = document.getElementById('upload-btn-text');
  const spinner = document.getElementById('upload-btn-spinner');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    SpeechStudio.showSttError('');
    SpeechStudio.setBusy(button, btnText, spinner, true);
    try {
      SpeechStudio.showSttResult(await SpeechStudio.post('/stt', new FormData(form)));
    } catch (err) {
      SpeechStudio.showSttError(err.message);
    } finally {
      SpeechStudio.setBusy(button, btnText, spinner, false);
    }
  });
}

function initCopyButton() {
  const button = document.getElementById('btn-copy-clipboard');
  if (!button) return;
  button.addEventListener('click', async () => {
    const text = document.getElementById('transcription-text').value;
    if (!text) return;
    const icon = document.getElementById('copy-icon');
    const label = document.getElementById('copy-text');
    try {
      await navigator.clipboard.writeText(text);
      icon.className = 'fa-solid fa-check text-success me-1';
      label.textContent = 'Copied!';
    } catch (err) {
      label.textContent = 'Copy failed';
    }
    setTimeout(() => {
      icon.className = 'fa-regular fa-copy me-1';
      label.textContent = 'Copy Text';
    }, 2000);
  });
}

// ---- Dashboard / history: quick play, details modal, confirm dialogs ----

function initHistoryPage() {
  const player = document.getElementById('global-audio-player');
  let activeButton = null;
  const idleHtml = '<i class="fa-solid fa-play"></i> Play';

  function resetButton(button) {
    if (button) button.innerHTML = idleHtml;
  }

  document.querySelectorAll('[data-play-url]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!player) return;
      if (activeButton === button && !player.paused) {
        player.pause();
        resetButton(button);
        return;
      }
      resetButton(activeButton);
      activeButton = button;
      player.src = button.dataset.playUrl;
      button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Loading...';
      try {
        await player.play();
        button.innerHTML = '<i class="fa-solid fa-pause"></i> Pause';
      } catch (err) {
        button.innerHTML = '<i class="fa-solid fa-triangle-exclamation text-danger"></i> Failed';
        setTimeout(() => resetButton(button), 2000);
      }
    });
  });
  if (player) player.addEventListener('ended', () => resetButton(activeButton));

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  const modalEl = document.getElementById('historyDetailsModal');
  if (!modalEl) return;
  const modal = new bootstrap.Modal(modalEl);
  const copyButton = document.getElementById('modal-btn-copy');
  let copyValue = '';

  document.querySelectorAll('[data-view-details]').forEach((button) => {
    button.addEventListener('click', () => {
      const { op, lang, input, output } = button.dataset;
      const isTts = op === 'TTS';
      const badge = document.getElementById('modal-op-type');
      badge.textContent = op;
      badge.className = `badge badge-custom ${isTts ? 'badge-tts' : 'badge-stt'} mt-1`;
      document.getElementById('modal-lang').textContent = lang;
      document.getElementById('modal-input-label').textContent = isTts ? 'Original text' : 'Audio file';
      document.getElementById('modal-output-label').textContent = isTts ? 'Audio file' : 'Transcription';
      document.getElementById('modal-input-text').textContent = input;
      document.getElementById('modal-output-text').textContent = output;
      copyValue = isTts ? input : output;
      modal.show();
    });
  });

  copyButton.addEventListener('click', async () => {
    const original = copyButton.innerHTML;
    try {
      await navigator.clipboard.writeText(copyValue);
      copyButton.textContent = 'Copied!';
    } catch (err) {
      copyButton.textContent = 'Copy failed';
    }
    setTimeout(() => { copyButton.innerHTML = original; }, 1500);
  });
}
