const TangliengimHangulIme = (() => {
  const L_TABLE = [...Array(19)].map((_, index) => String.fromCodePoint(0x1100 + index));
  const V_TABLE = [...Array(21)].map((_, index) => String.fromCodePoint(0x1161 + index));
  const T_TABLE = ["", ...[...Array(27)].map((_, index) => String.fromCodePoint(0x11a8 + index))];
  const L_INDEX = Object.fromEntries(L_TABLE.map((char, index) => [char, index]));
  const V_INDEX = Object.fromEntries(V_TABLE.map((char, index) => [char, index]));
  const T_INDEX = Object.fromEntries(T_TABLE.map((char, index) => [char, index]));

  const KEY_TO_JAMO = {
    r: "ㄱ", R: "ㄲ", s: "ㄴ", e: "ㄷ", E: "ㄸ", f: "ㄹ",
    a: "ㅁ", q: "ㅂ", Q: "ㅃ", t: "ㅅ", d: "ㅇ",
    w: "ㅈ", W: "ㅉ", c: "ㅊ", z: "ㅋ", x: "ㅌ", v: "ㅍ", g: "ㅎ", G: "ㆆ",
    k: "ㅏ", o: "ㅐ", i: "ㅑ", j: "ㅓ", p: "ㅔ", P: "ㅖ",
    u: "ㅕ", h: "ㅗ", y: "ㅛ", n: "ㅜ", b: "ㅠ", m: "ㅡ", l: "ㅣ",
  };
  const SHIFT_PRESERVED_KEYS = new Set(["R", "E", "Q", "W", "P", "G"]);

  const COMPAT_TO_L = {
    "ㄱ": "ᄀ", "ㄲ": "ᄁ", "ㄴ": "ᄂ", "ㄷ": "ᄃ", "ㄸ": "ᄄ", "ㄹ": "ᄅ",
    "ㅁ": "ᄆ", "ㅂ": "ᄇ", "ㅃ": "ᄈ", "ㅅ": "ᄉ", "ㅇ": "ᄋ",
    "ㅈ": "ᄌ", "ㅉ": "ᄍ", "ㅊ": "ᄎ", "ㅋ": "ᄏ", "ㅌ": "ᄐ", "ㅍ": "ᄑ", "ㅎ": "ᄒ",
    "ㆆ": "ᅙ",
  };
  const COMPAT_TO_V = {
    "ㅏ": "ᅡ", "ㅐ": "ᅢ", "ㅑ": "ᅣ", "ㅓ": "ᅥ", "ㅔ": "ᅦ",
    "ㅕ": "ᅧ", "ㅖ": "ᅨ", "ㅗ": "ᅩ", "ㅛ": "ᅭ", "ㅜ": "ᅮ", "ㅠ": "ᅲ",
    "ㅡ": "ᅳ", "ㅣ": "ᅵ", "ㅢ": "ᅴ",
  };
  const COMPAT_TO_T = {
    "ㄱ": "ᆨ", "ㄴ": "ᆫ", "ㄷ": "ᆮ", "ㄹ": "ᆯ", "ㅁ": "ᆷ",
    "ㅂ": "ᆸ", "ㅅ": "ᆺ", "ㅇ": "ᆼ", "ㅈ": "ᆽ", "ㅊ": "ᆾ", "ㅎ": "ᇂ",
  };
  const T_TO_L = {
    "ᆨ": "ᄀ", "ᆫ": "ᄂ", "ᆮ": "ᄃ", "ᆯ": "ᄅ", "ᆷ": "ᄆ",
    "ᆸ": "ᄇ", "ᆺ": "ᄉ", "ᆼ": "ᄋ", "ᆽ": "ᄌ", "ᆾ": "ᄎ", "ᇂ": "ᄒ",
  };
  const L_TO_COMPAT = Object.fromEntries(Object.entries(COMPAT_TO_L).map(([key, value]) => [value, key]));
  const V_TO_COMPAT = Object.fromEntries(Object.entries(COMPAT_TO_V).map(([key, value]) => [value, key]));
  Object.assign(V_TO_COMPAT, {
    "ᅪ": "ㅘ",
    "ᅫ": "ㅙ",
    "ᅬ": "ㅚ",
    "ᅰ": "ㅞ",
    "ᅱ": "ㅟ",
    "ᅴ": "ㅢ",
  });
  const T_TO_COMPAT = Object.fromEntries(Object.entries(COMPAT_TO_T).map(([key, value]) => [value, key]));
  T_TO_COMPAT["ᆶ"] = "ㅀ";

  const V_COMBINE = {
    "ᅩᅡ": "ᅪ",
    "ᅩᅢ": "ᅫ",
    "ᅩᅵ": "ᅬ",
    "ᅮᅦ": "ᅰ",
    "ᅮᅵ": "ᅱ",
    "ᅳᅵ": "ᅴ",
  };
  const T_COMBINE = { "ᆯᇂ": "ᆶ" };
  const T_SPLIT = { "ᆶ": ["ᆯ", "ᇂ"] };
  const SPECIAL_MEDIALS = new Set(["ᅷ", "ᆤ", "ힻ"]);
  const HANGUL_CHOSEONG_FILLER = "\u115f";
  const TONE_MARKS = { 1: "ˆ", 2: "ˋ", 4: "ˊ", 5: "ˉ" };
  const TONE_INPUT = { "ˆ": "1", "ꞈ": "1", "ˋ": "2", "`": "2", "ˎ": "2", "ˊ": "4", "ˏ": "4", "ˉ": "5", "ˍ": "5" };

  const INITIAL_KEY_TO_L = Object.fromEntries(
    Object.entries(KEY_TO_JAMO)
      .filter(([, jamo]) => jamo in COMPAT_TO_L)
      .map(([key, jamo]) => [key, COMPAT_TO_L[jamo]])
  );
  const HOKKIEN_SEQUENCE_MAP = {};
  for (const [key, initial] of Object.entries(INITIAL_KEY_TO_L)) {
    HOKKIEN_SEQUENCE_MAP[`${key}mp`] = `${initial}ힻ`;
    HOKKIEN_SEQUENCE_MAP[`${key}kn`] = `${initial}ᅷ`;
    HOKKIEN_SEQUENCE_MAP[`${key}in`] = `${initial}ᆤ`;
  }
  Object.assign(HOKKIEN_SEQUENCE_MAP, {
    mp: `${HANGUL_CHOSEONG_FILLER}ힻ`,
    kn: `${HANGUL_CHOSEONG_FILLER}ᅷ`,
    in: `${HANGUL_CHOSEONG_FILLER}ᆤ`,
    mdk: "ᅙᅡ",
  });
  const MAX_SEQUENCE_LENGTH = Math.max(...Object.keys(HOKKIEN_SEQUENCE_MAP).map((key) => key.length));

  function normalizeKeyboardChar(char) {
    if (/^[A-Z]$/.test(char) && !SHIFT_PRESERVED_KEYS.has(char)) return char.toLowerCase();
    return char;
  }

  function composeSyllable(initial, medial, final = "") {
    if (initial in L_INDEX && medial in V_INDEX && final in T_INDEX) {
      return String.fromCodePoint(0xac00 + (L_INDEX[initial] * 21 + V_INDEX[medial]) * 28 + T_INDEX[final]);
    }
    return `${initial}${medial}${final}`;
  }

  function canBeFinal(compat) {
    return compat in COMPAT_TO_T;
  }

  function isInitialJamo(char) {
    return char in L_INDEX || char === "ᅙ";
  }

  function isVowelJamo(char) {
    return char in V_INDEX || SPECIAL_MEDIALS.has(char);
  }

  function isHangulishForTone(char) {
    if (!char) return false;
    const code = char.codePointAt(0);
    return (
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0x3130 && code <= 0x318f) ||
      (code >= 0x1100 && code <= 0x11ff) ||
      SPECIAL_MEDIALS.has(char)
    );
  }

  function normalizeReadingBase(value) {
    return [...String(value || "")]
      .filter((char) => !"12345ˆˋ`ˊˉꞈˎˏˍ".includes(char))
      .join("");
  }

  class Composer {
    constructor() {
      this.output = "";
      this.cursorPos = 0;
      this.initial = "";
      this.medial = "";
      this.final = "";
      this.keyHistory = [];
    }

    hasBuffer() {
      return Boolean(this.initial || this.medial || this.final);
    }

    bufferText() {
      if (this.initial && this.medial) return composeSyllable(this.initial, this.medial, this.final);
      if (this.initial) return L_TO_COMPAT[this.initial] || this.initial;
      if (this.medial) return V_TO_COMPAT[this.medial] || this.medial;
      if (this.final) return T_TO_COMPAT[this.final] || this.final;
      return "";
    }

    text() {
      return `${this.output.slice(0, this.cursorPos)}${this.bufferText()}${this.output.slice(this.cursorPos)}`;
    }

    displayCursorPos() {
      return this.cursorPos + this.bufferText().length;
    }

    snapshot() {
      return [this.output, this.cursorPos, this.initial, this.medial, this.final];
    }

    restore(snapshot) {
      [this.output, this.cursorPos, this.initial, this.medial, this.final] = snapshot;
      this.cursorPos = Math.max(0, Math.min(this.cursorPos, this.output.length));
    }

    setText(text, cursor = text.length) {
      this.output = String(text || "");
      this.cursorPos = Math.max(0, Math.min(cursor, this.output.length));
      this.initial = "";
      this.medial = "";
      this.final = "";
      this.keyHistory = [];
    }

    commit() {
      if (!this.hasBuffer()) return;
      const text = this.bufferText();
      this.output = `${this.output.slice(0, this.cursorPos)}${text}${this.output.slice(this.cursorPos)}`;
      this.cursorPos += text.length;
      this.initial = "";
      this.medial = "";
      this.final = "";
    }

    insertLiteral(text) {
      this.commit();
      this.output = `${this.output.slice(0, this.cursorPos)}${text}${this.output.slice(this.cursorPos)}`;
      this.cursorPos += text.length;
      this.keyHistory = [];
    }

    moveLeft() {
      this.commit();
      if (this.cursorPos > 0) this.cursorPos -= 1;
      this.keyHistory = [];
    }

    moveRight() {
      this.commit();
      if (this.cursorPos < this.output.length) this.cursorPos += 1;
      this.keyHistory = [];
    }

    addInitial(initial, sourceCompat = "") {
      if (!this.hasBuffer()) {
        this.initial = initial;
        return;
      }
      if (!this.initial && this.medial === "ᅳ" && !this.final && sourceCompat === "ㅇ") {
        this.medial = "";
        this.initial = "ᅙ";
        return;
      }
      if (this.initial && !this.medial) {
        const previousCompat = L_TO_COMPAT[this.initial] || "";
        if (previousCompat in COMPAT_TO_T && sourceCompat in COMPAT_TO_T) {
          const candidate = T_COMBINE[`${COMPAT_TO_T[previousCompat]}${COMPAT_TO_T[sourceCompat]}`];
          if (candidate) {
            this.initial = "";
            this.final = candidate;
            return;
          }
        }
        this.commit();
        this.initial = initial;
        return;
      }
      if (this.initial && this.medial && !this.final && sourceCompat && canBeFinal(sourceCompat)) {
        this.final = COMPAT_TO_T[sourceCompat];
        return;
      }
      if (this.initial && this.medial && this.final && sourceCompat && canBeFinal(sourceCompat)) {
        const candidate = T_COMBINE[`${this.final}${COMPAT_TO_T[sourceCompat]}`];
        if (candidate) {
          this.final = candidate;
          return;
        }
      }
      this.commit();
      this.initial = initial;
    }

    addVowel(medial) {
      if (!this.hasBuffer()) {
        this.medial = medial;
        return;
      }
      if (!this.initial && this.medial && !this.final) {
        const candidate = V_COMBINE[`${this.medial}${medial}`];
        if (candidate) {
          this.medial = candidate;
          return;
        }
        this.commit();
        this.medial = medial;
        return;
      }
      if (this.initial && !this.medial) {
        this.medial = medial;
        return;
      }
      if (this.initial && this.medial && !this.final) {
        const candidate = V_COMBINE[`${this.medial}${medial}`];
        if (candidate) {
          this.medial = candidate;
          return;
        }
        this.commit();
        if (SPECIAL_MEDIALS.has(medial)) {
          this.insertLiteral(`${HANGUL_CHOSEONG_FILLER}${medial}`);
        } else {
          this.medial = medial;
        }
        return;
      }
      if (this.initial && this.medial && this.final) {
        if (this.final in T_SPLIT) {
          const [keepFinal, moveFinal] = T_SPLIT[this.final];
          this.final = keepFinal;
          this.commit();
          this.initial = T_TO_L[moveFinal] || "";
          this.medial = medial;
        } else {
          const moveInitial = T_TO_L[this.final] || "";
          if (!moveInitial) {
            this.commit();
            this.initial = "ᄋ";
            this.medial = medial;
          } else {
            this.final = "";
            this.commit();
            this.initial = moveInitial;
            this.medial = medial;
          }
        }
        return;
      }
      this.commit();
      this.initial = "ᄋ";
      this.medial = medial;
    }

    backspace() {
      if (this.final) {
        if (this.final in T_SPLIT) this.final = T_SPLIT[this.final][0];
        else this.final = "";
        return;
      }
      if (this.medial) {
        const reverse = Object.fromEntries(Object.entries(V_COMBINE).map(([key, value]) => [value, key[0]]));
        if (this.medial in reverse) this.medial = reverse[this.medial];
        else this.medial = "";
        return;
      }
      if (this.initial) {
        this.initial = "";
        return;
      }
      if (this.cursorPos > 0) {
        this.output = `${this.output.slice(0, this.cursorPos - 1)}${this.output.slice(this.cursorPos)}`;
        this.cursorPos -= 1;
      }
      this.keyHistory = [];
    }

    addTone(digit) {
      const mark = TONE_MARKS[digit];
      if (!mark) return;
      this.commit();
      const before = this.output[this.cursorPos - 1];
      if (isHangulishForTone(before)) {
        this.output = `${this.output.slice(0, this.cursorPos)}${mark}${this.output.slice(this.cursorPos)}`;
        this.cursorPos += mark.length;
      } else {
        this.insertLiteral(digit);
      }
      this.keyHistory = [];
    }

    handleCompat(compat) {
      if (compat in COMPAT_TO_V) this.addVowel(COMPAT_TO_V[compat]);
      else if (compat in COMPAT_TO_L) this.addInitial(COMPAT_TO_L[compat], compat);
      else this.insertLiteral(compat);
    }

    startMappedCluster(mapped) {
      this.commit();
      if (mapped.length >= 2 && isInitialJamo(mapped[0]) && isVowelJamo(mapped[1])) {
        this.initial = mapped[0];
        this.medial = mapped[1];
        this.final = mapped[2] in T_INDEX ? mapped[2] : "";
        if (mapped.length > 3) {
          this.commit();
          this.insertLiteral(mapped.slice(3));
        }
      } else {
        this.insertLiteral(mapped);
      }
    }

    processChar(char) {
      const normalized = normalizeKeyboardChar(char);
      if (normalized in TONE_INPUT) {
        this.addTone(TONE_INPUT[normalized]);
        return;
      }
      if ("12345".includes(normalized)) {
        this.addTone(normalized);
        return;
      }
      if (!(normalized in KEY_TO_JAMO)) {
        this.insertLiteral(char);
        return;
      }

      const before = this.snapshot();
      this.handleCompat(KEY_TO_JAMO[normalized]);
      this.keyHistory.push([normalized, before]);
      if (this.keyHistory.length > MAX_SEQUENCE_LENGTH) {
        this.keyHistory = this.keyHistory.slice(-MAX_SEQUENCE_LENGTH);
      }
      const rawTail = this.keyHistory.map(([key]) => key).join("");
      const match = Object.entries(HOKKIEN_SEQUENCE_MAP)
        .sort((a, b) => b[0].length - a[0].length)
        .find(([sequence]) => rawTail.endsWith(sequence));
      if (match) {
        const startIndex = this.keyHistory.length - match[0].length;
        this.restore(this.keyHistory[startIndex][1]);
        this.startMappedCluster(match[1]);
        this.keyHistory = [];
      }
    }
  }

  return {
    Composer,
    normalizeReadingBase,
  };
})();

window.TangliengimHangulIme = TangliengimHangulIme;
