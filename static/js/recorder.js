// Speech Studio browser voice recorder (MediaRecorder API).
// Depends on SpeechStudio from main.js.

document.addEventListener('DOMContentLoaded', () => {
  const MAX_SECONDS = 180;
  const recordBtn = document.getElementById('record-btn');
  if (!recordBtn) return;

  const icon = document.getElementById('record-btn-icon');
  const timerLabel = document.getElementById('record-timer');
  const statusLabel = document.getElementById('record-status');
  const wave = document.getElementById('wave-visualiser');
  const cancelBtn = document.getElementById('btn-cancel-recording');
  const controlsRow = document.getElementById('record-controls-row');
  const languageSelect = document.getElementById('language');

  let recorder = null;
  let stream = null;
  let chunks = [];
  let seconds = 0;
  let timer = null;

  const MIME_CANDIDATES = ['audio/webm', 'audio/ogg', 'audio/mp4'];

  function setIdle(message) {
    recordBtn.classList.remove('recording');
    recordBtn.disabled = false;
    icon.className = 'fa-solid fa-microphone';
    timerLabel.textContent = '00:00';
    statusLabel.textContent = message;
    wave.classList.remove('active');
    controlsRow.style.display = 'none';
  }

  function releaseMicrophone() {
    clearInterval(timer);
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  async function startRecording() {
    SpeechStudio.showSttError('');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      SpeechStudio.showSttError('Recording is not supported in this browser. Use the file upload instead.');
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      SpeechStudio.showSttError('Microphone access was denied or no microphone was found. Check your browser permissions.');
      return;
    }

    const mimeType = MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    chunks = [];
    recorder.ondataavailable = (event) => { if (event.data && event.data.size > 0) chunks.push(event.data); };
    recorder.onstop = upload;
    recorder.start();

    seconds = 0;
    recordBtn.classList.add('recording');
    icon.className = 'fa-solid fa-stop';
    statusLabel.textContent = 'Recording... click again to stop.';
    wave.classList.add('active');
    controlsRow.style.display = 'block';
    timerLabel.textContent = '00:00';
    timer = setInterval(() => {
      seconds += 1;
      timerLabel.textContent =
        `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
      if (seconds >= MAX_SECONDS) stopRecording();
    }, 1000);
  }

  function stopRecording() {
    if (!recorder || recorder.state === 'inactive') return;
    recordBtn.classList.remove('recording');
    recordBtn.disabled = true;
    icon.className = 'fa-solid fa-circle-notch fa-spin';
    statusLabel.textContent = 'Transcribing... please wait.';
    wave.classList.remove('active');
    controlsRow.style.display = 'none';
    releaseMicrophone();
    recorder.stop();
  }

  function cancelRecording() {
    if (!recorder || recorder.state === 'inactive') return;
    recorder.onstop = null;
    recorder.stop();
    releaseMicrophone();
    setIdle('Recording cancelled.');
  }

  async function upload() {
    const type = recorder.mimeType || 'audio/webm';
    const blob = new Blob(chunks, { type });
    if (blob.size === 0) {
      setIdle('Nothing was recorded.');
      SpeechStudio.showSttError('The recording was empty. Please try again.');
      return;
    }
    const extension = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
    const formData = new FormData();
    formData.append('audio_data', blob, `recording.${extension}`);
    formData.append('language', languageSelect.value);
    try {
      SpeechStudio.showSttResult(await SpeechStudio.post('/record', formData));
      setIdle('Click to record again.');
    } catch (err) {
      setIdle('Something went wrong. Click to try again.');
      SpeechStudio.showSttError(err.message);
    }
  }

  recordBtn.addEventListener('click', () => (recorder && recorder.state === 'recording' ? stopRecording() : startRecording()));
  if (cancelBtn) cancelBtn.addEventListener('click', cancelRecording);
  window.addEventListener('beforeunload', releaseMicrophone);
});
