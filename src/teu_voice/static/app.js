const elements = {
  script: document.querySelector("#script"),
  charCount: document.querySelector("#char-count"),
  tagSuggestions: document.querySelector("#tag-suggestions"),
  quickTags: document.querySelector("#quick-tags"),
  tagLibrary: document.querySelector("#tag-library"),
  tagCountLabel: document.querySelector("#tag-count-label"),
  speed: document.querySelector("#speed"),
  speedLabel: document.querySelector("#speed-label"),
  referenceMeta: document.querySelector("#reference-meta"),
  referencePlayer: document.querySelector("#reference-player"),
  referenceFile: document.querySelector("#reference-file"),
  fileLabel: document.querySelector("#file-label"),
  uploadHint: document.querySelector("#upload-hint"),
  microphoneButton: document.querySelector("#microphone-button"),
  microphoneStatus: document.querySelector("#microphone-status"),
  microphonePlayer: document.querySelector("#microphone-player"),
  builtinVoice: document.querySelector("#builtin-voice"),
  denoise: document.querySelector("#denoise"),
  denoiseRow: document.querySelector("#denoise-row"),
  styleTransfer: document.querySelector("#style-transfer"),
  styleTransferRow: document.querySelector("#style-transfer-row"),
  consent: document.querySelector("#consent"),
  consentRow: document.querySelector("#consent-row"),
  formError: document.querySelector("#form-error"),
  previewButton: document.querySelector("#preview-button"),
  generateButton: document.querySelector("#generate-button"),
  generateLabel: document.querySelector("#generate-label"),
  engineBadge: document.querySelector("#engine-badge"),
  resultPanel: document.querySelector("#result-panel"),
  emptyResult: document.querySelector("#empty-result"),
  workingResult: document.querySelector("#working-result"),
  previewResult: document.querySelector("#preview-result"),
  doneResult: document.querySelector("#done-result"),
  jobStage: document.querySelector("#job-stage"),
  previewTags: document.querySelector("#preview-tags"),
  performanceScript: document.querySelector("#performance-script"),
  previewEffects: document.querySelector("#preview-effects"),
  previewWarnings: document.querySelector("#preview-warnings"),
  resultPlayer: document.querySelector("#result-player"),
  trackTitle: document.querySelector("#track-title"),
  trackMeta: document.querySelector("#track-meta"),
  downloadLink: document.querySelector("#download-link"),
  closePreview: document.querySelector("#close-preview"),
  showScript: document.querySelector("#show-script"),
};

const suppliedAccessKey = new URLSearchParams(window.location.search).get("access_key") || "";

const state = {
  config: null,
  configLoaded: false,
  source: "provided",
  tagById: new Map(),
  suggestions: [],
  suggestionIndex: 0,
  suggestionRange: null,
  composing: false,
  completedPreview: null,
  pendingJob: null,
  polling: null,
  pollFailures: 0,
  previewSequence: 0,
  jobInFlight: false,
  hasCompletedResult: false,
  microphoneFile: null,
  microphoneCapture: null,
  microphoneUrl: null,
  accessKey: suppliedAccessKey,
};

function showError(message) {
  elements.formError.textContent = message;
  elements.formError.hidden = false;
}

function clearError() {
  elements.formError.hidden = true;
  elements.formError.textContent = "";
}

function formatApiDetail(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return "";
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== "body").join(" → ")
          : "";
        return `${location ? `${location}: ` : ""}${item.msg || "Dữ liệu không hợp lệ."}`;
      })
      .filter(Boolean);
    if (messages.length) return messages.join(" · ");
  }
  if (detail && typeof detail === "object") return detail.message || fallback;
  return fallback;
}

async function jsonRequest(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.accessKey) headers.set("X-Teu-Access-Key", state.accessKey);
  const response = await fetch(url, { ...options, headers });
  let payload = {};
  try {
    payload = await response.json();
  } catch (_) {
    // The fallback below is clearer than a JSON parse error.
  }
  if (!response.ok) {
    const error = new Error(formatApiDetail(payload.detail, `Yêu cầu thất bại (${response.status}).`));
    error.status = response.status;
    throw error;
  }
  return payload;
}

function authorizedUrl(url) {
  if (!state.accessKey) return url;
  const target = new URL(url, window.location.origin);
  target.searchParams.set("access_key", state.accessKey);
  return `${target.pathname}${target.search}`;
}

function foldSearch(value) {
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("vi")
    .replace(/[\s_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function updateCharCount() {
  const max = state.config?.limits?.max_text_chars || 2000;
  elements.charCount.textContent = `${elements.script.value.length.toLocaleString("vi-VN")} / ${max.toLocaleString("vi-VN")}`;
}

function formatSpeed(value) {
  return new Intl.NumberFormat("vi-VN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function updateSpeedLabel() {
  const value = Number(elements.speed.value);
  const mood = value < 0.93 ? "Chậm" : value > 1.07 ? "Nhanh" : "Bình thường";
  elements.speedLabel.textContent = `${formatSpeed(value)}× · ${mood}`;
}

function syncControls() {
  const engineReady = Boolean(state.configLoaded && state.config?.engine?.available);
  elements.generateButton.disabled = !engineReady || state.jobInFlight;
  elements.previewButton.disabled = !state.configLoaded || state.jobInFlight;
  elements.generateLabel.textContent = state.jobInFlight ? "Đang tạo giọng…" : "Tạo giọng nói";
  elements.microphoneButton.disabled = state.jobInFlight;
}

function makeTagButton(tag, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.dataset.tagId = tag.id;
  button.title = `${tag.description} · ${tag.support_label}`;

  const icon = document.createElement("b");
  icon.textContent = tag.icon;
  const copy = document.createElement("span");
  const name = document.createElement("strong");
  name.textContent = tag.name;
  const mention = document.createElement("small");
  mention.textContent = tag.mention;
  copy.append(name, mention);
  const support = document.createElement("i");
  support.className = `tag-support ${tag.fidelity}`;
  support.textContent = tag.support_label;
  button.append(icon, copy, support);
  button.addEventListener("click", () => insertTag(tag));
  return button;
}

function renderTagCatalog(tags) {
  state.tagById = new Map(tags.map((tag) => [tag.id, tag]));
  elements.tagCountLabel.textContent = `${tags.length} tag · gõ @ để tìm`;
  elements.quickTags.replaceChildren();
  for (const tag of tags.filter((item) => item.popular).slice(0, 10)) {
    elements.quickTags.append(makeTagButton(tag, "quick-tag"));
  }

  const groups = new Map();
  for (const tag of tags) {
    if (!groups.has(tag.category)) groups.set(tag.category, []);
    groups.get(tag.category).push(tag);
  }
  elements.tagLibrary.replaceChildren();
  for (const [category, categoryTags] of groups) {
    const group = document.createElement("section");
    group.className = "tag-group";
    const heading = document.createElement("h3");
    heading.textContent = category;
    const grid = document.createElement("div");
    grid.className = "tag-group-grid";
    for (const tag of categoryTags) grid.append(makeTagButton(tag, "library-tag"));
    group.append(heading, grid);
    elements.tagLibrary.append(group);
  }
}

function mentionAtCaret() {
  const caret = elements.script.selectionStart;
  const beforeCaret = elements.script.value.slice(0, caret);
  const start = beforeCaret.lastIndexOf("@");
  if (start < 0) return null;
  const previous = beforeCaret[start - 1] || "";
  if (previous && /[\p{L}\p{N}_@]/u.test(previous)) return null;
  const raw = beforeCaret.slice(start + 1);
  if (raw.length > 48 || /[\n\r.,!?;:()[\]{}<>/\\"'`]/u.test(raw)) return null;
  if (!/^[\p{L}\p{M}\p{N}\s_-]*$/u.test(raw)) return null;
  return { start, end: caret, query: raw };
}

function scoreTag(tag, query) {
  const folded = foldSearch(query);
  if (!folded) return tag.popular ? 0 : 4;
  const fields = [tag.token, tag.name, tag.id, ...tag.aliases].map(foldSearch);
  if (fields.some((field) => field === folded)) return 0;
  if (fields.some((field) => field.startsWith(folded))) return 1;
  if (fields.some((field) => field.split("_").some((word) => word.startsWith(folded)))) return 2;
  if (fields.some((field) => field.includes(folded))) return 3;
  return Number.POSITIVE_INFINITY;
}

function closeSuggestions() {
  state.suggestions = [];
  state.suggestionRange = null;
  state.suggestionIndex = 0;
  elements.tagSuggestions.hidden = true;
  elements.script.setAttribute("aria-expanded", "false");
  elements.script.removeAttribute("aria-activedescendant");
}

function setActiveSuggestion(index) {
  if (!state.suggestions.length) return;
  state.suggestionIndex = (index + state.suggestions.length) % state.suggestions.length;
  const options = elements.tagSuggestions.querySelectorAll('[role="option"]');
  options.forEach((option, optionIndex) => {
    const active = optionIndex === state.suggestionIndex;
    option.classList.toggle("active", active);
    option.setAttribute("aria-selected", String(active));
    if (active) {
      elements.script.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    }
  });
}

function renderSuggestions() {
  elements.tagSuggestions.replaceChildren();
  if (!state.suggestions.length) {
    const empty = document.createElement("div");
    empty.className = "suggestion-empty";
    empty.textContent = "Chưa có tag khớp · thử từ khác hoặc mở thư viện bên dưới";
    elements.tagSuggestions.append(empty);
  } else {
    for (const [index, tag] of state.suggestions.entries()) {
      const option = makeTagButton(tag, "tag-suggestion");
      option.id = `tag-option-${tag.id}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      option.addEventListener("pointerdown", (event) => event.preventDefault());
      option.addEventListener("mouseenter", () => setActiveSuggestion(index));
      elements.tagSuggestions.append(option);
    }
  }
  elements.tagSuggestions.hidden = false;
  elements.script.setAttribute("aria-expanded", "true");
  setActiveSuggestion(0);
}

function updateSuggestions() {
  if (state.composing || !state.configLoaded) return;
  const mention = mentionAtCaret();
  if (!mention) {
    closeSuggestions();
    return;
  }
  const scored = state.config.emotion_tags
    .map((tag) => ({ tag, score: scoreTag(tag, mention.query) }))
    .filter((item) => Number.isFinite(item.score))
    .sort((left, right) => left.score - right.score || Number(right.tag.popular) - Number(left.tag.popular) || left.tag.name.localeCompare(right.tag.name, "vi"));
  state.suggestionRange = mention;
  state.suggestions = scored.slice(0, 8).map((item) => item.tag);
  state.suggestionIndex = 0;
  renderSuggestions();
}

function insertTag(tag, replacementRange = state.suggestionRange) {
  const start = replacementRange?.start ?? elements.script.selectionStart;
  const end = replacementRange?.end ?? elements.script.selectionEnd;
  const value = elements.script.value;
  const needsLeadingSpace = start > 0 && !/[\s([{—–-]$/.test(value.slice(0, start));
  const needsTrailingSpace = end >= value.length || !/^\s/.test(value.slice(end));
  const insertion = `${needsLeadingSpace ? " " : ""}${tag.mention}${needsTrailingSpace ? " " : ""}`;
  elements.script.setRangeText(insertion, start, end, "end");
  closeSuggestions();
  updateCharCount();
  elements.script.focus();
  elements.script.dispatchEvent(new Event("change", { bubbles: true }));
}

function handleScriptKeydown(event) {
  if (event.isComposing || state.composing || elements.tagSuggestions.hidden) return;
  if (event.key === "ArrowDown" && state.suggestions.length) {
    event.preventDefault();
    setActiveSuggestion(state.suggestionIndex + 1);
  } else if (event.key === "ArrowUp" && state.suggestions.length) {
    event.preventDefault();
    setActiveSuggestion(state.suggestionIndex - 1);
  } else if ((event.key === "Enter" || event.key === "Tab") && state.suggestions.length) {
    event.preventDefault();
    insertTag(state.suggestions[state.suggestionIndex]);
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeSuggestions();
  }
}

function updateSource(source, { resetConsent = true } = {}) {
  const changed = state.source !== source;
  if (changed && source !== "microphone" && state.microphoneCapture) discardMicrophoneCapture();
  state.source = source;
  for (const node of document.querySelectorAll(".voice-source")) node.classList.remove("active");
  document.querySelector(`#${source}-source`)?.classList.add("active");
  const isClone = source !== "builtin";
  elements.consentRow.hidden = !isClone;
  elements.denoiseRow.hidden = !isClone;
  elements.denoise.checked = false;
  if (resetConsent && changed) elements.consent.checked = false;
}

function encodeMonoWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function discardMicrophoneCapture() {
  const capture = state.microphoneCapture;
  if (capture) {
    clearInterval(capture.timer);
    capture.processor.disconnect();
    capture.silentGain.disconnect();
    capture.source.disconnect();
    capture.stream.getTracks().forEach((track) => track.stop());
    capture.context.close();
  }
  state.microphoneCapture = null;
  elements.microphoneButton.textContent = "Bắt đầu thu";
}

function resetMicrophoneSample(message) {
  state.microphoneFile = null;
  if (state.microphoneUrl) URL.revokeObjectURL(state.microphoneUrl);
  state.microphoneUrl = null;
  elements.microphonePlayer.pause();
  elements.microphonePlayer.removeAttribute("src");
  elements.microphonePlayer.hidden = true;
  elements.microphoneStatus.textContent = message;
}

function finishMicrophoneCapture() {
  const capture = state.microphoneCapture;
  if (!capture) return;
  discardMicrophoneCapture();
  const sampleCount = capture.chunks.reduce((total, chunk) => total + chunk.length, 0);
  const collectedSamples = new Float32Array(sampleCount);
  let offset = 0;
  let peak = 0;
  for (const chunk of capture.chunks) {
    collectedSamples.set(chunk, offset);
    offset += chunk.length;
    for (const sample of chunk) peak = Math.max(peak, Math.abs(sample));
  }
  // Leave a safety margin below the backend's 8-second clone limit: a browser
  // callback can arrive a fraction of a second after the visible timer.
  const maximumSamples = Math.floor(capture.sampleRate * 7.8);
  const samples = collectedSamples.length > maximumSamples
    ? collectedSamples.slice(0, maximumSamples)
    : collectedSamples;
  const duration = samples.length / capture.sampleRate;
  if (duration < 5.8) {
    resetMicrophoneSample("Mẫu còn ngắn; hãy thu liền mạch ít nhất 6 giây để clone giữ màu giọng tốt hơn.");
    return;
  }
  if (peak >= 0.985) {
    resetMicrophoneSample("Mic đã bị quá âm lượng. Hãy hạ gain mic rồi thu lại để tránh méo màu giọng.");
    return;
  }
  const blob = encodeMonoWav(samples, capture.sampleRate);
  state.microphoneFile = new File([blob], "microphone-reference.wav", { type: "audio/wav" });
  if (state.microphoneUrl) URL.revokeObjectURL(state.microphoneUrl);
  state.microphoneUrl = URL.createObjectURL(blob);
  elements.microphonePlayer.src = state.microphoneUrl;
  elements.microphonePlayer.hidden = false;
  elements.microphoneStatus.textContent = `Đã thu ${duration.toFixed(1)} giây · không clipping · sẵn sàng clone đúng màu mic này.`;
  elements.consent.checked = false;
}

async function toggleMicrophoneCapture() {
  clearError();
  if (state.microphoneCapture) {
    finishMicrophoneCapture();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    showError("Trình duyệt này chưa hỗ trợ thu micro. Hãy tải WAV 6–8 giây thay thế.");
    return;
  }
  try {
    resetMicrophoneSample("Đang xin quyền dùng micro…");
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: { ideal: 1 },
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    const context = new AudioContext();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    const capture = {
      stream,
      context,
      source,
      processor,
      silentGain,
      sampleRate: context.sampleRate,
      chunks: [],
      startedAt: performance.now(),
      timer: null,
    };
    processor.onaudioprocess = (event) => {
      capture.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    };
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    capture.timer = setInterval(() => {
      const seconds = (performance.now() - capture.startedAt) / 1000;
      elements.microphoneStatus.textContent = `Đang thu ${seconds.toFixed(1)} / 8,0 giây · hãy đọc tự nhiên, liền mạch.`;
      if (seconds >= 8) finishMicrophoneCapture();
    }, 100);
    state.microphoneCapture = capture;
    elements.microphoneButton.textContent = "Dừng & dùng mẫu";
  } catch (error) {
    resetMicrophoneSample("Không thể dùng micro.");
    showError(error.name === "NotAllowedError" ? "Bạn cần cho phép trình duyệt dùng micro để thu mẫu giọng." : error.message);
  }
}

function showResult(which) {
  elements.emptyResult.hidden = which !== "empty";
  elements.workingResult.hidden = which !== "working";
  elements.previewResult.hidden = which !== "preview";
  elements.doneResult.hidden = which !== "done";
}

function restoreStableResult() {
  showResult(state.hasCompletedResult ? "done" : "empty");
}

function validateText() {
  const text = elements.script.value.trim();
  if (!text) throw new Error("Vui lòng nhập nội dung cần đọc.");
  const max = state.config?.limits?.max_text_chars || 2000;
  if (text.length > max) throw new Error(`Nội dung tối đa ${max.toLocaleString("vi-VN")} ký tự mỗi lượt.`);
  return text;
}

function renderPreviewTags(ids = []) {
  elements.previewTags.replaceChildren();
  if (!ids.length) {
    const neutral = document.createElement("span");
    neutral.className = "preview-tag neutral";
    neutral.textContent = "Không tag · đọc tự nhiên";
    elements.previewTags.append(neutral);
    return;
  }
  for (const id of ids) {
    const tag = state.tagById.get(id);
    if (!tag) continue;
    const chip = document.createElement("span");
    chip.className = `preview-tag ${tag.fidelity}`;
    chip.textContent = `${tag.icon} ${tag.mention}`;
    chip.title = `${tag.name} · ${tag.support_label}`;
    elements.previewTags.append(chip);
  }
}

function renderWarnings(warnings = []) {
  elements.previewWarnings.replaceChildren();
  for (const warning of warnings) {
    const note = document.createElement("p");
    note.textContent = warning;
    elements.previewWarnings.append(note);
  }
}

function renderPreview(payload) {
  elements.performanceScript.textContent = payload.performance_text || "";
  renderPreviewTags(payload.emotion_tags || []);
  const speed = Number(payload.effects?.speed ?? payload.speed ?? elements.speed.value);
  const segmentCount = payload.segment_count
    || payload.effects?.segment_count
    || payload.segments?.length
    || 1;
  const wrapperGroupCount = payload.wrapper_group_count
    || payload.effects?.wrapper_group_count
    || 1;
  const styleTransfer = payload.effects?.style_transfer ?? elements.styleTransfer.checked;
  const styleText = styleTransfer ? " · mẫu phong cách bật" : "";
  elements.previewEffects.textContent = `${segmentCount} đoạn kịch bản · ${wrapperGroupCount} nhóm tổng hợp · tốc độ ${formatSpeed(speed)}×${styleText} · WAV 48 kHz`;
  renderWarnings(payload.warnings || []);
}

async function loadConfig() {
  try {
    state.config = await jsonRequest("/api/config");
    state.configLoaded = true;
    renderTagCatalog(state.config.emotion_tags);
    elements.script.maxLength = state.config.limits.max_text_chars;
    elements.speed.min = state.config.limits.speed_min;
    elements.speed.max = state.config.limits.speed_max;
    elements.speed.value = state.config.limits.speed_default;
    const styleConfig = state.config.style_transfer || {};
    elements.styleTransfer.checked = Boolean(styleConfig.available && styleConfig.default);
    elements.styleTransfer.disabled = !styleConfig.available;
    elements.styleTransferRow.hidden = !styleConfig.available;
    elements.uploadHint.textContent = `Giọng rõ, một người nói, không nhạc nền · tối đa ${state.config.limits.max_upload_mb} MB`;
    updateCharCount();
    updateSpeedLabel();

    elements.builtinVoice.replaceChildren();
    for (const voice of state.config.builtin_voices) {
      const option = document.createElement("option");
      option.value = voice;
      option.textContent = voice;
      elements.builtinVoice.append(option);
    }

    if (state.config.reference.available) {
      const ref = state.config.reference;
      const channelLabel = ref.channels === 1 ? "mono" : `${ref.channels} kênh`;
      elements.referenceMeta.textContent = `${ref.duration_seconds.toFixed(2)} giây · ${Math.round(ref.sample_rate / 1000)} kHz · ${channelLabel}`;
      elements.referencePlayer.src = authorizedUrl(ref.url);
    } else {
      elements.referenceMeta.textContent = "Không tìm thấy mẫu giọng";
      document.querySelector('input[name="voice-source"][value="provided"]').disabled = true;
      document.querySelector('input[name="voice-source"][value="builtin"]').checked = true;
      updateSource("builtin");
    }

    const engine = state.config.engine;
    elements.engineBadge.textContent = engine.available ? "Engine sẵn sàng" : "Cần cài engine";
    elements.engineBadge.className = `engine-badge ${engine.available ? "ready" : "error"}`;
    elements.engineBadge.title = engine.detail;
    if (!engine.available) showError(engine.detail);
  } catch (error) {
    state.configLoaded = false;
    elements.engineBadge.textContent = "Mất kết nối";
    elements.engineBadge.className = "engine-badge error";
    showError(error.message);
  } finally {
    syncControls();
  }
}

async function previewPerformance() {
  clearError();
  const sequence = ++state.previewSequence;
  try {
    validateText();
    elements.previewButton.disabled = true;
    const payload = await jsonRequest("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: elements.script.value,
        speed: Number(elements.speed.value),
        style_transfer: elements.styleTransfer.checked,
      }),
    });
    if (sequence !== state.previewSequence) return;
    renderPreview(payload);
    showResult("preview");
    elements.previewResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    if (sequence === state.previewSequence) showError(error.message);
  } finally {
    if (sequence === state.previewSequence) syncControls();
  }
}

function buildJobForm() {
  const form = new FormData();
  form.append("text", elements.script.value);
  form.append("speed", elements.speed.value);
  form.append("reference_mode", state.source === "microphone" ? "upload" : state.source);
  form.append("builtin_voice", elements.builtinVoice.value || "Adam");
  form.append("denoise", String(elements.denoise.checked));
  form.append("style_transfer", String(elements.styleTransfer.checked));
  form.append("consent", String(elements.consent.checked));
  if (state.source === "upload" && elements.referenceFile.files[0]) {
    form.append("reference_file", elements.referenceFile.files[0]);
  }
  if (state.source === "microphone" && state.microphoneFile) form.append("reference_file", state.microphoneFile);
  return form;
}

function endActiveJobWithError(message) {
  if (state.polling) clearTimeout(state.polling);
  state.polling = null;
  state.pendingJob = null;
  state.jobInFlight = false;
  elements.resultPanel.setAttribute("aria-busy", "false");
  restoreStableResult();
  showError(message);
  syncControls();
}

function titleForTags(ids = []) {
  const names = ids
    .map((id) => state.tagById.get(id)?.name)
    .filter(Boolean)
    .slice(0, 2);
  return names.length ? names.join(" + ") : "Bản tự nhiên";
}

function finishActiveJob(job) {
  if (state.polling) clearTimeout(state.polling);
  state.polling = null;

  // Serverless mode: backend embeds audio as base64 in the response.
  // Use a Blob URL to avoid a separate /audio/ fetch that would hit a
  // different stateless instance with an empty /tmp.
  if (job.audio_b64) {
    const bytes = Uint8Array.from(atob(job.audio_b64), (c) => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: "audio/wav" });
    const blobUrl = URL.createObjectURL(blob);
    elements.resultPlayer.src = blobUrl;
    elements.downloadLink.href = blobUrl;
    elements.downloadLink.download = job.output_name || "teu-voice.wav";
  } else {
    const audioUrl = new URL(authorizedUrl(job.audio_url), window.location.origin);
    audioUrl.searchParams.set("v", String(Date.now()));
    elements.resultPlayer.src = `${audioUrl.pathname}${audioUrl.search}`;
    elements.downloadLink.href = authorizedUrl(job.audio_url);
  }

  elements.trackTitle.textContent = titleForTags(job.emotion_tags);
  const styleText = job.effects?.style_transfer ? " · mẫu phong cách" : "";
  elements.trackMeta.textContent = `${job.duration_seconds.toFixed(2)} giây · ${formatSpeed(job.speed)}×${styleText} · WAV 48 kHz · local`;
  state.completedPreview = job;
  state.hasCompletedResult = true;
  state.pendingJob = null;
  state.jobInFlight = false;
  elements.resultPanel.setAttribute("aria-busy", "false");
  showResult("done");
  syncControls();
}

async function createJob() {
  if (state.jobInFlight) return;
  clearError();
  try {
    validateText();
  } catch (error) {
    showError(error.message);
    elements.script.focus();
    return;
  }
  if (state.source !== "builtin" && !elements.consent.checked) {
    showError("Hãy xác nhận quyền sử dụng mẫu giọng trước khi tạo.");
    elements.consent.focus();
    return;
  }
  if (state.source === "upload" || state.source === "microphone") {
    const file = state.source === "microphone" ? state.microphoneFile : elements.referenceFile.files[0];
    if (!file) {
      showError(state.source === "microphone" ? "Hãy thu một mẫu mic 6–8 giây trước khi tạo giọng." : "Vui lòng chọn một tệp WAV làm mẫu giọng.");
      if (state.source === "upload") elements.referenceFile.focus();
      return;
    }
    const maxBytes = (state.config?.limits?.max_upload_mb || 20) * 1024 * 1024;
    if (file.size > maxBytes) {
      showError(`Tệp mẫu giọng vượt quá giới hạn ${state.config.limits.max_upload_mb} MB.`);
      elements.referenceFile.focus();
      return;
    }
  }

  state.pendingJob = { speed: Number(elements.speed.value) };
  state.jobInFlight = true;
  state.pollFailures = 0;
  elements.resultPanel.setAttribute("aria-busy", "true");
  elements.jobStage.textContent = "Đang gửi kịch bản";
  showResult("working");
  syncControls();
  if (window.matchMedia("(max-width: 900px)").matches) {
    elements.resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  try {
    const job = await jsonRequest("/api/jobs", { method: "POST", body: buildJobForm() });
    state.pendingJob = { ...state.pendingJob, id: job.id };
    // Serverless mode: synthesis runs synchronously, so the POST response
    // already contains the final status. Skip polling in that case.
    if (job.status === "done") {
      finishActiveJob(job);
    } else if (job.status === "error" || job.status === "cancelled") {
      endActiveJobWithError(job.error || "Engine không thể tạo giọng.");
    } else {
      await pollJob(job.id);
    }
  } catch (error) {
    endActiveJobWithError(error.message);
  }
}

async function pollJob(jobId) {
  if (state.polling) clearTimeout(state.polling);
  state.polling = null;
  try {
    const job = await jsonRequest(`/api/jobs/${jobId}`);
    state.pollFailures = 0;
    elements.jobStage.textContent = job.stage;
    if (job.status === "done") {
      finishActiveJob(job);
      return;
    }
    if (job.status === "error" || job.status === "cancelled") {
      endActiveJobWithError(job.error || "Engine không thể tạo giọng.");
      return;
    }
    state.polling = setTimeout(() => pollJob(jobId), 1000);
  } catch (error) {
    state.pollFailures += 1;
    if (state.pollFailures <= 3 && state.jobInFlight) {
      elements.jobStage.textContent = `Mất kết nối, đang thử lại (${state.pollFailures}/3)`;
      state.polling = setTimeout(() => pollJob(jobId), 1500);
      return;
    }
    endActiveJobWithError(`${error.message} Hãy thử lại; lượt tạo trên máy có thể vẫn đang hoàn tất.`);
  }
}

elements.script.addEventListener("input", () => {
  updateCharCount();
  updateSuggestions();
});
elements.script.addEventListener("click", updateSuggestions);
elements.script.addEventListener("keydown", handleScriptKeydown);
elements.script.addEventListener("compositionstart", () => {
  state.composing = true;
  closeSuggestions();
});
elements.script.addEventListener("compositionend", () => {
  state.composing = false;
  updateSuggestions();
});
elements.script.addEventListener("blur", () => setTimeout(closeSuggestions, 120));
elements.speed.addEventListener("input", updateSpeedLabel);
elements.referenceFile.addEventListener("change", () => {
  const file = elements.referenceFile.files[0];
  elements.fileLabel.textContent = file ? file.name : "Chọn mẫu WAV 3–8 giây";
  elements.consent.checked = false;
});
elements.microphoneButton.addEventListener("click", toggleMicrophoneCapture);
for (const radio of document.querySelectorAll('input[name="voice-source"]')) {
  radio.addEventListener("change", () => updateSource(radio.value));
}
elements.previewButton.addEventListener("click", previewPerformance);
elements.generateButton.addEventListener("click", createJob);
elements.closePreview.addEventListener("click", restoreStableResult);
elements.showScript.addEventListener("click", () => {
  if (!state.completedPreview) return;
  renderPreview(state.completedPreview);
  showResult("preview");
});
document.addEventListener("pointerdown", (event) => {
  if (event.target !== elements.script && !elements.tagSuggestions.contains(event.target)) closeSuggestions();
});

updateCharCount();
updateSpeedLabel();
updateSource("provided", { resetConsent: false });
syncControls();
loadConfig();
