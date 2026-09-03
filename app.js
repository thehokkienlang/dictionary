const DATA_URL = "public/data/hokkien-hanri-dict.json?v=20260903-search-pages";
const RESULTS_PER_PAGE = 10;

const state = {
  entries: [],
  groups: [],
  inputMode: "lomari",
  loaded: false,
  currentPage: 1,
  readingCandidates: new Map(),
};

const searchInput = document.querySelector("#searchInput");
const clearButton = document.querySelector("#clearButton");
const summaryBar = document.querySelector("#summaryBar");
const resultSummary = document.querySelector("#resultSummary");
const dataStatus = document.querySelector("#dataStatus");
const results = document.querySelector("#results");
const template = document.querySelector("#resultTemplate");
const pagination = document.querySelector("#pagination");
const hangulKeyboardToggle = document.querySelector("#hangulKeyboardToggle");
const imeCandidates = document.querySelector("#imeCandidates");
const hangulComposer = new TangliengimHangulIme.Composer();
let internalSearchUpdate = false;
let audioRunId = 0;
let currentAudio = null;
let sharedAudioContext = null;
const decodedAudioCache = new Map();

const HANGUL_TONE_MARKS = {
  1: "ꞈ",
  "ˆ": "ꞈ",
  "ꞈ": "ꞈ",
  2: "ˎ",
  "ˋ": "ˎ",
  "`": "ˎ",
  "ˎ": "ˎ",
  4: "ˏ",
  "ˊ": "ˏ",
  "ˏ": "ˏ",
  5: "ˍ",
  "ˉ": "ˍ",
  "ˍ": "ˍ",
};

const UPPER_HANGUL_TONE_MARKS = {
  1: "ˆ",
  "ˆ": "ˆ",
  "ꞈ": "ˆ",
  2: "ˋ",
  "ˋ": "ˋ",
  "`": "ˋ",
  "ˎ": "ˋ",
  3: "",
  4: "ˊ",
  "ˊ": "ˊ",
  "ˏ": "ˊ",
  5: "ˉ",
  "ˉ": "ˉ",
  "ˍ": "ˉ",
};

const HANGUL_TONE_CHARS = new Set([...Object.keys(HANGUL_TONE_MARKS), "3"]);
const LATIN_WIDTH_APOSTROPHES = new Set(["’", "‘", "'"]);

function normalizeText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{Letter}\p{Number}\u1100-\u11FF\u3130-\u318F\u3400-\u4DBF\u4E00-\u9FFF\u{20000}-\u{2EBEF}]+/gu, "")
    .toLowerCase();
}

function normalizeNasalAlias(value, nasalMarker) {
  let output = "";
  let canMarkPrevious = false;
  for (const char of [...String(value || "").normalize("NFKD").toLowerCase()]) {
    if (char === "\u0330" || char === "~") {
      if (canMarkPrevious && !output.endsWith(nasalMarker)) {
        output += nasalMarker;
      }
    } else if (/[\u0300-\u036f]/u.test(char)) {
      continue;
    } else if (/[\p{Letter}\p{Number}\u1100-\u11FF\u3130-\u318F\u3400-\u4DBF\u4E00-\u9FFF\u{20000}-\u{2EBEF}]/u.test(char)) {
      output += char;
      canMarkPrevious = true;
    } else {
      canMarkPrevious = false;
    }
  }
  return output;
}

function normalizeLomariSearchAliases(value) {
  const aliases = new Set([
    normalizeText(value),
    normalizeNasalAlias(value, "l"),
    normalizeNasalAlias(value, "~"),
  ].filter(Boolean));
  return [...aliases].join(" ");
}

function queryVariants(rawQuery) {
  const variants = new Set([
    normalizeText(rawQuery),
    normalizeNasalAlias(rawQuery, "l"),
    normalizeNasalAlias(rawQuery, "~"),
  ].filter(Boolean));

  if (String(rawQuery || "").includes("~")) {
    variants.delete(normalizeText(rawQuery));
  }

  return [...variants];
}

function visibleKind(kind) {
  const names = {
    plain_hanri: "Hanri",
    mixed_hanri: "Mixed",
    hangul_override: "Hangul",
    numeric_override: "Number",
    other: "Other",
  };
  return names[kind] || kind;
}

function searchableEntry(entry) {
  return entry.active && entry.kind !== "numeric_override";
}

function groupKeyForEntry(entry) {
  const headword = entry.hanri || entry.reading;
  const reading = normalizeText(entry.readingBase || entry.reading || headword);
  return `${headword}\u0000${reading}`;
}

function groupEntries(entries) {
  const byHeadwordReading = new Map();
  for (const entry of entries.filter(searchableEntry)) {
    const headword = entry.hanri || entry.reading;
    const key = groupKeyForEntry(entry);
    if (!byHeadwordReading.has(key)) {
      byHeadwordReading.set(key, {
        hanri: headword,
        kind: entry.kind,
        priority: entry.priority,
        row: entry.row,
        readings: [],
        search: {
          hanri: normalizeText(headword),
          reading: "",
          readingBase: "",
          lomari: "",
          lomariAliases: "",
          english: "",
          all: "",
        },
      });
    }

    const group = byHeadwordReading.get(key);
    group.priority = Math.min(group.priority, entry.priority);
    group.row = Math.min(group.row, entry.row);
    group.readings.push(entry);
  }

  const groups = [...byHeadwordReading.values()];
  for (const group of groups) {
    group.readings.sort((a, b) =>
      a.priority - b.priority || a.row - b.row || a.reading.localeCompare(b.reading)
    );
    group.search.reading = normalizeText(group.readings.map((item) => item.reading).join(" "));
    group.search.readingBase = normalizeText(group.readings.map((item) => item.readingBase).join(" "));
    group.search.lomari = normalizeText(group.readings.map((item) => item.lomari).join(" "));
    group.search.lomariAliases = normalizeLomariSearchAliases(group.readings.map((item) => item.lomari).join(" "));
    group.search.english = normalizeText(group.readings.map((item) => item.english || "").join(" "));
    group.search.all = [
      group.search.hanri,
      group.search.reading,
      group.search.readingBase,
      group.search.lomari,
      group.search.lomariAliases,
      group.search.english,
      normalizeText(group.readings.map((item) => item.raw?.reading || "").join(" ")),
    ].join(" ");
  }

  return groups.sort((a, b) => a.priority - b.priority || a.row - b.row || a.hanri.localeCompare(b.hanri));
}

function scoreField(value, query, boost) {
  if (!value) return 0;
  if (value === query) return 100 + boost;
  if (value.startsWith(query)) return 80 + boost;
  if (value.includes(query)) return 55 + boost;
  return 0;
}

function scoreGroup(group, queries, mode) {
  if (!queries.length) {
    return 0;
  }

  const fields = [
    { name: "hanri", boost: mode === "hanri-hangul" ? 6 : 0 },
    { name: "reading", boost: mode === "hanri-hangul" ? 6 : 0 },
    { name: "readingBase", boost: mode === "hanri-hangul" ? 6 : 0 },
    { name: "lomari", boost: mode === "lomari" ? 6 : 0 },
    { name: "english", boost: 0 },
  ];

  let best = 0;
  for (const query of queries) {
    for (const field of fields) {
      const value = field.name === "lomari"
        ? `${group.search.lomari || ""} ${group.search.lomariAliases || ""}`.trim()
        : group.search[field.name] || "";
      best = Math.max(best, scoreField(value, query, field.boost));
    }
  }

  return best;
}

function searchGroups() {
  const rawQuery = searchInput.value.trim();
  const queries = queryVariants(rawQuery);

  const matches = state.groups
    .map((group) => ({ group, score: scoreGroup(group, queries, state.inputMode) }))
    .filter((item) => item.score > 0)
    .sort((a, b) =>
      b.score - a.score ||
      a.group.priority - b.group.priority ||
      a.group.row - b.group.row ||
      a.group.hanri.localeCompare(b.group.hanri)
    );

  const total = matches.length;
  const totalPages = Math.ceil(total / RESULTS_PER_PAGE);
  const page = totalPages
    ? Math.max(1, Math.min(state.currentPage, totalPages))
    : 1;
  const start = (page - 1) * RESULTS_PER_PAGE;

  return {
    rawQuery,
    shown: matches.slice(start, start + RESULTS_PER_PAGE).map((item) => item.group),
    total,
    page,
    totalPages,
  };
}

function buildReadingCandidateMap(entries) {
  const byReading = new Map();
  for (const entry of entries.filter(searchableEntry)) {
    const readingKeys = [
      entry.readingBase,
      entry.reading,
      entry.raw?.reading,
    ].map((value) => normalizeText(TangliengimHangulIme.normalizeReadingBase(value)));

    for (const key of new Set(readingKeys.filter(Boolean))) {
      if (!byReading.has(key)) byReading.set(key, []);
      byReading.get(key).push(entry);
    }
  }

  for (const candidates of byReading.values()) {
    candidates.sort((a, b) =>
      a.priority - b.priority || a.row - b.row || a.hanri.localeCompare(b.hanri)
    );
  }
  return byReading;
}

function isImeCandidateChar(char) {
  if (!char) return false;
  return /[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3ˆˋ`ˊˉꞈˎˏˍ12345]/u.test(char);
}

function activeCandidateRange() {
  if (state.inputMode !== "hanri-hangul") return null;
  const text = searchInput.value;
  const cursor = searchInput.selectionStart ?? text.length;
  if (cursor !== (searchInput.selectionEnd ?? cursor)) return null;

  let start = cursor;
  while (start > 0 && isImeCandidateChar(text[start - 1])) start -= 1;
  if (start === cursor) return null;
  return { text, start, end: cursor, segment: text.slice(start, cursor) };
}

function findImeCandidates() {
  const range = activeCandidateRange();
  if (!range) return [];

  const chars = [...range.segment];
  const starts = [];
  let offset = range.start;
  for (const char of chars) {
    starts.push(offset);
    offset += char.length;
  }

  const found = [];
  for (let index = 0; index < chars.length; index += 1) {
    const suffix = chars.slice(index).join("");
    const key = normalizeText(TangliengimHangulIme.normalizeReadingBase(suffix));
    const entries = state.readingCandidates.get(key);
    if (!entries?.length) continue;
    for (const entry of entries) {
      found.push({
        entry,
        start: starts[index],
        end: range.end,
        length: suffix.length,
      });
    }
    if (found.length) break;
  }

  const seen = new Set();
  return found
    .filter(({ entry }) => {
      const key = `${entry.hanri}\u0000${entry.reading}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 9);
}

function renderImeCandidates() {
  if (!imeCandidates) return;
  imeCandidates.replaceChildren();

  if (state.inputMode !== "hanri-hangul" || !state.loaded) {
    imeCandidates.hidden = true;
    return;
  }

  const candidates = findImeCandidates();
  imeCandidates.hidden = !candidates.length;
  if (!candidates.length) return;

  for (const [index, candidate] of candidates.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ime-candidate";
    const number = document.createElement("span");
    number.className = "candidate-number";
    number.textContent = String(index + 1);
    const hanri = document.createElement("span");
    hanri.className = "candidate-hanri";
    if (candidate.entry.kind === "hangul_override") {
      hanri.classList.add("candidate-hangul");
      hanri.append(renderToneMarkedReading(candidate.entry.reading));
    } else {
      hanri.textContent = candidate.entry.hanri;
    }
    const reading = document.createElement("span");
    reading.className = "candidate-reading";
    if (candidate.entry.kind !== "hangul_override") {
      reading.append(renderToneMarkedReading(candidate.entry.reading));
    }
    button.append(number, hanri);
    if (candidate.entry.kind !== "hangul_override") {
      button.append(reading);
    }
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => applyImeCandidate(candidate));
    imeCandidates.append(button);
  }
}

function applyImeCandidate(candidate) {
  const text = searchInput.value;
  const next = `${text.slice(0, candidate.start)}${candidate.entry.hanri}${text.slice(candidate.end)}`;
  hangulComposer.setText(next, candidate.start + candidate.entry.hanri.length);
  updateSearchFromComposer();
}

function isToneMark(char) {
  return HANGUL_TONE_CHARS.has(char);
}

function displayTextNode(text) {
  const fragment = document.createDocumentFragment();
  for (const char of [...String(text || "")]) {
    if (LATIN_WIDTH_APOSTROPHES.has(char)) {
      const span = document.createElement("span");
      span.className = "latin-apostrophe";
      span.textContent = char;
      fragment.append(span);
    } else {
      fragment.append(document.createTextNode(char));
    }
  }
  return fragment;
}

function isPrecomposedHangul(char) {
  if (!char) return false;
  const code = char.codePointAt(0);
  return code >= 0xac00 && code <= 0xd7a3;
}

function isInitialJamo(char) {
  if (!char) return false;
  const code = char.codePointAt(0);
  return (code >= 0x1100 && code <= 0x1112) || char === "ᅙ";
}

function isVowelJamo(char) {
  if (!char) return false;
  const code = char.codePointAt(0);
  return (code >= 0x1161 && code <= 0x1175) || char === "ᅷ" || char === "ᆤ" || char === "ힻ";
}

function isFinalJamo(char) {
  if (!char || isVowelJamo(char)) return false;
  const code = char.codePointAt(0);
  return code >= 0x11a8 && code <= 0x11ff;
}

function codePointAtInfo(text, index) {
  const code = text.codePointAt(index);
  if (code === undefined) return null;
  const char = String.fromCodePoint(code);
  return { char, code, end: index + char.length };
}

function isHanriChar(char) {
  const code = char?.codePointAt(0);
  if (code === undefined) return false;
  return (
    (code >= 0x3400 && code <= 0x4dbf) ||
    (code >= 0x4e00 && code <= 0x9fff) ||
    (code >= 0x20000 && code <= 0x2ebef)
  );
}

function readingUnitAt(text, index) {
  const char = text[index];
  if (!char) return null;

  if (isPrecomposedHangul(char)) {
    return { text: char, end: index + 1, canCarryTone: true };
  }

  if (isInitialJamo(char) && isVowelJamo(text[index + 1])) {
    let end = index + 2;
    if (isFinalJamo(text[end])) {
      end += 1;
    }
    return { text: text.slice(index, end), end, canCarryTone: true };
  }

  return { text: char, end: index + 1, canCarryTone: false };
}

function headwordUnitAt(text, index) {
  const hangulUnit = readingUnitAt(text, index);
  if (hangulUnit?.canCarryTone) {
    const tone = text[hangulUnit.end];
    const end = isToneMark(tone) ? hangulUnit.end + 1 : hangulUnit.end;
    return {
      kind: "hangul",
      text: hangulUnit.text,
      raw: text.slice(index, end),
      end,
    };
  }

  const first = codePointAtInfo(text, index);
  if (!first) return null;

  if (isHanriChar(first.char)) {
    let end = first.end;
    while (end < text.length) {
      const next = codePointAtInfo(text, end);
      if (!next || !isHanriChar(next.char)) break;
      end = next.end;
    }
    return { kind: "hanri", text: text.slice(index, end), end };
  }

  return { kind: "literal", text: first.char, end: first.end };
}

function readingUnitToneEnd(text, unit) {
  const tone = text[unit.end];
  return unit.canCarryTone && isToneMark(tone) ? unit.end + 1 : unit.end;
}

function tonedHangulNode(unit, tone) {
  const mark = HANGUL_TONE_MARKS[tone];
  if (!mark) {
    return document.createTextNode(unit);
  }

  const ruby = document.createElement("ruby");
  ruby.className = "hangul-tone";
  ruby.setAttribute("aria-label", `${unit}${tone}`);
  ruby.append(document.createTextNode(unit));

  const rt = document.createElement("rt");
  rt.textContent = mark;
  ruby.append(rt);
  return ruby;
}

function renderToneMarkedReading(reading) {
  const fragment = document.createDocumentFragment();
  const text = String(reading || "");
  let index = 0;

  while (index < text.length) {
    const unit = readingUnitAt(text, index);
    if (!unit) {
      break;
    }

    const tone = text[unit.end];
    if (unit.canCarryTone && isToneMark(tone)) {
      fragment.append(tonedHangulNode(unit.text, tone));
      index = unit.end + 1;
    } else {
      fragment.append(displayTextNode(unit.text));
      index = unit.end;
    }
  }

  return fragment;
}

function renderInlineUpperToneReading(reading) {
  const fragment = document.createDocumentFragment();
  const text = String(reading || "");
  let index = 0;

  while (index < text.length) {
    const unit = readingUnitAt(text, index);
    if (!unit) break;

    const tone = text[unit.end];
    if (unit.canCarryTone) {
      const unitNode = document.createElement("span");
      unitNode.className = "hangul-reading-unit";
      unitNode.textContent = unit.text;
      fragment.append(unitNode);
    } else {
      fragment.append(displayTextNode(unit.text));
    }
    if (unit.canCarryTone && isToneMark(tone)) {
      const mark = UPPER_HANGUL_TONE_MARKS[tone] || "";
      if (mark) {
        const toneNode = document.createElement("span");
        toneNode.className = "inline-upper-tone";
        toneNode.textContent = mark;
        fragment.append(toneNode);
      }
      index = unit.end + 1;
    } else {
      index = unit.end;
    }
  }

  return fragment;
}

function findReadingUnitStart(text, start, unitText) {
  let index = start;
  while (index < text.length) {
    const unit = readingUnitAt(text, index);
    if (!unit) break;
    if (unit.canCarryTone && unit.text === unitText) {
      return index;
    }
    index = readingUnitToneEnd(text, unit);
  }
  return -1;
}

function findNextMixedReadingBoundary(source, sourceIndex, reading, readingIndex) {
  let index = sourceIndex;
  while (index < source.length) {
    const unit = headwordUnitAt(source, index);
    if (!unit) break;

    if (unit.kind === "hangul") {
      const match = findReadingUnitStart(reading, readingIndex, unit.text);
      if (match >= 0) return match;
    } else if (unit.kind === "literal") {
      const match = reading.indexOf(unit.text, readingIndex);
      if (match >= 0) return match;
    }

    index = unit.end;
  }
  return reading.length;
}

function appendHanriRuby(fragment, hanriText, readingText) {
  if (!readingText) {
    fragment.append(displayTextNode(hanriText));
    return;
  }

  const ruby = document.createElement("ruby");
  ruby.className = "entry-headword-ruby";
  const base = document.createElement("span");
  base.className = "entry-headword-base";
  base.append(displayTextNode(hanriText));
  const rt = document.createElement("rt");
  rt.className = "entry-headword-reading";
  rt.append(renderInlineUpperToneReading(readingText));
  ruby.append(base, rt);
  fragment.append(ruby);
}

function renderMixedEntryHeadword(group, reading) {
  const fragment = document.createDocumentFragment();
  const source = String(group.hanri || "");
  let sourceIndex = 0;
  let readingIndex = 0;

  while (sourceIndex < source.length) {
    const unit = headwordUnitAt(source, sourceIndex);
    if (!unit) break;

    if (unit.kind === "hanri") {
      const boundary = findNextMixedReadingBoundary(source, unit.end, reading, readingIndex);
      appendHanriRuby(fragment, unit.text, reading.slice(readingIndex, boundary));
      readingIndex = boundary;
    } else if (unit.kind === "hangul") {
      const hangul = document.createElement("span");
      hangul.className = "entry-headword-hangul entry-headword-inline-hangul";
      hangul.append(renderToneMarkedReading(unit.raw));
      fragment.append(hangul);

      const readingUnit = readingUnitAt(reading, readingIndex);
      if (readingUnit?.canCarryTone && readingUnit.text === unit.text) {
        readingIndex = readingUnitToneEnd(reading, readingUnit);
      }
    } else {
      fragment.append(displayTextNode(unit.text));
      if (reading.startsWith(unit.text, readingIndex)) {
        readingIndex += unit.text.length;
      }
    }

    sourceIndex = unit.end;
  }

  return fragment;
}

function renderEntryHeadword(group) {
  const fragment = document.createDocumentFragment();
  const primaryReading = group.readings[0]?.reading || group.hanri || "";

  if (group.kind === "hangul_override") {
    const hangul = document.createElement("span");
    hangul.className = "entry-headword-hangul";
    hangul.append(renderToneMarkedReading(primaryReading));
    fragment.append(hangul);
    return fragment;
  }

  if (group.kind === "mixed_hanri") {
    fragment.append(renderMixedEntryHeadword(group, primaryReading));
    return fragment;
  }

  const ruby = document.createElement("ruby");
  ruby.className = "entry-headword-ruby";
  const base = document.createElement("span");
  base.className = "entry-headword-base";
  base.append(displayTextNode(group.hanri));
  const rt = document.createElement("rt");
  rt.className = "entry-headword-reading";
  rt.append(renderInlineUpperToneReading(primaryReading));
  ruby.append(base, rt);
  fragment.append(ruby);
  return fragment;
}

function copyText(text) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
  return Promise.resolve();
}

function showToast(message) {
  let toast = document.querySelector(".toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.className = "toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    document.body.append(toast);
  }

  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("visible"), 1500);
}

function stopAudio() {
  audioRunId += 1;
  if (currentAudio) {
    try {
      if (typeof currentAudio.stop === "function") currentAudio.stop();
      else if (typeof currentAudio.pause === "function") currentAudio.pause();
    } catch {
      // Already stopped.
    }
    currentAudio = null;
  }
}

function audioContext() {
  if (!sharedAudioContext) {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) {
      throw new Error("Web Audio is not available");
    }
    sharedAudioContext = new Context();
  }
  return sharedAudioContext;
}

async function decodedAudioBuffer(file) {
  const url = encodeURI(file);
  if (decodedAudioCache.has(url)) {
    return decodedAudioCache.get(url);
  }

  const bufferPromise = fetch(url)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.arrayBuffer();
    })
    .then((arrayBuffer) => audioContext().decodeAudioData(arrayBuffer));
  decodedAudioCache.set(url, bufferPromise);
  return bufferPromise;
}

function copyBufferChannels(buffer, startFrame, endFrame) {
  const length = Math.max(1, endFrame - startFrame);
  const channels = [];
  for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
    channels.push(buffer.getChannelData(channel).slice(startFrame, startFrame + length));
  }
  return channels;
}

function crossfadeSamples(previous, next) {
  const length = Math.min(previous.length, next.length);
  const output = new Float32Array(length);
  if (length <= 1) {
    output.set(next.subarray(0, length));
    return output;
  }
  for (let index = 0; index < length; index += 1) {
    const alpha = index / (length - 1);
    output[index] = previous[index] * (1 - alpha) + next[index] * alpha;
  }
  return output;
}

function speedUpChannels(channels, sampleRate, speedFactor) {
  if (speedFactor <= 1 || !channels.length || !sampleRate) {
    return channels;
  }

  const totalFrames = channels[0].length;
  if (totalFrames <= sampleRate / 20) {
    return channels;
  }

  const keepFrames = Math.max(1, Math.round(sampleRate * 0.1));
  const removeFrames = Math.max(1, Math.round(keepFrames * (speedFactor - 1)));
  const fadeFrames = Math.max(1, Math.round(sampleRate * 0.01));
  const output = channels.map(() => []);
  let position = 0;

  while (position < totalFrames) {
    const keepEnd = Math.min(position + keepFrames, totalFrames);
    for (let channel = 0; channel < channels.length; channel += 1) {
      const source = channels[channel];
      const target = output[channel];
      for (let index = position; index < keepEnd; index += 1) {
        target.push(source[index]);
      }
    }
    position = keepEnd;

    if (position >= totalFrames) break;
    const skipEnd = Math.min(position + removeFrames, totalFrames);
    const canCrossfade = output[0].length >= fadeFrames && skipEnd + fadeFrames < totalFrames;

    if (canCrossfade) {
      for (let channel = 0; channel < channels.length; channel += 1) {
        const target = output[channel];
        const source = channels[channel];
        const targetStart = target.length - fadeFrames;
        for (let index = 0; index < fadeFrames; index += 1) {
          const alpha = index / Math.max(1, fadeFrames - 1);
          target[targetStart + index] =
            target[targetStart + index] * (1 - alpha) + source[skipEnd + index] * alpha;
        }
      }
      position = skipEnd + fadeFrames;
    } else {
      position = skipEnd;
    }
  }

  return output.map((channel) => Float32Array.from(channel));
}

function fadeOutChannels(channels, sampleRate, fadeSeconds) {
  const fadeFrames = Math.min(
    channels[0]?.length || 0,
    Math.max(1, Math.round(sampleRate * fadeSeconds))
  );
  if (fadeFrames <= 1) return channels;

  for (const channel of channels) {
    const start = channel.length - fadeFrames;
    for (let index = 0; index < fadeFrames; index += 1) {
      channel[start + index] *= (fadeFrames - index - 1) / (fadeFrames - 1);
    }
  }
  return channels;
}

function audioTrimFrames(buffer, segment) {
  let startSeconds = 0;
  if (segment.englishClusterHelper) {
    startSeconds = 0.24;
  } else if (segment.trimStart) {
    startSeconds = 0.2;
  }
  const endSeconds = segment.trimEnd ? 0.15 : 0;
  let startFrame = Math.round(buffer.sampleRate * startSeconds);
  let endFrame = buffer.length - Math.round(buffer.sampleRate * endSeconds);

  if (startFrame >= endFrame) {
    const overflow = startFrame - endFrame + 1;
    const endTrimFrames = buffer.length - endFrame;
    if (endTrimFrames >= overflow) {
      endFrame += overflow;
    } else {
      startFrame = Math.max(0, startFrame - (overflow - endTrimFrames));
      endFrame = buffer.length;
    }
  }

  return {
    startFrame: Math.max(0, Math.min(startFrame, buffer.length - 1)),
    endFrame: Math.max(1, Math.min(endFrame, buffer.length)),
  };
}

async function processedAudioSegment(segment) {
  const buffer = await decodedAudioBuffer(segment.file);
  const { startFrame, endFrame } = audioTrimFrames(buffer, segment);
  let channels = copyBufferChannels(buffer, startFrame, endFrame);
  channels = speedUpChannels(channels, buffer.sampleRate, Number(segment.speed) || 1);

  if (segment.englishClusterHelper && channels[0]?.length) {
    const maxFrames = Math.max(1, Math.round(buffer.sampleRate * 0.24));
    channels = channels.map((channel) => channel.slice(0, Math.min(channel.length, maxFrames)));
    fadeOutChannels(channels, buffer.sampleRate, 0.015);
  }

  return {
    channels,
    sampleRate: buffer.sampleRate,
    channelCount: buffer.numberOfChannels,
    canOverlapPrevious: Boolean(segment.trimStart),
    lFinal: Boolean(segment.lFinal),
    shortOverlapFinal: Boolean(segment.shortOverlapFinal),
    englishClusterHelper: Boolean(segment.englishClusterHelper),
  };
}

function overlapSeconds(previous, current) {
  if (current.englishClusterHelper) return 0.04;
  if (previous.englishClusterHelper) return 0.04;
  if (previous.shortOverlapFinal) return 0.05;
  if (previous.lFinal) return 0.15;
  return 0.1;
}

function appendChannels(previousChannels, nextChannels, overlapFrames) {
  const channelCount = previousChannels.length;
  const previousLength = previousChannels[0].length;
  const nextLength = nextChannels[0].length;
  const overlap = Math.max(0, Math.min(overlapFrames, previousLength, nextLength));
  const outputLength = previousLength + nextLength - overlap;
  const outputChannels = [];

  for (let channel = 0; channel < channelCount; channel += 1) {
    const previous = previousChannels[channel];
    const next = nextChannels[Math.min(channel, nextChannels.length - 1)];
    const output = new Float32Array(outputLength);
    output.set(previous.subarray(0, previousLength - overlap), 0);
    if (overlap > 0) {
      output.set(
        crossfadeSamples(previous.subarray(previousLength - overlap), next.subarray(0, overlap)),
        previousLength - overlap
      );
    }
    output.set(next.subarray(overlap), previousLength);
    outputChannels.push(output);
  }

  return outputChannels;
}

async function buildImeAudioBuffer(segments) {
  const context = audioContext();
  const processed = [];
  for (const segment of segments) {
    processed.push(await processedAudioSegment(segment));
  }
  if (!processed.length) {
    throw new Error("No playable audio");
  }

  const sampleRate = processed[0].sampleRate;
  const channelCount = processed[0].channelCount;
  const leadFrames = Math.max(0, Math.round(sampleRate * 0.25));
  let combined = Array.from({ length: channelCount }, () => new Float32Array(leadFrames));
  let previousSegment = null;

  for (const segment of processed) {
    if (segment.sampleRate !== sampleRate || segment.channelCount !== channelCount) {
      throw new Error("Audio files use different formats");
    }

    const overlap = previousSegment && segment.canOverlapPrevious
      ? Math.round(sampleRate * overlapSeconds(previousSegment, segment))
      : 0;
    combined = appendChannels(combined, segment.channels, overlap);
    previousSegment = segment;
  }

  const output = context.createBuffer(channelCount, combined[0].length, sampleRate);
  for (let channel = 0; channel < channelCount; channel += 1) {
    output.copyToChannel(combined[channel], channel);
  }
  return output;
}

function normalizeAudioSegments(audio) {
  if (audio?.segments?.length) {
    return audio.segments;
  }
  return (audio?.files || []).map((file) => ({
    file,
    trimStart: false,
    trimEnd: false,
    speed: 1,
    lFinal: false,
    shortOverlapFinal: false,
    englishClusterHelper: false,
  }));
}

async function playAudioSequence(audio, button) {
  stopAudio();
  const runId = audioRunId;
  button.classList.add("playing");
  button.disabled = true;
  try {
    const context = audioContext();
    await context.resume();
    const segments = normalizeAudioSegments(audio);
    const buffer = await buildImeAudioBuffer(segments);
    if (runId !== audioRunId) {
      return;
    }

    await new Promise((resolve) => {
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.addEventListener("ended", resolve, { once: true });
      currentAudio = source;
      source.start();
    });
  } finally {
    if (runId === audioRunId) {
      currentAudio = null;
    }
    button.classList.remove("playing");
    button.disabled = false;
  }
}

function renderReading(entry) {
  const wrapper = document.createElement("div");
  wrapper.className = "reading";

  const lomariField = document.createElement("div");
  lomariField.className = "reading-field";
  const lomariLabel = document.createElement("span");
  lomariLabel.className = "field-label";
  lomariLabel.textContent = "Lomari";
  const lomari = document.createElement("span");
  lomari.className = "lomari";
  lomari.textContent = entry.lomari || " ";
  lomariField.append(lomariLabel, lomari);

  const englishField = document.createElement("div");
  englishField.className = "reading-field english-field";
  const englishLabel = document.createElement("span");
  englishLabel.className = "field-label";
  englishLabel.textContent = "English";
  const english = document.createElement("span");
  english.className = "english-gloss";
  english.textContent = entry.english || " ";
  englishField.append(englishLabel, english);

  const actions = document.createElement("div");
  actions.className = "reading-actions";

  const audioSegments = normalizeAudioSegments(entry.audio);
  const missingAudio = entry.audio?.missing || [];
  const playButton = document.createElement("button");
  playButton.className = "audio-reading";
  playButton.type = "button";
  playButton.textContent = "Listen";
  playButton.setAttribute("aria-label", `Listen to ${entry.reading}`);
  if (!audioSegments.length) {
    playButton.disabled = true;
    playButton.title = missingAudio.length ? `No audio for ${missingAudio.join(", ")}` : "No audio for this reading";
  }
  playButton.addEventListener("click", async () => {
    if (!audioSegments.length) {
      showToast(playButton.title);
      return;
    }
    try {
      await playAudioSequence(entry.audio, playButton);
      if (missingAudio.length) {
        showToast(`Missing audio: ${missingAudio.join(", ")}`);
      }
    } catch {
      playButton.classList.remove("playing");
      playButton.disabled = false;
      showToast("Could not play audio");
    }
  });

  const copyButton = document.createElement("button");
  copyButton.className = "copy-reading";
  copyButton.type = "button";
  copyButton.textContent = "Copy";
  copyButton.setAttribute("aria-label", `Copy ${entry.reading} ${entry.lomari || ""}`.trim());
  copyButton.addEventListener("click", async () => {
    const value = entry.lomari ? `${entry.reading}\t${entry.lomari}` : entry.reading;
    try {
      await copyText(value);
      showToast("Reading copied");
    } catch {
      showToast("Could not copy reading");
    }
  });

  actions.append(playButton, copyButton);
  wrapper.append(lomariField, englishField, actions);
  return wrapper;
}

function paginationItems(page, totalPages) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  if (page <= 4) {
    return [1, 2, 3, 4, 5, "ellipsis", totalPages];
  }

  if (page >= totalPages - 3) {
    return [1, "ellipsis", totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
  }

  return [1, "ellipsis-before", page - 1, page, page + 1, "ellipsis-after", totalPages];
}

function renderPagination(page, totalPages) {
  pagination.replaceChildren();
  pagination.hidden = totalPages <= 1;
  if (totalPages <= 1) return;

  const makeButton = (label, nextPage, options = {}) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-button";
    button.textContent = label;
    button.disabled = options.disabled || false;
    if (options.current) {
      button.classList.add("current");
      button.setAttribute("aria-current", "page");
    }
    button.addEventListener("click", () => {
      state.currentPage = nextPage;
      renderResults();
      searchInput.focus();
    });
    return button;
  };

  pagination.append(makeButton("<", Math.max(1, page - 1), { disabled: page === 1 }));
  for (const item of paginationItems(page, totalPages)) {
    if (typeof item === "number") {
      pagination.append(makeButton(String(item), item, { current: item === page }));
    } else {
      const ellipsis = document.createElement("span");
      ellipsis.className = "page-ellipsis";
      ellipsis.textContent = "...";
      pagination.append(ellipsis);
    }
  }
  pagination.append(makeButton(">", Math.min(totalPages, page + 1), { disabled: page === totalPages }));
}

function renderResults() {
  if (!state.loaded) return;

  const { rawQuery, shown, total, page, totalPages } = searchGroups();
  results.replaceChildren();
  clearButton.hidden = !searchInput.value;
  renderImeCandidates();

  if (!rawQuery) {
    summaryBar.hidden = true;
    pagination.hidden = true;
    pagination.replaceChildren();
    resultSummary.textContent = "";
    return;
  }

  summaryBar.hidden = false;

  if (!shown.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const title = document.createElement("strong");
    title.textContent = "No matching entries yet";
    const note = document.createElement("span");
    note.textContent = "Try Hanri, Tangliengim Hangul, Lomari, or English meanings.";
    empty.append(title, note);
    results.append(empty);
    resultSummary.textContent = "0 results";
    pagination.hidden = true;
    pagination.replaceChildren();
    return;
  }

  for (const group of shown) {
    const node = template.content.firstElementChild.cloneNode(true);
    const hanri = node.querySelector(".hanri");
    hanri.replaceChildren(renderEntryHeadword(group));
    node.querySelector(".entry-meta").textContent = `${visibleKind(group.kind)} · ${group.readings.length} reading${group.readings.length === 1 ? "" : "s"}`;
    const readings = node.querySelector(".readings");
    group.readings.slice(0, 8).forEach((entry) => readings.append(renderReading(entry)));
    if (group.readings.length > 8) {
      const more = document.createElement("div");
      more.className = "more-readings";
      more.textContent = `+${group.readings.length - 8} more readings`;
      readings.append(more);
    }
    results.append(node);
  }

  const rangeStart = (page - 1) * RESULTS_PER_PAGE + 1;
  const rangeEnd = rangeStart + shown.length - 1;
  resultSummary.textContent = `${total} result${total === 1 ? "" : "s"} · showing ${rangeStart}-${rangeEnd}`;
  renderPagination(page, totalPages);
}

function setInputMode(mode) {
  state.inputMode = mode === "lomari" ? "lomari" : "hanri-hangul";
  if (hangulKeyboardToggle) {
    hangulKeyboardToggle.setAttribute("aria-pressed", String(state.inputMode === "hanri-hangul"));
  }
  searchInput.placeholder = "Type 漢字, 한글, Lomari, or English...";
  searchInput.classList.toggle("hangul-ime-active", state.inputMode === "hanri-hangul");
  hangulComposer.setText(searchInput.value, searchInput.selectionStart ?? searchInput.value.length);
  state.currentPage = 1;
  renderResults();
}

function replaceSelectionBeforeImeKey() {
  const start = searchInput.selectionStart ?? searchInput.value.length;
  const end = searchInput.selectionEnd ?? start;
  if (start === end) return start;
  const next = `${searchInput.value.slice(0, start)}${searchInput.value.slice(end)}`;
  hangulComposer.setText(next, start);
  return start;
}

function syncComposerFromSearchInput() {
  const text = hangulComposer.text();
  const cursor = searchInput.selectionStart ?? searchInput.value.length;
  const selectionEnd = searchInput.selectionEnd ?? cursor;

  if (searchInput.value !== text || cursor !== selectionEnd) {
    hangulComposer.setText(searchInput.value, cursor);
    return;
  }

  if (cursor !== hangulComposer.displayCursorPos()) {
    hangulComposer.commit();
    hangulComposer.cursorPos = Math.max(0, Math.min(cursor, hangulComposer.output.length));
    hangulComposer.keyHistory = [];
  }
}

function updateSearchFromComposer() {
  internalSearchUpdate = true;
  searchInput.value = hangulComposer.text();
  const cursor = hangulComposer.displayCursorPos();
  searchInput.setSelectionRange(cursor, cursor);
  internalSearchUpdate = false;
  state.currentPage = 1;
  renderResults();
}

function shouldHandleImeKey(event) {
  if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return false;
  if (event.key.length === 1) return true;
  return ["Backspace", "ArrowLeft", "ArrowRight", "Home", "End", "Enter"].includes(event.key);
}

function handleHanriHangulKeydown(event) {
  if (state.inputMode !== "hanri-hangul" || !shouldHandleImeKey(event)) return;

  if (event.key === "Enter") {
    renderImeCandidates();
    return;
  }

  event.preventDefault();
  syncComposerFromSearchInput();
  replaceSelectionBeforeImeKey();

  if (event.key === "Backspace") {
    hangulComposer.backspace();
  } else if (event.key === "ArrowLeft") {
    hangulComposer.moveLeft();
  } else if (event.key === "ArrowRight") {
    hangulComposer.moveRight();
  } else if (event.key === "Home") {
    hangulComposer.commit();
    hangulComposer.cursorPos = 0;
    hangulComposer.keyHistory = [];
  } else if (event.key === "End") {
    hangulComposer.commit();
    hangulComposer.cursorPos = hangulComposer.output.length;
    hangulComposer.keyHistory = [];
  } else if (event.key.length === 1) {
    hangulComposer.processChar(event.key);
  }

  updateSearchFromComposer();
}

function handleHanriHangulBeforeInput(event) {
  if (state.inputMode !== "hanri-hangul" || event.isComposing || !event.cancelable) return;

  if (event.inputType === "insertText" && event.data) {
    event.preventDefault();
    syncComposerFromSearchInput();
    replaceSelectionBeforeImeKey();
    for (const char of [...event.data]) {
      hangulComposer.processChar(char);
    }
    updateSearchFromComposer();
  } else if (event.inputType === "deleteContentBackward") {
    event.preventDefault();
    syncComposerFromSearchInput();
    replaceSelectionBeforeImeKey();
    hangulComposer.backspace();
    updateSearchFromComposer();
  }
}

async function loadDictionary() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    state.entries = data.entries || [];
    state.groups = groupEntries(state.entries);
    state.readingCandidates = buildReadingCandidateMap(state.entries);
    state.loaded = true;
    dataStatus.textContent = `${data.counts?.active_entries || state.entries.length} active TSV entries`;
    renderResults();
  } catch (error) {
    state.loaded = true;
    dataStatus.textContent = "Dictionary failed to load";
    summaryBar.hidden = false;
    pagination.hidden = true;
    resultSummary.textContent = "Check that public/data/hokkien-hanri-dict.json exists.";
    results.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state error";
    empty.textContent = `Could not load dictionary data: ${error.message}`;
    results.append(empty);
  }
}

searchInput.addEventListener("beforeinput", handleHanriHangulBeforeInput);
searchInput.addEventListener("keydown", handleHanriHangulKeydown);
searchInput.addEventListener("input", () => {
  if (internalSearchUpdate) return;
  if (state.inputMode === "hanri-hangul") {
    hangulComposer.setText(searchInput.value, searchInput.selectionStart ?? searchInput.value.length);
  }
  state.currentPage = 1;
  renderResults();
});
searchInput.addEventListener("click", () => {
  if (state.inputMode === "hanri-hangul") {
    syncComposerFromSearchInput();
    renderImeCandidates();
  }
});
clearButton.addEventListener("click", () => {
  searchInput.value = "";
  hangulComposer.setText("", 0);
  state.currentPage = 1;
  searchInput.focus();
  renderResults();
});
hangulKeyboardToggle?.addEventListener("click", () => {
  setInputMode(state.inputMode === "hanri-hangul" ? "lomari" : "hanri-hangul");
  searchInput.focus();
});

loadDictionary();
setInputMode("lomari");
