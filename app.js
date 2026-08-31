const DATA_URL = "public/data/hokkien-hanri-dict.json";
const MAX_INITIAL_RESULTS = 24;
const MAX_SEARCH_RESULTS = 80;

const state = {
  entries: [],
  groups: [],
  mode: "all",
  loaded: false,
};

const searchInput = document.querySelector("#searchInput");
const clearButton = document.querySelector("#clearButton");
const resultSummary = document.querySelector("#resultSummary");
const dataStatus = document.querySelector("#dataStatus");
const results = document.querySelector("#results");
const template = document.querySelector("#resultTemplate");
const filterButtons = [...document.querySelectorAll(".filter-button")];

const HANGUL_TONE_MARKS = {
  1: "ꞈ",
  2: "ˎ",
  4: "ˏ",
  5: "ˍ",
};

function normalizeText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{Letter}\p{Number}\u1100-\u11FF\u3130-\u318F\u3400-\u4DBF\u4E00-\u9FFF\u{20000}-\u{2EBEF}]+/gu, "")
    .toLowerCase();
}

function visibleKind(kind) {
  const names = {
    plain_hanri: "Hanri",
    mixed_hanri: "Mixed",
    hangul_override: "IME",
    numeric_override: "Number",
    other: "Other",
  };
  return names[kind] || kind;
}

function searchableEntry(entry) {
  return entry.active && entry.kind !== "numeric_override";
}

function groupEntries(entries) {
  const byHanri = new Map();
  for (const entry of entries.filter(searchableEntry)) {
    const key = entry.hanri || entry.reading;
    if (!byHanri.has(key)) {
      byHanri.set(key, {
        hanri: key,
        kind: entry.kind,
        priority: entry.priority,
        row: entry.row,
        readings: [],
        search: {
          hanri: normalizeText(key),
          reading: "",
          readingBase: "",
          lomari: "",
          all: "",
        },
      });
    }

    const group = byHanri.get(key);
    group.priority = Math.min(group.priority, entry.priority);
    group.row = Math.min(group.row, entry.row);
    group.readings.push(entry);
  }

  const groups = [...byHanri.values()];
  for (const group of groups) {
    group.readings.sort((a, b) =>
      a.priority - b.priority || a.row - b.row || a.reading.localeCompare(b.reading)
    );
    group.search.reading = normalizeText(group.readings.map((item) => item.reading).join(" "));
    group.search.readingBase = normalizeText(group.readings.map((item) => item.readingBase).join(" "));
    group.search.lomari = normalizeText(group.readings.map((item) => item.lomari).join(" "));
    group.search.all = [
      group.search.hanri,
      group.search.reading,
      group.search.readingBase,
      group.search.lomari,
      normalizeText(group.readings.map((item) => item.raw?.reading || "").join(" ")),
    ].join(" ");
  }

  return groups.sort((a, b) => a.priority - b.priority || a.row - b.row || a.hanri.localeCompare(b.hanri));
}

function scoreGroup(group, query, mode) {
  if (!query) {
    return group.kind === "plain_hanri" ? 1 : 0;
  }

  const fields = mode === "all"
    ? ["hanri", "reading", "readingBase", "lomari", "all"]
    : mode === "reading"
      ? ["reading", "readingBase"]
      : [mode];

  let best = 0;
  for (const field of fields) {
    const value = group.search[field] || "";
    if (!value) continue;
    if (value === query) best = Math.max(best, 100);
    else if (value.startsWith(query)) best = Math.max(best, 80);
    else if (value.includes(query)) best = Math.max(best, 55);
  }

  return best;
}

function searchGroups() {
  const rawQuery = searchInput.value.trim();
  const query = normalizeText(rawQuery);
  const limit = query ? MAX_SEARCH_RESULTS : MAX_INITIAL_RESULTS;

  const matches = state.groups
    .map((group) => ({ group, score: scoreGroup(group, query, state.mode) }))
    .filter((item) => item.score > 0)
    .sort((a, b) =>
      b.score - a.score ||
      a.group.priority - b.group.priority ||
      a.group.row - b.group.row ||
      a.group.hanri.localeCompare(b.group.hanri)
    );

  return {
    rawQuery,
    shown: matches.slice(0, limit).map((item) => item.group),
    total: matches.length,
  };
}

function isToneDigit(char) {
  return /^[12345]$/.test(char);
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
    if (unit.canCarryTone && isToneDigit(tone)) {
      fragment.append(tonedHangulNode(unit.text, tone));
      index = unit.end + 1;
    } else {
      fragment.append(document.createTextNode(unit.text));
      index = unit.end;
    }
  }

  return fragment;
}

function renderReading(entry) {
  const wrapper = document.createElement("div");
  wrapper.className = "reading";

  const hangul = document.createElement("span");
  hangul.className = "hangul";
  hangul.append(renderToneMarkedReading(entry.reading));
  hangul.title = entry.reading;

  const lomari = document.createElement("span");
  lomari.className = "lomari";
  lomari.textContent = entry.lomari || " ";

  const source = document.createElement("span");
  source.className = "source-row";
  source.textContent = `row ${entry.row}`;

  wrapper.append(hangul, lomari, source);
  return wrapper;
}

function renderResults() {
  if (!state.loaded) return;

  const { rawQuery, shown, total } = searchGroups();
  results.replaceChildren();
  clearButton.hidden = !searchInput.value;

  if (!shown.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = rawQuery
      ? "No matching entries yet."
      : "No displayable dictionary entries found.";
    results.append(empty);
    resultSummary.textContent = rawQuery ? "0 results" : "No entries";
    return;
  }

  for (const group of shown) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".hanri").textContent = group.hanri;
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

  const capped = shown.length < total ? `, showing ${shown.length}` : "";
  resultSummary.textContent = rawQuery
    ? `${total} result${total === 1 ? "" : "s"}${capped}`
    : `${state.groups.length} searchable entries, showing ${shown.length}`;
}

function setMode(mode) {
  state.mode = mode;
  for (const button of filterButtons) {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-checked", String(active));
  }
  renderResults();
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
    state.loaded = true;
    dataStatus.textContent = `${data.counts?.active_entries || state.entries.length} active TSV entries`;
    renderResults();
  } catch (error) {
    state.loaded = true;
    dataStatus.textContent = "Dictionary failed to load";
    resultSummary.textContent = "Check that public/data/hokkien-hanri-dict.json exists.";
    results.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state error";
    empty.textContent = `Could not load dictionary data: ${error.message}`;
    results.append(empty);
  }
}

searchInput.addEventListener("input", renderResults);
clearButton.addEventListener("click", () => {
  searchInput.value = "";
  searchInput.focus();
  renderResults();
});
filterButtons.forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

loadDictionary();
