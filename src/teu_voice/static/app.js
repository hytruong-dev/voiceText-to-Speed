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
const MIC_STORAGE_KEY = "teu-voice-microphone-reference-v1";

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

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
  }
  return btoa(binary);
}

function base64ToBytes(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function persistMicrophoneSample(blob, duration) {
  try {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    localStorage.setItem(
      MIC_STORAGE_KEY,
      JSON.stringify({
        base64: bytesToBase64(bytes),
        duration,
        fileName: "microphone-reference.wav",
        savedAt: Date.now(),
      }),
    );
  } catch (_) {
    // Quota or private mode — cloning still works for this session.
  }
}

function clearPersistedMicrophoneSample() {
  try {
    localStorage.removeItem(MIC_STORAGE_KEY);
  } catch (_) {
    // Ignore storage failures.
  }
}

function restorePersistedMicrophoneSample() {
  try {
    const raw = localStorage.getItem(MIC_STORAGE_KEY);
    if (!raw) return false;
    const payload = JSON.parse(raw);
    if (!payload?.base64 || typeof payload.duration !== "number") {
      clearPersistedMicrophoneSample();
      return false;
    }
    const bytes = base64ToBytes(payload.base64);
    const blob = new Blob([bytes], { type: "audio/wav" });
    state.microphoneFile = new File([blob], payload.fileName || "microphone-reference.wav", {
      type: "audio/wav",
    });
    if (state.microphoneUrl) URL.revokeObjectURL(state.microphoneUrl);
    state.microphoneUrl = URL.createObjectURL(blob);
    elements.microphonePlayer.src = state.microphoneUrl;
    elements.microphonePlayer.hidden = false;
    elements.microphoneStatus.textContent = `Đã khôi phục mẫu mic ${Number(payload.duration).toFixed(1)} giây · sẵn sàng clone lại mà không cần thu mới.`;
    return true;
  } catch (_) {
    clearPersistedMicrophoneSample();
    return false;
  }
}

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
    let message = formatApiDetail(payload.detail, "");
    if (!message) {
      if (response.status === 500 || response.status === 502 || response.status === 504) {
        message =
          "Máy chủ cloud hết bộ nhớ hoặc bị ngắt giữa chừng. Hãy rút ngắn nội dung (dưới 250 ký tự), dùng giọng dựng sẵn Adam, tắt mic/clone rồi thử lại.";
      } else {
        message = `Yêu cầu thất bại (${response.status}).`;
      }
    }
    const error = new Error(message);
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

function effectiveMaxTextChars() {
  return state.config?.limits?.max_text_chars || 2000;
}

function effectiveJobChunkChars() {
  const limits = state.config?.limits || {};
  if (state.source === "builtin") {
    return limits.max_job_chars || limits.max_text_chars || 2000;
  }
  return limits.max_clone_text_chars || limits.max_job_chars || 120;
}

function updateCharCount() {
  const max = effectiveMaxTextChars();
  const secondsHint = Math.max(
    1,
    Math.round((elements.script.value.length / 100) * (state.config?.limits?.approx_seconds_per_100_chars || 6)),
  );
  elements.charCount.textContent = `${elements.script.value.length.toLocaleString("vi-VN")} / ${max.toLocaleString("vi-VN")} · ~${secondsHint}s`;
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
  if (isClone) {
    // Speed DSP warps clone timbre; keep near natural reading rate.
    elements.speed.value = "1";
    updateSpeedLabel();
  }
  if (state.config?.limits) {
    elements.script.maxLength = effectiveMaxTextChars();
  }
  updateCharCount();
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

function trimAndNormalizeCloneSamples(samples, sampleRate) {
  const threshold = 0.01;
  let start = 0;
  let end = samples.length - 1;
  while (start < samples.length && Math.abs(samples[start]) <= threshold) start += 1;
  while (end > start && Math.abs(samples[end]) <= threshold) end -= 1;
  const guard = Math.floor(sampleRate * 0.08);
  start = Math.max(0, start - guard);
  end = Math.min(samples.length - 1, end + guard);
  let trimmed = samples.subarray(start, end + 1);

  const preferredSeconds = 7.5;
  const preferredSamples = Math.floor(sampleRate * preferredSeconds);
  if (trimmed.length > preferredSamples) {
    const frame = Math.max(1, Math.floor(sampleRate * 0.02));
    const hop = frame * 2;
    let bestStart = 0;
    let bestScore = -1;
    for (let offset = 0; offset + preferredSamples <= trimmed.length; offset += hop) {
      let speech = 0;
      let energy = 0;
      for (let index = offset; index < offset + preferredSamples; index += frame) {
        const sample = trimmed[index];
        const abs = Math.abs(sample);
        if (abs > threshold) speech += 1;
        energy += sample * sample;
      }
      const frames = Math.ceil(preferredSamples / frame);
      const score = (speech / frames) * Math.sqrt(energy / frames);
      if (score > bestScore) {
        bestScore = score;
        bestStart = offset;
      }
    }
    trimmed = trimmed.subarray(bestStart, bestStart + preferredSamples);
  }

  let peak = 0;
  for (let index = 0; index < trimmed.length; index += 1) {
    peak = Math.max(peak, Math.abs(trimmed[index]));
  }
  if (peak < 0.02) {
    return { error: "Mẫu quá nhỏ; hãy thu gần mic hơn rồi thử lại." };
  }
  if (peak >= 0.985) {
    return { error: "Mic đã bị quá âm lượng. Hãy hạ gain mic rồi thu lại để tránh méo màu giọng." };
  }

  // Keep natural timbre — no EQ. Only gentle peak match for enrollment.
  const targetPeak = 10 ** (-3.0 / 20);
  const gain = targetPeak / peak;
  const normalized = new Float32Array(trimmed.length);
  for (let index = 0; index < trimmed.length; index += 1) {
    normalized[index] = trimmed[index] * gain;
  }

  const fade = Math.min(Math.floor(sampleRate * 0.004), Math.floor(normalized.length / 2));
  for (let index = 0; index < fade; index += 1) {
    const ramp = index / fade;
    normalized[index] *= ramp;
    normalized[normalized.length - 1 - index] *= ramp;
  }
  return { samples: normalized, peak, duration: normalized.length / sampleRate };
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

function clearMicrophoneUi(message) {
  state.microphoneFile = null;
  if (state.microphoneUrl) URL.revokeObjectURL(state.microphoneUrl);
  state.microphoneUrl = null;
  elements.microphonePlayer.pause();
  elements.microphonePlayer.removeAttribute("src");
  elements.microphonePlayer.hidden = true;
  elements.microphoneStatus.textContent = message;
}

function resetMicrophoneSample(message, { clearStorage = true } = {}) {
  clearMicrophoneUi(message);
  if (clearStorage) clearPersistedMicrophoneSample();
}

function finishMicrophoneCapture() {
  const capture = state.microphoneCapture;
  if (!capture) return;
  discardMicrophoneCapture();
  const sampleCount = capture.chunks.reduce((total, chunk) => total + chunk.length, 0);
  const collectedSamples = new Float32Array(sampleCount);
  let offset = 0;
  for (const chunk of capture.chunks) {
    collectedSamples.set(chunk, offset);
    offset += chunk.length;
  }
  const prepared = trimAndNormalizeCloneSamples(collectedSamples, capture.sampleRate);
  if (prepared.error) {
    resetMicrophoneSample(prepared.error);
    return;
  }
  if (prepared.duration < 5.8) {
    resetMicrophoneSample("Phần tiếng nói thực còn ngắn; hãy thu liền mạch ít nhất 6 giây để clone giữ màu giọng tốt hơn.");
    return;
  }
  const blob = encodeMonoWav(prepared.samples, capture.sampleRate);
  state.microphoneFile = new File([blob], "microphone-reference.wav", { type: "audio/wav" });
  if (state.microphoneUrl) URL.revokeObjectURL(state.microphoneUrl);
  state.microphoneUrl = URL.createObjectURL(blob);
  elements.microphonePlayer.src = state.microphoneUrl;
  elements.microphonePlayer.hidden = false;
  elements.microphoneStatus.textContent = `Đã thu ${prepared.duration.toFixed(1)} giây · đã chuẩn hóa mức âm · sẵn sàng clone đúng màu mic này.`;
  elements.consent.checked = false;
  void persistMicrophoneSample(blob, prepared.duration);
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
    clearMicrophoneUi("Đang xin quyền dùng micro…");
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: { ideal: 1 },
        sampleRate: { ideal: 48000 },
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    clearPersistedMicrophoneSample();
    const context = new AudioContext({ sampleRate: 48000 });
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
    if (!restorePersistedMicrophoneSample()) {
      clearMicrophoneUi("Không thể dùng micro.");
    }
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
  const max = effectiveMaxTextChars();
  if (text.length > max) {
    throw new Error(`Nội dung tối đa ${max.toLocaleString("vi-VN")} ký tự mỗi lượt (~60–90 giây).`);
  }
  return text;
}

function splitScriptForJobs(text, maxChars) {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (!cleaned) return [];
  if (cleaned.length <= maxChars) return [cleaned];

  const parts = [];
  let remaining = cleaned;
  while (remaining) {
    if (remaining.length <= maxChars) {
      parts.push(remaining);
      break;
    }
    const window = remaining.slice(0, maxChars + 1);
    let splitAt = -1;
    for (const marker of [". ", "! ", "? ", "; ", ", ", " "]) {
      const index = window.lastIndexOf(marker);
      if (index >= Math.max(24, Math.floor(maxChars / 3))) {
        splitAt = index + marker.length;
        break;
      }
    }
    const atIndex = window.lastIndexOf("@");
    if (atIndex > 0 && (splitAt < 0 || atIndex < splitAt) && atIndex >= Math.floor(maxChars * 0.5)) {
      splitAt = atIndex;
    }
    if (splitAt <= 0) splitAt = maxChars;
    const chunk = remaining.slice(0, splitAt).trim();
    if (chunk) parts.push(chunk);
    remaining = remaining.slice(splitAt).trim();
  }
  return parts;
}

async function waitForJobDone(jobId) {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    if (!state.jobInFlight) throw new Error("Đã hủy lượt tạo giọng.");
    const job = await jsonRequest(`/api/jobs/${jobId}`);
    if (job.status === "done") return job;
    if (job.status === "error" || job.status === "cancelled") {
      throw new Error(job.error || "Engine không thể tạo giọng.");
    }
    elements.jobStage.textContent = job.stage || "Đang tổng hợp";
    await new Promise((resolve) => {
      state.polling = setTimeout(resolve, 900);
    });
  }
  throw new Error("Hết thời gian chờ khi tạo giọng. Hãy thử lại.");
}

async function fetchJobAudioBuffer(job, audioContext) {
  const response = await fetch(authorizedUrl(job.audio_url), {
    headers: state.accessKey ? { "X-Teu-Access-Key": state.accessKey } : {},
  });
  if (!response.ok) throw new Error("Không tải được tệp âm thanh vừa tạo.");
  const data = await response.arrayBuffer();
  return audioContext.decodeAudioData(data.slice(0));
}

function concatenateAudioBuffers(audioContext, buffers, gapSeconds = 0.06) {
  const sampleRate = buffers[0]?.sampleRate || 48000;
  const gapSamples = Math.max(0, Math.floor(sampleRate * gapSeconds));
  let total = 0;
  for (const buffer of buffers) total += buffer.length + gapSamples;
  total = Math.max(1, total - gapSamples);
  const output = audioContext.createBuffer(1, total, sampleRate);
  const channel = output.getChannelData(0);
  let offset = 0;
  for (let index = 0; index < buffers.length; index += 1) {
    channel.set(buffers[index].getChannelData(0), offset);
    offset += buffers[index].length;
    if (index < buffers.length - 1) offset += gapSamples;
  }
  return output;
}

function encodeAudioBufferToWav(buffer) {
  return encodeMonoWav(buffer.getChannelData(0), buffer.sampleRate);
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
    elements.script.maxLength = effectiveMaxTextChars();
    elements.speed.min = state.config.limits.speed_min;
    elements.speed.max = state.config.limits.speed_max;
    elements.speed.value = state.config.limits.speed_default;
    const styleConfig = state.config.style_transfer || {};
    elements.styleTransfer.checked = Boolean(styleConfig.available && styleConfig.default);
    elements.styleTransfer.disabled = !styleConfig.available;
    elements.styleTransferRow.hidden = !styleConfig.available;
    elements.uploadHint.textContent = `Tự chọn cửa sổ 6–8 giây sạch nhất · tối đa ${state.config.limits.max_upload_mb} MB`;
    updateCharCount();
    updateSpeedLabel();

    elements.builtinVoice.replaceChildren();
    const voices = state.config.builtin_voices || [];
    for (const voice of voices) {
      const option = document.createElement("option");
      const id = typeof voice === "string" ? voice : voice.id;
      const label = typeof voice === "string" ? voice : (voice.label || voice.id);
      option.value = id;
      option.textContent = label;
      elements.builtinVoice.append(option);
    }
    const preferredBuiltin = state.config.voice_region?.default_builtin;
    if (preferredBuiltin) elements.builtinVoice.value = preferredBuiltin;

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

function buildJobForm(text = elements.script.value) {
  const form = new FormData();
  form.append("text", text);
  const isClone = state.source !== "builtin";
  // Clone timbre is ruined by rate-change DSP; keep near 1.0×.
  form.append("speed", isClone ? "1" : elements.speed.value);
  form.append("reference_mode", state.source === "microphone" ? "upload" : state.source);
  form.append("builtin_voice", elements.builtinVoice.value || state.config?.voice_region?.default_builtin || "Adam");
  form.append("denoise", "false");
  // Keep style transfer off for clone identity (especially on cloud).
  form.append("style_transfer", isClone ? "false" : String(elements.styleTransfer.checked));
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

function finishActiveJob(job, { audioBlob = null, durationSeconds = null } = {}) {
  if (state.polling) clearTimeout(state.polling);
  state.polling = null;
  if (audioBlob) {
    const objectUrl = URL.createObjectURL(audioBlob);
    elements.resultPlayer.src = objectUrl;
    elements.downloadLink.href = objectUrl;
    elements.downloadLink.download = `teu-voice-${Date.now()}.wav`;
  } else {
    const audioUrl = new URL(authorizedUrl(job.audio_url), window.location.origin);
    audioUrl.searchParams.set("v", String(Date.now()));
    elements.resultPlayer.src = `${audioUrl.pathname}${audioUrl.search}`;
    elements.downloadLink.href = authorizedUrl(job.audio_url);
  }
  elements.trackTitle.textContent = titleForTags(job.emotion_tags);
  const styleText = job.effects?.style_transfer ? " · mẫu phong cách" : "";
  const duration = Number(durationSeconds ?? job.duration_seconds ?? 0);
  elements.trackMeta.textContent = `${duration.toFixed(2)} giây · ${formatSpeed(job.speed)}×${styleText} · WAV 48 kHz`;
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
  let fullText;
  try {
    fullText = validateText();
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

  const chunks = splitScriptForJobs(fullText, effectiveJobChunkChars());
  state.pendingJob = { speed: Number(elements.speed.value), chunks: chunks.length };
  state.jobInFlight = true;
  state.pollFailures = 0;
  elements.resultPanel.setAttribute("aria-busy", "true");
  elements.jobStage.textContent = chunks.length > 1
    ? `Đang tạo đoạn dài (${chunks.length} phần)…`
    : "Đang gửi kịch bản";
  showResult("working");
  syncControls();
  if (window.matchMedia("(max-width: 900px)").matches) {
    elements.resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  try {
    if (chunks.length === 1) {
      const job = await jsonRequest("/api/jobs", { method: "POST", body: buildJobForm(chunks[0]) });
      state.pendingJob = { ...state.pendingJob, id: job.id };
      if (job.status === "done") {
        finishActiveJob(job);
        return;
      }
      const done = await waitForJobDone(job.id);
      finishActiveJob(done);
      return;
    }

    const audioContext = new AudioContext({ sampleRate: 48000 });
    const buffers = [];
    let lastJob = null;
    const allTags = [];
    try {
      for (let index = 0; index < chunks.length; index += 1) {
        elements.jobStage.textContent = `Đang tạo phần ${index + 1}/${chunks.length}…`;
        const job = await jsonRequest("/api/jobs", {
          method: "POST",
          body: buildJobForm(chunks[index]),
        });
        lastJob = job.status === "done" ? job : await waitForJobDone(job.id);
        allTags.push(...(lastJob.emotion_tags || []));
        buffers.push(await fetchJobAudioBuffer(lastJob, audioContext));
      }
      const merged = concatenateAudioBuffers(audioContext, buffers);
      const blob = encodeAudioBufferToWav(merged);
      finishActiveJob(
        {
          ...lastJob,
          emotion_tags: [...new Set(allTags)],
          duration_seconds: merged.duration,
          speed: Number(elements.speed.value),
        },
        { audioBlob: blob, durationSeconds: merged.duration },
      );
    } finally {
      audioContext.close();
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
  elements.fileLabel.textContent = file ? file.name : "Chọn mẫu WAV 3–60 giây";
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
const restoredMic = restorePersistedMicrophoneSample();
updateSource(restoredMic ? "microphone" : "provided", { resetConsent: false });
if (restoredMic) {
  const microphoneRadio = document.querySelector('input[name="voice-source"][value="microphone"]');
  if (microphoneRadio) microphoneRadio.checked = true;
}
syncControls();
loadConfig();
