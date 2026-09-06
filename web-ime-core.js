const TangliengimImeCore = (() => {
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

  function searchableEntry(entry) {
    return entry.active && entry.kind !== "numeric_override";
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
      if (!unit) break;

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

  class TextImeController {
    constructor({
      control,
      candidateContainer,
      entries = [],
      enabled = () => true,
      onUpdate = () => {},
      enterBehavior = "none",
      candidateLimit = 9,
    }) {
      this.control = control;
      this.candidateContainer = candidateContainer;
      this.enabled = enabled;
      this.onUpdate = onUpdate;
      this.enterBehavior = enterBehavior;
      this.candidateLimit = candidateLimit;
      this.composer = new TangliengimHangulIme.Composer();
      this.candidatesByReading = buildReadingCandidateMap(entries);
      this.activeCandidates = [];
      this.internalUpdate = false;

      this.handleKeydown = this.handleKeydown.bind(this);
      this.handleBeforeInput = this.handleBeforeInput.bind(this);
      this.handleInput = this.handleInput.bind(this);
      this.handleCursorChange = this.handleCursorChange.bind(this);

      control.addEventListener("keydown", this.handleKeydown);
      control.addEventListener("beforeinput", this.handleBeforeInput);
      control.addEventListener("input", this.handleInput);
      control.addEventListener("click", this.handleCursorChange);
      control.addEventListener("keyup", this.handleCursorChange);
      this.renderCandidates();
    }

    isEnabled() {
      return Boolean(this.enabled());
    }

    setEntries(entries) {
      this.candidatesByReading = buildReadingCandidateMap(entries || []);
      this.renderCandidates();
    }

    setEnabled() {
      this.syncComposerFromControl();
      this.renderCandidates();
    }

    clear() {
      this.composer.setText("", 0);
      this.updateControlFromComposer();
      this.control.focus();
    }

    syncComposerFromControl() {
      const text = this.composer.text();
      const cursor = this.control.selectionStart ?? this.control.value.length;
      const selectionEnd = this.control.selectionEnd ?? cursor;

      if (this.control.value !== text || cursor !== selectionEnd) {
        this.composer.setText(this.control.value, cursor);
        return;
      }

      if (cursor !== this.composer.displayCursorPos()) {
        this.composer.commit();
        this.composer.cursorPos = Math.max(0, Math.min(cursor, this.composer.output.length));
        this.composer.keyHistory = [];
      }
    }

    replaceSelectionBeforeImeKey() {
      const start = this.control.selectionStart ?? this.control.value.length;
      const end = this.control.selectionEnd ?? start;
      if (start === end) return start;
      const next = `${this.control.value.slice(0, start)}${this.control.value.slice(end)}`;
      this.composer.setText(next, start);
      return start;
    }

    updateControlFromComposer() {
      this.internalUpdate = true;
      this.control.value = this.composer.text();
      const cursor = this.composer.displayCursorPos();
      this.control.setSelectionRange(cursor, cursor);
      this.internalUpdate = false;
      this.onUpdate();
      this.renderCandidates();
    }

    shouldHandleKey(event) {
      if (!this.isEnabled()) return false;
      if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return false;
      if (event.key.length === 1) return true;
      return ["Backspace", "ArrowLeft", "ArrowRight", "Home", "End", "Enter", "Tab"].includes(event.key);
    }

    handleKeydown(event) {
      if (!this.shouldHandleKey(event)) return;

      if (event.key === "Tab" && this.activeCandidates.length) {
        event.preventDefault();
        this.applyCandidate(this.activeCandidates[0]);
        return;
      }

      if (event.key === "Enter" && this.enterBehavior !== "newline") {
        this.renderCandidates();
        return;
      }

      event.preventDefault();
      this.syncComposerFromControl();
      this.replaceSelectionBeforeImeKey();

      if (event.key === "Backspace") {
        this.composer.backspace();
      } else if (event.key === "ArrowLeft") {
        this.composer.moveLeft();
      } else if (event.key === "ArrowRight") {
        this.composer.moveRight();
      } else if (event.key === "Home") {
        this.composer.commit();
        this.composer.cursorPos = 0;
        this.composer.keyHistory = [];
      } else if (event.key === "End") {
        this.composer.commit();
        this.composer.cursorPos = this.composer.output.length;
        this.composer.keyHistory = [];
      } else if (event.key === "Enter") {
        this.composer.insertLiteral("\n");
      } else if (event.key.length === 1) {
        this.composer.processChar(event.key);
      }

      this.updateControlFromComposer();
    }

    handleBeforeInput(event) {
      if (!this.isEnabled() || event.isComposing || !event.cancelable) return;

      if (event.inputType === "insertText" && event.data) {
        event.preventDefault();
        this.syncComposerFromControl();
        this.replaceSelectionBeforeImeKey();
        for (const char of [...event.data]) {
          this.composer.processChar(char);
        }
        this.updateControlFromComposer();
      } else if (event.inputType === "deleteContentBackward") {
        event.preventDefault();
        this.syncComposerFromControl();
        this.replaceSelectionBeforeImeKey();
        this.composer.backspace();
        this.updateControlFromComposer();
      } else if (event.inputType === "insertLineBreak" || event.inputType === "insertParagraph") {
        if (this.enterBehavior !== "newline") return;
        event.preventDefault();
        this.syncComposerFromControl();
        this.replaceSelectionBeforeImeKey();
        this.composer.insertLiteral("\n");
        this.updateControlFromComposer();
      }
    }

    handleInput() {
      if (this.internalUpdate) return;
      if (this.isEnabled()) {
        this.composer.setText(this.control.value, this.control.selectionStart ?? this.control.value.length);
      }
      this.onUpdate();
      this.renderCandidates();
    }

    handleCursorChange() {
      if (this.isEnabled()) {
        this.syncComposerFromControl();
      }
      this.renderCandidates();
    }

    activeCandidateRange() {
      if (!this.isEnabled()) return null;
      const text = this.control.value;
      const cursor = this.control.selectionStart ?? text.length;
      if (cursor !== (this.control.selectionEnd ?? cursor)) return null;

      let start = cursor;
      while (start > 0 && isImeCandidateChar(text[start - 1])) start -= 1;
      if (start === cursor) return null;
      return { text, start, end: cursor, segment: text.slice(start, cursor) };
    }

    findCandidates() {
      const range = this.activeCandidateRange();
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
        const entries = this.candidatesByReading.get(key);
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
        .slice(0, this.candidateLimit);
    }

    renderCandidates() {
      if (!this.candidateContainer) return;
      this.candidateContainer.replaceChildren();

      if (!this.isEnabled()) {
        this.activeCandidates = [];
        this.candidateContainer.hidden = true;
        return;
      }

      this.activeCandidates = this.findCandidates();
      this.candidateContainer.hidden = !this.activeCandidates.length;
      if (!this.activeCandidates.length) return;

      for (const [index, candidate] of this.activeCandidates.entries()) {
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
        button.addEventListener("click", () => this.applyCandidate(candidate));
        this.candidateContainer.append(button);
      }
    }

    applyCandidate(candidate) {
      const text = this.control.value;
      const next = `${text.slice(0, candidate.start)}${candidate.entry.hanri}${text.slice(candidate.end)}`;
      this.composer.setText(next, candidate.start + candidate.entry.hanri.length);
      this.updateControlFromComposer();
    }
  }

  function createTextImeController(options) {
    return new TextImeController(options);
  }

  return {
    buildReadingCandidateMap,
    createTextImeController,
    displayTextNode,
    headwordUnitAt,
    isToneMark,
    normalizeLomariSearchAliases,
    normalizeText,
    queryVariants,
    readingUnitAt,
    readingUnitToneEnd,
    renderInlineUpperToneReading,
    renderToneMarkedReading,
    searchableEntry,
  };
})();

window.TangliengimImeCore = TangliengimImeCore;
