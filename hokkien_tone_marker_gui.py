import csv
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

# ==== 0. WRAP HANGUL+PUNC ====
def nowrap_after_annotation(html: str) -> str:
    """
    Wrap any single <ruby>…</ruby> immediately followed by punctuation in an
    inline-block <span>, to prevent line-breaking between them. Links carry
    white-space: nowrap themselves, so they do not need an extra span.
    """
    return re.sub(
        r'((?:<ruby\b(?:(?!<ruby\b).)*?</ruby>))'                            # one <ruby>…</ruby>
        r'([.,;:?!]”|[.,;:?!])',                                             # followed by punctuation (with optional trailing ”)
        r'<span style="text-indent:0;display:inline-block">\1\2</span>',
        html,
        flags=re.DOTALL
    )

# ==== 1. HELPER DATA ====
special_jamo = {'ᅷ', 'ᆤ', 'ힻ'}
hangul_choseong_filler = '\u115F'
extra_consonants = {'ᅙ'}

# ==== 2. HANGUL DETECTION ====
def is_hangul_precomposed(ch: str) -> bool:
    return '\uAC00' <= ch <= '\uD7A3'

def is_hangul_consonant(ch: str) -> bool:
    return '\u1100' <= ch <= '\u1112' or ch in extra_consonants

def is_hangul_jongseong(ch: str) -> bool:
    return ('\u11A8' <= ch <= '\u11FF') or ch in {'ᇍ', 'ᇎ'}

def is_jamo(ch: str) -> bool:
    return (
        ('\u1100' <= ch <= '\u1112')     # Leading jamo
        or ('\u1161' <= ch <= '\u1175')  # ✅ Medial jamo (THIS MUST BE HERE)
        or ('\u11A8' <= ch <= '\u11FF')  # Jongseong jamo
        or ('\u3130' <= ch <= '\u318F')  # Compatibility jamo
        or ch in special_jamo
        or ch in extra_consonants
    )

# ==== 3. LOMARI TONE MARKER FUNCTIONS ==== 
tone_priority_lomari = ['a', 'e', 'o', 'u', 'i', 'n', 'm']
tone_combining_mark_lomari = {
    '1': '\u0302',
    '2': '\u0300',
    '3': '',
    '4': '\u0301',
    '5': '\u0304',
}
NASAL_TILDE_BELOW = '\u0330'


def lomari_mark_target_index(body: str) -> int | None:
    body_lower = body.lower()
    for letter in tone_priority_lomari:
        idxs = [
            i for i, ch in enumerate(body_lower)
            if ch == letter and not unicodedata.combining(ch)
        ]
        if not idxs:
            continue
        return idxs[1] if letter in ('n', 'm') and len(idxs) > 1 else idxs[0]
    for idx, ch in enumerate(body):
        if ch.isalpha():
            return idx
    return None


def add_combining_mark_to_lomari_target(body: str, mark: str) -> str:
    if not mark:
        return body
    idx = lomari_mark_target_index(body)
    if idx is None:
        return body
    end = idx + 1
    while end < len(body) and unicodedata.combining(body[end]):
        if body[end] == mark:
            return body
        end += 1
    return body[:end] + mark + body[end:]


def nasalize_lomari_rime(rime: str) -> str:
    return add_combining_mark_to_lomari_target(rime, NASAL_TILDE_BELOW)

def apply_tone(token: str) -> str:
    # Accept upper/lowercase, keep leading/trailing punctuation
    m = re.match(r'^([^A-Za-z\u0300-\u036f]*)([A-Za-z\u0300-\u036f]+)([12345])([^A-Za-z\u0300-\u036f]*)$', token)
    if not m:
        return token

    lead, body, tone, tail = m.groups()
    return lead + add_combining_mark_to_lomari_target(
        body,
        tone_combining_mark_lomari.get(tone, ''),
    ) + tail


def convert_tone_string(s: str) -> str:
    out_words = []
    for word in s.split():
        parts = re.split(r"([\-'—,\.!?:;’~])", word)
        out_parts = []
        for tok in parts:
            if tok in ("-", "'", "—", ",", ".", "!", "?", ":", ";", "‧", "~"):
                out_parts.append(tok)
            else:
                out_parts.append(apply_tone(tok))
        out_words.append("".join(out_parts))
    return " ".join(out_words)
# ==== TONE SYMBOL INPUT NORMALISER ====
TONE_SYMBOL_TO_DIGIT = str.maketrans({
    'ꞈ': '1',
    'ˎ': '2',
    'ˏ': '4',
    'ˍ': '5',

## alternate tone-symbol set used in some output formats
    'ˆ': '1',
    '`': '2',
    'ˋ': '2',
    'ˊ': '4',
    'ˉ': '5',
})

def normalize_tone_symbols_to_digits(s: str) -> str:
    return s.translate(TONE_SYMBOL_TO_DIGIT)

# ==== 3a. PRE-NORMALIZE ᅟᅡᆽᅟᅣᆽ → ᅟᅷᅟᆤ SEQUENCES ====
def normalize_yyae(seg: str) -> str:
    out = []

    JONG_ㅈ  = 22   # jongseong index for ㅈ
    VOWEL_ㅏ = 0    # jungseong index for ㅏ
    VOWEL_ㅑ = 2    # jungseong index for ㅑ

    for ch in seg:
        code = ord(ch)

        # only precomposed Hangul
        if not (0xAC00 <= code <= 0xD7A3):
            out.append(ch)
            continue

        s_index   = code - 0xAC00
        lead_idx  = s_index // 588
        vowel_idx = (s_index % 588) // 28
        final_idx = s_index % 28

        initial_jamo = chr(0x1100 + lead_idx)  # ᄀ..ᄒ etc.

        if final_idx == JONG_ㅈ and vowel_idx == VOWEL_ㅏ:
            out.append(initial_jamo + 'ᅷ')   # 갖, 깢, 낮, ...
        elif final_idx == JONG_ㅈ and vowel_idx == VOWEL_ㅑ:
            out.append(initial_jamo + 'ᆤ')   # (ㅑ + ㅈ) series
        else:
            out.append(ch)

    return "".join(out)

def normalize_apostrophes(seg: str) -> str:
    """
    Apostrophe rules:

      若'是   -> 若’是
      '에     -> ’에

      '若是'  -> ‘若是’
      '나시'  -> ‘나시’
    """

    # 1) Quotation-style apostrophes
    #    '若是' -> ‘若是’
    #    '나시' -> ‘나시’
    seg = re.sub(r"'([^']+)'", r"‘\1’", seg)

    # 2) Straight apostrophe immediately after a closing square bracket
    #    is a connector apostrophe.
    #    [若是]'人 -> [若是]’人
    seg = seg.replace("]'", "]’")

    # 3) Internal connector apostrophe
    #    若'是 -> 若’是
    seg = re.sub(r"(?<=\w)'(?=\w)", "’", seg)

    # 4) Leading apostrophe before Hangul
    #    '에 -> ’에
    seg = re.sub(
        r"(?:(?<=\s)|(?<=^)|(?<=\]))'(?=[\uAC00-\uD7A3\u1100-\u11FF])",
        "’",
        seg
    )

    return seg

# ==== 3b. PRE-NORMALIZE ㅜ COMPATIBILITY JAVO SEQUENCES ====
def normalize_compat_jamo(seg: str) -> str:
    
    # 1) base mapping for ㅜ → jamo-cluster
    full_to_jamo = {
        '가ㅜ':'ᄀᅷ','까ㅜ':'ᄁᅷ','나ㅜ':'ᄂᅷ','다ㅜ':'ᄃᅷ',
        '따ㅜ':'ᄄᅷ','라ㅜ':'ᄅᅷ','마ㅜ':'ᄆᅷ','바ㅜ':'ᄇᅷ',
        '빠ㅜ':'ᄈᅷ','사ㅜ':'ᄉᅷ','아ㅜ':'ᄋᅷ',
        '자ㅜ':'ᄌᅷ','짜ㅜ':'ᄍᅷ','차ㅜ':'ᄎᅷ','카ㅜ':'ᄏᅷ',
        '타ㅜ':'ᄐᅷ','파ㅜ':'ᄑᅷ','하ㅜ':'ᄒᅷ',
        '갸ㅜ':'ᄀᆤ','꺄ㅜ':'ᄁᆤ','냐ㅜ':'ᄂᆤ','댜ㅜ':'ᄃᆤ','땨ㅜ':'ᄄᆤ',
        '랴ㅜ':'ᄅᆤ','먀ㅜ':'ᄆᆤ','뱌ㅜ':'ᄇᆤ','뺘ㅜ':'ᄈᆤ','샤ㅜ':'ᄉᆤ',
        '야ㅜ':'ᄋᆤ','쟈ㅜ':'ᄌᆤ','쨔ㅜ':'ᄍᆤ','챠ㅜ':'ᄎᆤ',
        '캬ㅜ':'ᄏᆤ','탸ㅜ':'ᄐᆤ','퍄ㅜ':'ᄑᆤ','햐ㅜ':'ᄒᆤ'
    }

    # 2) add “…ㅎ” variants → “…ᇂ”
    base = full_to_jamo.copy()
    for pre, jamo in base.items():
        full_to_jamo[f"{pre}ㅎ"] = jamo + 'ᇂ'

    # 3) ㅡ + ㅇ-initial (+optional ㅜ, ㅎ)
    def repl_eu(m):
        syll = m.group('syll')
        has_u = (m.group('u') is not None)
        has_h = (m.group('h') is not None)

        # decompose the original syllable into vowel + final
        idx       = ord(syll) - 0xAC00
        vowel_idx = (idx % 588) // 28
        final_idx = idx % 28

        # medial Jamo (U+1161 + vowel_idx)
        medial    = chr(0x1161 + vowel_idx)
        # jongseong Jamo if any
        final_jamo = chr(0x11A7 + final_idx) if final_idx else ''

        # if they wrote ㅡ+X+ㅜ and you have a mapping for X+'ㅜ', use that special medial
        if has_u and (syll + 'ㅜ') in full_to_jamo:
            # full_to_jamo["아ㅜ"] == "ᄋᅷ", so index [1] is the medial 'ᅷ'
            medial = full_to_jamo[syll + 'ㅜ'][1]

        # build up: ᅙ + medial + original-final
        out = 'ᅙ' + medial + final_jamo

        # if they also wrote a trailing 'ㅎ', tack on U+11C2 'ᇂ'
        if has_h:
            out += 'ᇂ'

        return out

    seg = re.sub(
        r'ㅡ(?P<syll>[\uAC00-\uD7A3])(?P<u>ㅜ)?(?P<h>ㅎ)?',
        repl_eu,
        seg
    )

    # 4) tone‐digit replacements, longest‐first
    for pre, jamo in sorted(full_to_jamo.items(), key=lambda kv: -len(kv[0])):
        for tone in ('1','2','3','4','5'):
            seg = seg.replace(f"{pre}{tone}", f"{jamo}{tone}")

    # 5) bare‐sequence replacements, longest‐first
    for pre, jamo in sorted(full_to_jamo.items(), key=lambda kv: -len(kv[0])):
        seg = seg.replace(pre, jamo)

    return seg

def convert_segment_to_ruby(seg: str) -> str:
    # 1) Normalize 앚/쟞-type syllables into special jamo sequences
    seg = normalize_yyae(seg)

    # 2) Normalize apostrophes
    seg = normalize_apostrophes(seg)

    # 3) normalize all compatibility-jamo sequences
    seg = normalize_compat_jamo(seg)

    # 4) preserve leading-hyphen cases
    seg = (seg
       .replace("-뽀2","&#045;뽀2")
       .replace("-둏","&#045;둏")
       .replace("-ᄅᆤ5","&#045;ᄅᆤ5")
       .replace("-웨1","&#045;웨1")
       .replace("-아3","&#045;아3")
       .replace("벳1-","벳1&#045;"))

    # 5) now run the existing three-step pipeline
    return step4_process_extra_consonants(
        step3_process_special_jamo(
            step2_process_precomposed(seg)
        )
    )

# ==== 3c. HANGUL/JAMO -> BASE Lomari (no tone marks yet) ====

# 1) Initials (Choseong)
CHOSEONG_TO_Lomari = {
    'ᄋ': '',    # silent
    'ᄀ': 'k', 'ᄁ': 'g',
    'ᄂ': 'n',
    'ᄃ': 't', 'ᄄ': 'r',
    'ᄅ': 'l',
    'ᄆ': 'm',
    'ᄇ': 'p', 'ᄈ': 'b',
    'ᄉ': 's',
    'ᄌ': 'j', 'ᄍ': 'js',
    'ᄎ': 'ch',
    'ᄏ': 'kh',
    'ᄐ': 'th',
    'ᄑ': 'ph',
    'ᄒ': 'h',

    # extra initials
    'ᅙ': 'ng',
}

# 2) Vowels/medials (Jungseong)
# IMPORTANT: edit these to match YOUR 泉漳諺文 vowel values.
JUNGSEONG_TO_Lomari = {
    'ᅡ': 'a',
    'ᅢ': 'ai',
    'ᅣ': 'ia',
    'ᅥ': 'or',
    'ᅦ': 'e',
    'ᅧ': 'ior',
    'ᅨ': 'ie',
    'ᅩ': 'o',
    'ᅪ': 'oa',
    'ᅫ': 'oai',
    'ᅬ': 'oe',
    'ᅭ': 'io',
    'ᅮ': 'u',
    'ᅰ': 'ue',
    'ᅱ': 'ui',
    'ᅲ': 'iu',
    'ᅳ': '',
    'ᅴ': 'i',
    'ᅵ': 'i',

    # your special medials / symbols
    'ힻ': 'er',
    'ᅷ': 'au',
    'ᆤ': 'iau',
    }

# 3) Finals (Jongseong)
JONGSEONG_TO_Lomari = {
    '': '',
    'ᆨ': 'k',
    'ᆫ': 'n',
    'ᆮ': 't',
    'ᆯ': 'l',
    'ᆷ': 'm',
    'ᆸ': 'p',
    'ᆼ': 'ng',
    'ᆽ': 't',   # final ㅈ → -t (same as ㄷ)
    'ᆾ': 'h',   # final ㅊ → -h (same as ㅎ)
    'ᇂ': 'h',
}

TONE_DIGITS = set("12345")


def build_jamo_pronunciation_readings() -> dict[str, str]:
    readings = {
        'ㅏ': '아1', 'ᅡ': '아1',
        'ㅐ': '애1', 'ᅢ': '애1',
        'ㅑ': '야1', 'ᅣ': '야1',
        'ㅓ': '어1', 'ᅥ': '어1',
        'ㅔ': '에1', 'ᅦ': '에1',
        'ㅕ': '여1', 'ᅧ': '여1',
        'ㅖ': '예1', 'ᅨ': '예1',
        'ㅗ': '오1', 'ᅩ': '오1',
        'ㅘ': '와1', 'ᅪ': '와1',
        'ㅙ': '왜1', 'ᅫ': '왜1',
        'ㅚ': '외1', 'ᅬ': '외1',
        'ㅛ': '요1', 'ᅭ': '요1',
        'ㅜ': '우1', 'ᅮ': '우1',
        'ㅞ': '웨1', 'ᅰ': '웨1',
        'ㅟ': '위1', 'ᅱ': '위1',
        'ㅠ': '유1', 'ᅲ': '유1',
        'ㅡ': '으1', 'ᅳ': '으1',
        'ㅢ': '의1', 'ᅴ': '의1',
        'ㅣ': '이1', 'ᅵ': '이1',
        hangul_choseong_filler + 'ᅷ': hangul_choseong_filler + 'ᅷ1',
        'ᅷ': hangul_choseong_filler + 'ᅷ1',
        hangul_choseong_filler + 'ᆤ': hangul_choseong_filler + 'ᆤ1',
        'ᆤ': hangul_choseong_filler + 'ᆤ1',
        hangul_choseong_filler + 'ힻ': hangul_choseong_filler + 'ힻ1',
        'ힻ': hangul_choseong_filler + 'ힻ1',
        'ㄱ': '기5역1', 'ᄀ': '기5역1', 'ᆨ': '기5역1',
        'ㄲ': '샹5기5역1', 'ᄁ': '샹5기5역1', 'ᆩ': '샹5기5역1',
        'ㄴ': '니5운1', 'ᄂ': '니5운1', 'ᆫ': '니5운1',
        'ㄷ': '디5욷1', 'ᄃ': '디5욷1', 'ᆮ': '디5욷1',
        'ㄸ': '샹5디5욷1', 'ᄄ': '샹5디5욷1',
        'ㄹ': '리5일1', 'ᄅ': '리5일1', 'ᆯ': '리5일1',
        'ㅁ': '미5음4', 'ᄆ': '미5음4', 'ᆷ': '미5음4',
        'ㅂ': '비5얍1', 'ᄇ': '비5얍1', 'ᆸ': '비5얍1',
        'ㅃ': '샹5비5얍1', 'ᄈ': '샹5비5얍1',
        'ㅅ': '시5오1', 'ᄉ': '시5오1', 'ᆺ': '시5오1',
        'ㅇ': '이5응1', 'ᄋ': '이5응1', 'ᆼ': '이5응1',
        'ㆆ': 'ᄐᅷ3이5응1', 'ᅙ': 'ᄐᅷ3이5응1',
        'ㅈ': '지5웆1', 'ᄌ': '지5웆1', 'ᆽ': '지5웆1',
        'ㅉ': '샹5지5웆1', 'ᄍ': '샹5지5웆1',
        'ㅊ': '치1웇', 'ᄎ': '치1웇', 'ᆾ': '치1웇',
        'ㅋ': '키1역', 'ᄏ': '키1역', 'ᆿ': '키1역',
        'ㅌ': '티1욷', 'ᄐ': '티1욷', 'ᇀ': '티1욷',
        'ㅍ': '피1얍', 'ᄑ': '피1얍', 'ᇁ': '피1얍',
        'ㅎ': '히1웋', 'ᄒ': '히1웋', 'ᇂ': '히1웋',
        'ㅀ': '리5일5히5웋', 'ᆶ': '리5일5히5웋',
    }
    return readings


JAMO_PRONUNCIATION_READINGS = build_jamo_pronunciation_readings()


def jamo_pronunciation_at(text: str, index: int) -> tuple[str, int] | None:
    two = text[index:index + 2]
    if two in JAMO_PRONUNCIATION_READINGS:
        return JAMO_PRONUNCIATION_READINGS[two], index + 2
    one = text[index:index + 1]
    if (
        one
        and is_hangul_consonant(one)
        and index + 1 < len(text)
        and is_jamo(text[index + 1])
    ):
        return None
    if one in JAMO_PRONUNCIATION_READINGS:
        return JAMO_PRONUNCIATION_READINGS[one], index + 1
    return None


def is_latin_word_start(ch: str) -> bool:
    return ('A' <= ch <= 'Z') or ('a' <= ch <= 'z')


def latin_word_end(text: str, index: int) -> int:
    end = index
    while end < len(text) and (
        ('A' <= text[end] <= 'Z')
        or ('a' <= text[end] <= 'z')
        or ('0' <= text[end] <= '9')
    ):
        end += 1
    return end


TONE_SANDHI_MAP = {
    '1': '5',
    '5': '3',
    '3': '2',
    '2': '1',
    '4': '3',
}
CHECKED_TONE_SANDHI_MAP = {
    '1': '3',
    '3': '1',
}

# Reverse the normal surface/sandhi tone back to the citation tone stored in
# hokkien_hanri_dict.tsv.  The main open-tone cycle is unambiguous in reverse
# except sandhi tone 3, because citation tone 4 also sandhis to 3.  For a new
# bracketed entry, tone 3 follows the main 1→5→3→2→1 cycle and therefore
# defaults back to citation tone 5.
SANDHI_TO_CITATION_MAP = {
    '1': '2',
    '2': '3',
    '3': '5',
    '5': '1',
}
CHECKED_SANDHI_TO_CITATION_MAP = {
    '1': '3',
    '3': '1',
}
CHECKED_FINALS_FOR_SANDHI = {'ᆨ', 'ᆮ', 'ᆸ', 'ᇂ', 'ᆶ'}
SANDHI_EQUIVALENT_FINALS = {
    'ᆽ': 'ᆮ',
    'ᆾ': 'ᇂ',
}
HANRI_TSV_FILENAME = "hokkien_hanri_dict.tsv"
DEFAULT_HANRI_TSV_PATH = Path(__file__).resolve().with_name(HANRI_TSV_FILENAME)
_HANRI_READING_INDEX: dict[str, list[dict]] | None = None
_HANRI_READING_KEYS: list[str] | None = None
_MIXED_HANRI_READING_INDEX: dict[str, list[dict]] | None = None
_MIXED_HANRI_READING_KEYS: list[str] | None = None
_HANGUL_OVERRIDE_INDEX: dict[str, str] | None = None
_HANGUL_OVERRIDE_KEYS: list[str] | None = None

def decompose_precomposed_to_jamo(syll: str):
    """Return (initial_jamo, medial_jamo, final_jamo_or_empty) for a precomposed Hangul syllable."""
    idx = ord(syll) - 0xAC00
    lead_idx  = idx // 588
    vowel_idx = (idx % 588) // 28
    final_idx = idx % 28

    initial = chr(0x1100 + lead_idx)
    medial  = chr(0x1161 + vowel_idx)
    final   = chr(0x11A7 + final_idx) if final_idx else ''
    return initial, medial, final

def canonicalize_sandhi_final_jamo(final: str) -> str:
    return SANDHI_EQUIVALENT_FINALS.get(final, final)

def final_jamo_before_tone(reading: str, tone_index: int) -> str:
    if tone_index <= 0:
        return ''
    ch = reading[tone_index - 1]
    if is_hangul_precomposed(ch):
        _initial, _medial, final = decompose_precomposed_to_jamo(ch)
        return final
    if is_hangul_jongseong(ch):
        return ch
    return ''

def is_checked_final_before_tone(reading: str, tone_index: int) -> bool:
    final = canonicalize_sandhi_final_jamo(final_jamo_before_tone(reading, tone_index))
    return final in CHECKED_FINALS_FOR_SANDHI

def last_tone_digit_index(reading: str) -> int | None:
    for idx in range(len(reading) - 1, -1, -1):
        if reading[idx] in TONE_DIGITS:
            return idx
    return None

def final_hangul_unit_needs_implicit_tone(reading: str) -> tuple[int, str] | None:
    for idx in range(len(reading) - 1, -1, -1):
        if is_hangul_precomposed(reading[idx]) or is_jamo(reading[idx]):
            if idx + 1 < len(reading) and reading[idx + 1] in TONE_DIGITS:
                return None
            return idx + 1, reading[:idx + 1] + '3' + reading[idx + 1:]
    return None

def citation_to_sandhi_reading(reading: str) -> str | None:
    reading = normalize_tone_symbols_to_digits(str(reading or ''))
    implicit = final_hangul_unit_needs_implicit_tone(reading)
    if implicit is not None:
        idx, reading = implicit
    else:
        idx = last_tone_digit_index(reading)

    if idx is None:
        return None

    citation_tone = reading[idx]
    if citation_tone not in TONE_DIGITS:
        return None

    if is_checked_final_before_tone(reading, idx):
        sandhi_tone = CHECKED_TONE_SANDHI_MAP.get(citation_tone)
    else:
        sandhi_tone = TONE_SANDHI_MAP.get(citation_tone)

    if not sandhi_tone or sandhi_tone == citation_tone:
        return None
    return reading[:idx] + sandhi_tone + reading[idx + 1:]


def sandhi_to_citation_reading_options(reading: str) -> list[dict]:
    """Return every valid citation-tone reversal for the final surface tone.

    Open-syllable surface tone 3 is ambiguous in the current sandhi system:
        citation tone 4 -> sandhi tone 3
        citation tone 5 -> sandhi tone 3

    Therefore a non-final unmarked reading such as 좐 returns both 좐4 and 좐5.
    Other surface tones, and checked-final tones, return at most one option.
    """
    reading = normalize_tone_symbols_to_digits(str(reading or ''))

    implicit = final_hangul_unit_needs_implicit_tone(reading)
    if implicit is not None:
        idx, reading = implicit
    else:
        idx = last_tone_digit_index(reading)

    if idx is None:
        return []

    sandhi_tone = reading[idx]
    if sandhi_tone not in TONE_DIGITS:
        return []

    if is_checked_final_before_tone(reading, idx):
        citation_tones = [CHECKED_SANDHI_TO_CITATION_MAP.get(sandhi_tone)]
    elif sandhi_tone == '3':
        citation_tones = ['4', '5']
    else:
        citation_tones = [SANDHI_TO_CITATION_MAP.get(sandhi_tone)]

    options = []
    seen = set()
    for citation_tone in citation_tones:
        if not citation_tone or citation_tone == sandhi_tone:
            continue

        # Tone 3 is unmarked in the TSV.
        if citation_tone == '3':
            candidate = reading[:idx] + reading[idx + 1:]
        else:
            candidate = reading[:idx] + citation_tone + reading[idx + 1:]

        key = (citation_tone, candidate)
        if key in seen:
            continue
        seen.add(key)
        options.append({
            'tone': citation_tone,
            'reading': candidate,
        })

    return options


def sandhi_to_citation_reading(reading: str) -> str | None:
    """Return the default reverse-sandhi reading for compatibility.

    When surface tone 3 is ambiguous, tone 5 remains the automatic fallback for
    non-interactive callers.  The IME popup uses sandhi_to_citation_reading_options()
    and asks the user to choose tone 4 or tone 5 instead.
    """
    options = sandhi_to_citation_reading_options(reading)
    if not options:
        return None

    for option in options:
        if option.get('tone') == '5':
            return option.get('reading')
    return options[0].get('reading')


def special_rime_oe_yeo(medial: str, final: str) -> str | None:
    """
    Special vowel+final logic for:
      ㅓ (ᅥ) and ㅕ (ᅧ)
    Returns the rime string if handled, else None.
    """
    # ㅓ (ᅥ)
    if medial == 'ᅥ':
        if final == 'ᆯ':      # ㄹ
            return nasalize_lomari_rime("or")
        if final == 'ᆶ':      # ㅀ
            return nasalize_lomari_rime("or") + "h"
        if final == '':       # no final
            return "or"
        if final == 'ᇂ':      # ㅎ
            return "orh"
        # ㅇ-final keeps plain "o"
        if final == 'ᆼ':
            return "o" + JONGSEONG_TO_Lomari.get(final, "")

        # any other final: "or" + final
        return "or" + JONGSEONG_TO_Lomari.get(final, "")

    # ㅕ (ᅧ)
    if medial == 'ᅧ':
        if final == 'ᆯ':      # ㄹ
            return nasalize_lomari_rime("ior")
        if final == 'ᆶ':      # ㅀ
            return nasalize_lomari_rime("ior") + "h"
        if final == '':       # no final
            return "ior"
        if final == 'ᇂ':      # ㅎ
            return "iorh"
        if final == 'ᆼ':      # ㅇ
            return "io" + JONGSEONG_TO_Lomari.get(final, "")
        # other finals
        return "ior" + JONGSEONG_TO_Lomari.get(final, "")

    return None

VOWELS = set("aeiou")

def double_final_vowel(rime: str) -> str:
    """
    Mark nasalisation on the same target letter used for tone marks.
    Assumes rime is unaccented (tone digits will be applied later).
    Examples:
      "a" -> "a̰"
      "e" -> "ḛ"
      "ai" -> "a̰i"
      "iau" -> "ia̰u"
      "or" -> "o̰r"
    """
    return nasalize_lomari_rime(rime)

def glide_if_null_initial(initial: str, medial: str, rime: str) -> str:
    """
    Rule:
      If initial is ㅇ and medial is a compound vowel (NOT plain ㅣ/ㅜ),
      then romanisation should begin with y/w instead of i/u.

    Examples:
      ㅇ + ᅣ : ia  -> ya
      ㅇ + ᆤ : iau -> yau
      ㅇ + ᅧ : ior -> yor
      ㅇ + ᅨ : ie  -> ye
      ㅇ + ᅰ : ue  -> we
      ㅇ + ᅱ : ui  -> wi
      ㅇ + ᅲ : iu  -> yu
    """
    if initial != 'ᄋ':
        return rime

    # exclude plain ㅣ, ㅜ and ㅢ
    if medial in ('ᅵ', 'ᅮ', 'ᅴ'):
        return rime

    if rime.startswith('i'):
        return 'y' + rime[1:]
    if rime.startswith('u'):
        return 'w' + rime[1:]

    return rime

def cluster_to_base_lomari(initial: str, medial: str, final: str) -> str:
    ini = CHOSEONG_TO_Lomari.get(initial, '')

    # ㅡ (ᅳ) + ㄴ keeps the vowel silent.
    # e.g. 근 (ᄀ + ᅳ + ᆫ) -> kn, 끈 -> gn
    # IMPORTANT: ᅳ normally has empty vowel value, so handle ᅳ+ㄴ here.
    if medial == 'ᅳ' and final == 'ᆫ':
        return ini + "n"

    # Special-case ㅓ/ㅕ with final-dependent behaviour
    rime = special_rime_oe_yeo(medial, final)
    if rime is not None:
        rime = glide_if_null_initial(initial, medial, rime)
        return ini + rime

    # General vowel + ㄹ rule -> mark nasalisation on the tone-target letter.
    # (so 알1 becomes a̰1 -> â̰ after tone-marking)
    if final == 'ᆯ':  # ㄹ
        vow  = JUNGSEONG_TO_Lomari.get(medial, '')
        rime = double_final_vowel(vow)
        rime = glide_if_null_initial(initial, medial, rime)
        return ini + rime

    # L-final clusters: double vowel (like final ㄹ), then append coda
    # ㅀ ㄺ ᇍ ᇎ ㄻ ㄼ ㄾ  ->  h k n t m p t
    L_CLUSTER_FINALS = {
        'ᆶ': 'h',  # ㅀ
        'ᆰ': 'k',  # ㄺ
        'ᇍ': 'n',  # custom final-n
        'ᇎ': 't',  # custom final-t
        'ᆱ': 'm',  # ㄻ
        'ᆲ': 'p',  # ㄼ
        'ᆴ': 't',  # ㄾ
    }

    if final in L_CLUSTER_FINALS:
        vow  = JUNGSEONG_TO_Lomari.get(medial, '')
        rime = double_final_vowel(vow)              # same behaviour as ㄹ rule
        rime = glide_if_null_initial(initial, medial, rime)
        return ini + rime + L_CLUSTER_FINALS[final]

    # default behaviour for everything else
    vow = JUNGSEONG_TO_Lomari.get(medial, '')
    fin = JONGSEONG_TO_Lomari.get(final, '')
    rime = vow + fin
    rime = glide_if_null_initial(initial, medial, rime)
    return ini + rime

def auto_lomari_from_hangul(raw: str) -> str:
    raw = normalize_yyae(raw)
    raw = normalize_apostrophes(raw)
    raw = normalize_compat_jamo(raw)
    raw = normalize_annotation_tones(raw)

    out = []
    i = 0
    prev_was_syllable = False

    def append_sep_if_needed():
        nonlocal prev_was_syllable
        if prev_was_syllable:
            out.append("-")  # join syllables inside a “word”

    def standalone_special_medial_at(index: int) -> tuple[str, int] | None:
        if index + 1 >= len(raw):
            return None
        if raw[index] != hangul_choseong_filler or raw[index + 1] not in special_jamo:
            return None
        base = JUNGSEONG_TO_Lomari.get(raw[index + 1], raw[index + 1])
        end = index + 2
        if end < len(raw) and raw[end] in TONE_DIGITS:
            return base + raw[end], end + 1
        return base, end

    while i < len(raw):
        c = raw[i]

        # bracket handling: romanise Hangul inside [ ... ], ignore non-Hangul (e.g. Chinese), drop brackets
        if c == '[':
            i += 1

            while i < len(raw) and raw[i] != ']':
                c2 = raw[i]

                # whitespace inside bracket: keep and break syllable chain
                if c2.isspace():
                    out.append(c2)
                    i += 1
                    prev_was_syllable = False
                    continue

                # punctuation inside bracket: keep and break syllable chain
                if c2 in ",.!?:;‘’'‧~()“”":
                    out.append(c2)
                    i += 1
                    prev_was_syllable = False
                    continue

                # explicit hyphen marker
                if c2 == '-':
                    out.append("-")
                    i += 1
                    prev_was_syllable = False
                    continue

                # dash variants
                if c2 in "–—":
                    out.append("—")
                    i += 1
                    prev_was_syllable = False
                    continue

                jamo_pronunciation = jamo_pronunciation_at(raw, i)
                if jamo_pronunciation is not None:
                    append_sep_if_needed()
                    reading, i = jamo_pronunciation
                    out.append(auto_lomari_from_hangul(reading))
                    prev_was_syllable = True
                    continue

                standalone = standalone_special_medial_at(i)
                if standalone is not None:
                    append_sep_if_needed()
                    base, i = standalone
                    out.append(base)
                    prev_was_syllable = True
                    continue

                if c2 == 'ㅀ':
                    append_sep_if_needed()
                    out.append('ⁿh')
                    i += 1
                    prev_was_syllable = True
                    continue

                # A) precomposed hangul syllable + optional tone digit
                if is_hangul_precomposed(c2):
                    append_sep_if_needed()

                    # Special standalone vowel symbol:
                    # ힻ = er
                    if c2 == 'ힻ':
                        base = 'er'

                        if i + 1 < len(raw) and raw[i+1] in TONE_DIGITS:
                            out.append(base + raw[i+1])
                            i += 2
                        else:
                            out.append(base)
                            i += 1

                        prev_was_syllable = True
                        continue

                    initial, medial, final = decompose_precomposed_to_jamo(c2)

                # B) jamo-cluster + optional tone digit
                if is_hangul_consonant(c2) and i + 1 < len(raw) and is_jamo(raw[i+1]):
                    append_sep_if_needed()

                    initial = c2
                    medial  = raw[i+1]
                    j = i + 2
                    final = ''
                    if j < len(raw) and is_hangul_jongseong(raw[j]):
                        final = raw[j]
                        j += 1

                    base = cluster_to_base_lomari(initial, medial, final)

                    if j < len(raw) and raw[j] in TONE_DIGITS:
                        out.append(base + raw[j])
                        i = j + 1
                    else:
                        out.append(base)
                        i = j

                    prev_was_syllable = True
                    continue

                # otherwise (e.g. Chinese chars): ignore
                i += 1

            # skip closing ']'
            if i < len(raw) and raw[i] == ']':
                i += 1

            continue

        # whitespace: keep, and reset syllable-joining
        if c.isspace():
            out.append(c)
            i += 1
            prev_was_syllable = False
            continue

        # punctuation: keep, and reset syllable-joining
        if c in ",.!?:;‘’'‧~()“”":
            out.append(c)
            i += 1
            prev_was_syllable = False
            continue

        if is_latin_word_start(c):
            latin_end = latin_word_end(raw, i)
            append_sep_if_needed()
            out.append(raw[i:latin_end])
            i = latin_end
            prev_was_syllable = True
            continue

        # explicit hyphen marker
        if c == '-':
            out.append("-")
            i += 1
            prev_was_syllable = False
            continue

        # explicit hyphen/dash in source: keep it (don’t auto-add another)
        if c in "–—":
            out.append("—")
            i += 1
            prev_was_syllable = False
            continue

        jamo_pronunciation = jamo_pronunciation_at(raw, i)
        if jamo_pronunciation is not None:
            append_sep_if_needed()
            reading, i = jamo_pronunciation
            out.append(auto_lomari_from_hangul(reading))
            prev_was_syllable = True
            continue

        standalone = standalone_special_medial_at(i)
        if standalone is not None:
            append_sep_if_needed()
            base, i = standalone
            out.append(base)
            prev_was_syllable = True
            continue

        if c == 'ㅀ':
            append_sep_if_needed()
            out.append('ⁿh')
            i += 1
            prev_was_syllable = True
            continue

        # A) precomposed hangul syllable + optional tone digit
        if is_hangul_precomposed(c):
            append_sep_if_needed()

            initial, medial, final = decompose_precomposed_to_jamo(c)

            has_tone = (i + 1 < len(raw) and raw[i+1] in TONE_DIGITS)

            # ✅ EXCEPTION: 까 with NO tone → ka
            if (
                not has_tone
                and initial == 'ᄁ'
                and medial == 'ᅡ'
                and final == ''
            ):
                base = 'ka'
            else:
                base = cluster_to_base_lomari(initial, medial, final)

            if has_tone:
                out.append(base + raw[i+1])
                i += 2
            else:
                out.append(base)
                i += 1

            prev_was_syllable = True
            continue

        # B) jamo-cluster + optional tone digit
        if is_hangul_consonant(c) and i + 1 < len(raw) and is_jamo(raw[i+1]):
            append_sep_if_needed()

            initial = c
            medial  = raw[i+1]
            j = i + 2
            final = ''
            if j < len(raw) and is_hangul_jongseong(raw[j]):
                final = raw[j]
                j += 1

            base = cluster_to_base_lomari(initial, medial, final)

            if j < len(raw) and raw[j] in TONE_DIGITS:
                out.append(base + raw[j])
                i = j + 1
            else:
                out.append(base)
                i = j

            prev_was_syllable = True
            continue

        # fallback: keep char, but break syllable chain
        out.append(c)
        i += 1
        prev_was_syllable = False

    # convert digits -> diacritics (your existing tone engine)
    return convert_tone_string("".join(out))

# ==== 4. RUBY‐WRAPPING STEPS ====
def step2_process_precomposed(text: str) -> str:
    tone_map = {'1':'ꞈ','2':'ˎ','4':'ˏ','5':'ˍ'}
    out, i = "", 0
    while i < len(text):
        c = text[i]
        if is_hangul_precomposed(c) and i+1 < len(text) and text[i+1] in tone_map:
            t = tone_map[text[i+1]]
            out += (
                f"<ruby style=\"position: relative\">{c}"
                f"<rt style=\"font-size: 120%;position: absolute;top: -1.15em;left: 0.2em;z-index: -1\">{t}</rt>"
                f"</ruby>"
            )
            i += 1
        elif is_hangul_precomposed(c) and i+1 < len(text) and text[i+1] == '3':
            out += c
            i += 1
        else:
            out += c
        i += 1
    return out

def step3_process_special_jamo(text: str) -> str:
    tone_map = {'1':'ꞈ','2':'ˎ','4':'ˏ','5':'ˍ'}
    out, i, buf = "", 0, ""
    while i < len(text):
        c = text[i]
        if c in special_jamo:
            grp = buf + c if buf else c
            buf = ""
            if i+1 < len(text) and is_hangul_jongseong(text[i+1]):
                grp += text[i+1]; i += 1
            if i+1 < len(text) and text[i+1] in tone_map:
                t = tone_map[text[i+1]]
                out += (
                    f"<ruby style=\"position: relative\">{grp}"
                    f"<rt style=\"font-size: 120%;position: absolute;top: -1.15em;left: 0.2em;z-index: -1\">{t}</rt>"
                    f"</ruby>"
                )
                i += 1
            elif i+1 < len(text) and text[i+1] == '3':
                out += grp
                i += 1
            else:
                out += grp
        elif is_hangul_consonant(c):
            buf = c
        else:
            if buf:
                out += buf; buf = ""
            out += c
        i += 1
    if buf:
        out += buf
    return out

def step4_process_extra_consonants(text: str) -> str:
    tone_map = {'1':'ꞈ','2':'ˎ','4':'ˏ','5':'ˍ'}
    out, i = "", 0
    while i < len(text):
        c = text[i]
        if is_hangul_consonant(c) and i+1 < len(text) and text[i+1] not in extra_consonants:
            grp = c + text[i+1]; i += 1
            if i+1 < len(text) and is_hangul_jongseong(text[i+1]):
                grp += text[i+1]; i += 1
            if i+1 < len(text) and text[i+1] in tone_map:
                t = tone_map[text[i+1]]
                out += (
                    f"<ruby style=\"position: relative\">{grp}"
                    f"<rt style=\"font-size: 120%;position: absolute;top: -1.15em;left: 0.2em;z-index: -1\">{t}</rt>"
                    f"</ruby>"
                )
                i += 1
            elif i+1 < len(text) and text[i+1] == '3':
                out += grp
                i += 1
            else:
                out += grp
        else:
            out += c
        i += 1
    return out

# ==== 5. GLOSS LANGUAGE DETECTION ====
# 1) define your list of Malay words/phrases
malay_keywords = [
    "ais kacang", "atas", "baru", "kacang", "kacau",
    "lokun", "nasi lemak", "pasat", "roti", "sabun",
    "salah", "sayang", "sombong", "suka", "tahan",
    "tapi", "tolong"
    # …etc…
]

# 2) build one big regex alternation, escaping each entry
malay_pattern = re.compile(
    r'\b(?:' + 
      '|'.join(re.escape(w) for w in malay_keywords) +
    r')\b',
    re.IGNORECASE
)

def detect_language_code(gloss: str) -> str:
    # strip out hyphens and any &#45; entities
    clean = gloss.replace('-', '').replace('&#45;', '')
    # Chinese
    if clean and all(is_cjk_char(ch) for ch in clean):
        return "漢"
    # Japanese
    if re.fullmatch(r'[\u3040-\u30FF\uFF66-\uFF9F]+', clean):
        return "和"
    # Malay
    if malay_pattern.search(gloss):
        return "ms"
    # fallback to English
    return "en"

def contains_cjk(s: str) -> bool:
    return any(is_cjk_char(ch) for ch in s)


def infer_hanri_phrase_reading_from_tsv(hanri_text: str) -> str | None:
    """Infer a bracket reading from TSV-backed Hanri segments."""
    text = str(hanri_text or '').strip()
    if not text or not all(is_cjk_char(ch) for ch in text):
        return None

    out: list[str] = []
    i = 0
    while i < len(text):
        match = tsv_hanri_segment_for_run(text, i)
        if not match:
            return None
        hanri_word, reading = match
        if not hanri_word or not reading:
            return None
        next_i = i + len(hanri_word)
        if next_i <= i:
            return None
        if next_i < len(text):
            reading = citation_to_sandhi_reading(reading) or reading
        out.append(reading)
        i = next_i

    inferred = ''.join(out)
    if not inferred:
        return None
    return hangul_digits_to_annotation_symbols(normalize_yyae(inferred))


def is_inferred_hanri_only_bracket(inner: str) -> bool:
    text = str(inner or '').strip()
    return bool(text) and all(is_cjk_char(ch) for ch in text) and infer_hanri_phrase_reading_from_tsv(text) is not None


def split_hanri_hangul_bracket(inner: str):
    """
    Detect new Hanri-Hangul annotation format:

      [Hanri + Hangul]

    Examples:
      [人生띤솅1]
      [海海해1해2]

    Returns:
      (hanri_word, hangul_reading)

    If the bracket is not Hanri-first, return None.
    """
    inner = inner.strip()

    if inner and all(is_cjk_char(ch) for ch in inner):
        inferred_reading = infer_hanri_phrase_reading_from_tsv(inner)
        if inferred_reading:
            return inner, inferred_reading

    split_at = 0
    while split_at < len(inner) and is_cjk_char(inner[split_at]):
        split_at += 1

    if split_at <= 0 or split_at >= len(inner):
        return None

    hanri_word = inner[:split_at].strip()
    hangul_reading = inner[split_at:].strip()

    # Special classifier normalization:
    # 一個 / 兩個 / 三個 etc. -> 个
    # But do NOT affect 個人, 個性, 個體, etc.
    if hanri_word.endswith("個"):
        prefix = hanri_word[:-1]

        # Only convert when preceded by Chinese numerals
        if prefix and all(ch in "一二三四五六七八九十兩兩幾這那每逐" for ch in prefix):
            hanri_word = prefix + "个"

    if not contains_hangul_or_jamo(hangul_reading):
        return None

    hangul_reading = clean_chinese_annotation_hangul_input(hangul_reading)

    if not hangul_reading:
        return None

    return hanri_word, hangul_reading


def hanri_hangul_bracket_annotations(text: str) -> list[dict]:
    """Return bracket annotations prepared for new TSV entries.

    A bracketed reading is written as it sounds in the sentence.  If the closing
    bracket is immediately followed by another readable Hanri/Hangul unit, the
    bracketed item is non-final and its surface sandhi tone is reversed back to
    citation tone before it is offered for TSV saving.

    Open-syllable surface tone 3 is ambiguous because citation tone 4 and tone 5
    both sandhi to tone 3.  In that case reverse_sandhi_options contains both
    choices so the IME can ask the user which citation tone belongs in the TSV.

    Space or punctuation after the bracket keeps the reading unchanged.
    """
    source_text = str(text or '')
    annotations = []

    for match in re.finditer(r'\[([^\]]+)\]', source_text):
        inner = match.group(1)
        inferred_hanri_only = is_inferred_hanri_only_bracket(inner)
        parsed = split_hanri_hangul_bracket(inner)
        if not parsed:
            continue

        hanri_word, hangul_reading = parsed
        surface_reading = normalize_annotation_tones(hangul_reading)
        if inferred_hanri_only and is_followed_by_hanri(source_text, match.end() - 1):
            surface_reading = citation_to_sandhi_reading(surface_reading) or surface_reading
        reading_digits = surface_reading
        reverse_sandhi_options = []

        if is_followed_by_hanri(source_text, match.end() - 1):
            reverse_sandhi_options = sandhi_to_citation_reading_options(surface_reading)
            if reverse_sandhi_options:
                # Keep tone 5 as the non-interactive/default compatibility value.
                preferred = next(
                    (item for item in reverse_sandhi_options if item.get('tone') == '5'),
                    reverse_sandhi_options[0],
                )
                reading_digits = preferred.get('reading', surface_reading)

        annotations.append({
            'hanri': hanri_word,
            'reading': reading_digits,
            'display': hangul_digits_to_annotation_symbols(normalize_yyae(reading_digits)),
            'surface_reading': surface_reading,
            'surface_display': hangul_digits_to_annotation_symbols(normalize_yyae(surface_reading)),
            'sandhi_reversed': reading_digits != surface_reading,
            'reverse_sandhi_options': reverse_sandhi_options,
        })

    return annotations


def sandhi_bracket_reading_if_followed(text: str, closing_bracket_index: int, reading: str) -> str:
    j = closing_bracket_index + 1
    follows_protected_hanri = (
        j < len(text)
        and text.startswith("@@KNOWN_HANRI_", j)
        and text.find("@@", j + 2) != -1
    )

    if is_followed_by_hanri(text, closing_bracket_index) or follows_protected_hanri:
        return citation_to_sandhi_reading(reading) or reading
    return reading


def hanri_tsv_path_for_write() -> Path:
    env_path = os.environ.get("HOKKIEN_HANRI_DICT_PATH")
    if env_path:
        return Path(env_path)
    for path in hanri_tsv_candidates():
        if path.exists():
            return path
    return DEFAULT_HANRI_TSV_PATH


def hanri_reading_entry_exists(hanri: str, reading: str) -> bool:
    target_hanri = str(hanri or '').strip()
    target_reading = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(reading))
    for path in hanri_tsv_candidates():
        if not path.exists():
            continue
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            rows = [row for row in csv.reader(f, delimiter='\t') if any(cell.strip() for cell in row)]
        if not rows:
            continue
        header = [cell.strip().lower() for cell in rows[0]]
        has_header = 'reading' in header and 'hanri' in header
        reading_col = header.index('reading') if has_header else 0
        hanri_col = header.index('hanri') if has_header else 1
        data_rows = rows[1:] if has_header else rows
        for row in data_rows:
            row_reading = row[reading_col].strip() if len(row) > reading_col else ''
            row_hanri = row[hanri_col].strip() if len(row) > hanri_col else ''
            if (
                row_hanri == target_hanri
                and normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(row_reading)) == target_reading
            ):
                return True
        break
    return False


def existing_hanri_readings(hanri: str) -> list[str]:
    """Return TSV readings already stored for this exact Hanri text."""
    target_hanri = str(hanri or '').strip()
    if not target_hanri:
        return []

    readings: list[str] = []
    seen: set[str] = set()
    for path in hanri_tsv_candidates():
        if not path.exists():
            continue
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            rows = [row for row in csv.reader(f, delimiter='\t') if any(cell.strip() for cell in row)]
        if not rows:
            continue
        header = [cell.strip().lower() for cell in rows[0]]
        has_header = 'reading' in header and 'hanri' in header
        reading_col = header.index('reading') if has_header else 0
        hanri_col = header.index('hanri') if has_header else 1
        data_rows = rows[1:] if has_header else rows
        for row in data_rows:
            row_reading = row[reading_col].strip() if len(row) > reading_col else ''
            row_hanri = row[hanri_col].strip() if len(row) > hanri_col else ''
            if row_hanri != target_hanri:
                continue
            reading = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(row_reading))
            if reading and reading not in seen:
                readings.append(reading)
                seen.add(reading)
        break
    return readings


def append_hanri_reading_to_tsv(hanri: str, reading: str) -> bool:
    global _HANRI_READING_INDEX, _HANRI_READING_KEYS, _MIXED_HANRI_READING_INDEX, _MIXED_HANRI_READING_KEYS, _HANGUL_OVERRIDE_INDEX, _HANGUL_OVERRIDE_KEYS
    hanri = str(hanri or '').strip()
    reading = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(reading))
    if not hanri or not reading:
        return False
    if hanri_reading_entry_exists(hanri, reading):
        return False

    path = hanri_tsv_path_for_write()
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = path.exists() and path.stat().st_size > 0
    with path.open('a', encoding='utf-8', newline='') as f:
        if needs_newline:
            with path.open('rb') as existing:
                existing.seek(-1, os.SEEK_END)
                if existing.read(1) not in {b'\n', b'\r'}:
                    f.write('\n')
        writer = csv.writer(f, delimiter='\t', lineterminator='\n')
        writer.writerow([reading, hanri, '1', ''])

    _HANRI_READING_INDEX = None
    _HANRI_READING_KEYS = None
    _MIXED_HANRI_READING_INDEX = None
    _MIXED_HANRI_READING_KEYS = None
    _HANGUL_OVERRIDE_INDEX = None
    _HANGUL_OVERRIDE_KEYS = None
    return True


def protect_hanri_hangul_annotations(
    text: str,
    include_lomari_title: bool = True,
    use_wiktionary: bool = False,
):
    """
    Replace [Hanri + Hangul] blocks with safe placeholders before
    convert_segment_to_ruby() processes the sentence.

    This prevents the Hangul reading inside <rt> from being converted
    into nested <ruby> HTML.
    """
    protected = {}

    def repl(m):
        inner = m.group(1)
        explicit_continuation_marker = bool(m.group(2))
        inferred_hanri_only = is_inferred_hanri_only_bracket(inner)
        parsed = split_hanri_hangul_bracket(inner)

        if not parsed:
            return m.group(0)

        hanri_word, hangul_reading = parsed
        # Explicit [Hanri+Hangul] annotations already contain the surface
        # pronunciation exactly as typed by the user.  Do not apply forward
        # sandhi here: reverse sandhi is only for preparing a possible new TSV
        # citation-form entry in hanri_hangul_bracket_annotations().
        #
        # A bracketed reading may also be injected internally by the IME to
        # remember which TSV pronunciation produced this exact Hanri instance.
        # In either case, if it is immediately followed by another readable
        # unit, keep the visual ruby-continuation hyphen that automatic Hanri
        # annotations use.
        continuation_hyphen = (
            explicit_continuation_marker
            or
            is_followed_by_hanri(text, m.end() - 1)
            or text.startswith('@@KNOWN_HANRI_', m.end())
        )
        if (
            continuation_hyphen
            and (
                inferred_hanri_only
                or (
                    explicit_continuation_marker
                    and last_tone_digit_index(normalize_annotation_tones(hangul_reading)) is None
                )
            )
        ):
            hangul_reading = citation_to_sandhi_reading(hangul_reading) or hangul_reading

        key = f"@@HANRI_ANNOTATION_{len(protected)}@@"
        protected[key] = annotate_chinese_word(
            hanri_word,
            hangul_reading,
            use_wiktionary=use_wiktionary,
            include_lomari_title=include_lomari_title,
            continuation_hyphen=continuation_hyphen,
        )

        return key + ('-' if explicit_continuation_marker else '')

    text = re.sub(r'\[([^\]]+)\](-?)', repl, text)
    return text, protected


def restore_hanri_hangul_annotations(text: str, protected: dict) -> str:
    for key, value in protected.items():
        text = text.replace(key, value)
    return text

# ==== HANRI AUTO-READING DICTIONARY ====

def is_cjk_char(ch: str) -> bool:
    code = ord(ch) if ch else 0
    return (
        0x3400 <= code <= 0x4DBF      # CJK Extension A
        or 0x4E00 <= code <= 0x9FFF   # CJK Unified Ideographs
        or 0x20000 <= code <= 0x2A6DF # CJK Extension B
    )


def is_followed_by_hanri(text: str, index: int) -> bool:
    """
    Checks whether the Hanri character/word ending at text[index] is immediately
    followed by another readable unit.

    Space or punctuation = citation/final tone.
    Direct Hanri, Hangul, or [Hanri+Hangul] bracket = sandhi tone.
    """
    j = index + 1

    if j >= len(text):
        return False

    # Space means citation/final tone
    if text[j].isspace():
        return False

    # ASCII hyphen is an explicit continuation marker.
    if text[j] == "-":
        return True

    # Punctuation means citation/final tone.
    # Do NOT include [ here, because 來[變볜2] should count as followed.
    if text[j] in ",.!?:;，。！？：；、’'“”()「」『』…‧~":
        return False

    if text.startswith('@@HANRI_ANNOTATION_', j) or text.startswith('@@KNOWN_HANRI_', j):
        return True

    # Directly followed by another Hanri character
    if is_cjk_char(text[j]):
        return True

    # Directly followed by Latin text: keep it in the same Lomari word.
    if is_latin_word_start(text[j]):
        return True

    # Directly followed by Hangul/Jamo
    if (
        is_hangul_precomposed(text[j])
        or is_jamo(text[j])
        or ('\u3130' <= text[j] <= '\u318F')
    ):
        return True

    # Followed by bracketed annotation/gloss
    if text[j] == "[":
        end = text.find("]", j + 1)

        if end == -1:
            return False

        inner = text[j + 1:end].strip()

        if not inner:
            return False

        # New mode: [Hanri + Hangul], e.g. [變볜2]
        if is_cjk_char(inner[0]):
            return True

        # Old mode: [Hangul + Hanri/gloss], e.g. [볜2變]
        if (
            is_hangul_precomposed(inner[0])
            or is_jamo(inner[0])
            or ('\u3130' <= inner[0] <= '\u318F')
        ):
            return True

    return False

def hanri_tsv_candidates() -> list[Path]:
    env_path = os.environ.get("HOKKIEN_HANRI_DICT_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([
        Path(__file__).resolve().with_name(HANRI_TSV_FILENAME),
        DEFAULT_HANRI_TSV_PATH,
        Path.cwd() / HANRI_TSV_FILENAME,
    ])
    seen = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique

def strip_nonstandard_reading_mark(reading: str) -> str:
    return str(reading or '').strip().rstrip('*')

def strip_reading_tones(reading: str) -> str:
    out = []
    for ch in normalize_tone_symbols_to_digits(str(reading or '')):
        if ch in TONE_DIGITS:
            continue
        out.append(ch)
    return ''.join(out)

def safe_priority(value: str, default: int = 9999) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default

def field_contains_cjk(text: str) -> bool:
    return any(is_cjk_char(ch) for ch in str(text or ''))


def field_is_plain_cjk_key(text: str) -> bool:
    value = str(text or '').strip()
    return bool(value) and all(is_cjk_char(ch) for ch in value)

def field_is_mixed_hanri_key(text: str) -> bool:
    value = str(text or '').strip()
    return bool(value) and field_contains_cjk(value) and not field_is_plain_cjk_key(value)

def hangul_override_key(text: str) -> str:
    """Return a tone-free Hangul-only TSV override key.

    A Hangul-only value in the TSV hanri column is an explicit pronunciation/
    tone override.  Earlier converter versions accepted only one Hangul syllable
    or one Hokkien jamo cluster, which meant multi-syllable overrides worked in
    the IME audio/Lomari paths but were ignored by HTML conversion.

    Multi-syllable Hangul sequences are now accepted structurally:
        가ˉ야ˆ      -> 가야
        또디ˆ       -> 또디
        릐ˆ호ˋ      -> 릐호

    CJK, spaces, internal apostrophes, and dash boundaries remain excluded.
    A leading apostrophe is allowed for explicit attached overrides such as
    ’뽀ˊ and ’ᄅᆤˋ.
    """
    raw = normalize_tone_symbols_to_digits(str(text or '').strip())
    if not raw or field_contains_cjk(raw):
        return ''

    attached = raw[0] in {"'", '’', '‘'}
    body = raw[1:] if attached else raw
    if (
        not body
        or any(ch.isspace() or ch in {"'", '’', '‘', '-', '–', '—'} for ch in body)
    ):
        return ''

    base = strip_reading_tones(body)
    if not base:
        return ''

    i = 0
    unit_count = 0
    while i < len(base):
        ch = base[i]

        if is_hangul_precomposed(ch):
            i += 1
            unit_count += 1
            continue

        # Hokkien jamo syllable: initial + medial/jamo + optional jongseong.
        if (
            is_hangul_consonant(ch)
            and i + 1 < len(base)
            and is_jamo(base[i + 1])
        ):
            i += 2
            if i < len(base) and is_hangul_jongseong(base[i]):
                i += 1
            unit_count += 1
            continue

        return ''

    if not unit_count:
        return ''
    return ('’' if attached else '') + base

def load_hanri_reading_index() -> dict[str, list[dict]]:
    global _HANRI_READING_INDEX, _HANRI_READING_KEYS, _MIXED_HANRI_READING_INDEX, _MIXED_HANRI_READING_KEYS, _HANGUL_OVERRIDE_INDEX, _HANGUL_OVERRIDE_KEYS
    if _HANRI_READING_INDEX is not None:
        return _HANRI_READING_INDEX

    index: dict[str, list[dict]] = {}
    mixed_index: dict[str, list[dict]] = {}
    overrides: dict[str, tuple[str, int, int]] = {}
    for path in hanri_tsv_candidates():
        if not path.exists():
            continue

        with path.open('r', encoding='utf-8-sig', newline='') as f:
            rows = [row for row in csv.reader(f, delimiter='\t') if any(cell.strip() for cell in row)]
        if not rows:
            continue

        header = [cell.strip().lower() for cell in rows[0]]
        has_header = 'reading' in header and 'hanri' in header
        if has_header:
            data_rows = rows[1:]
            reading_col = header.index('reading')
            hanri_col = header.index('hanri')
            priority_col = header.index('priority') if 'priority' in header else None
            corrected_col = header.index('corrected') if 'corrected' in header else None
            row_offset = 2
        else:
            data_rows = rows
            reading_col = 0
            hanri_col = 1
            priority_col = 2
            corrected_col = None
            row_offset = 1

        for row_number, row in enumerate(data_rows, start=row_offset):
            reading_cell = row[reading_col].strip() if len(row) > reading_col else ''
            hanri = row[hanri_col].strip() if len(row) > hanri_col else ''
            corrected_cell = row[corrected_col].strip() if corrected_col is not None and len(row) > corrected_col else ''
            if not reading_cell or not hanri:
                continue

            reading = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(reading_cell))
            corrected = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(corrected_cell)) if corrected_cell else ''
            if reading and reading[0].isdigit() and corrected:
                continue

            priority = safe_priority(row[priority_col] if priority_col is not None and len(row) > priority_col else '')
            override_key = hangul_override_key(hanri)
            override_reading = corrected or reading
            if override_key and override_reading:
                existing = overrides.get(override_key)
                if existing is None or (priority, row_number) < (existing[1], existing[2]):
                    overrides[override_key] = (override_reading, priority, row_number)

            entry = {
                'reading': corrected or reading,
                'priority': priority,
                'row': row_number,
            }

            if field_is_mixed_hanri_key(hanri):
                mixed_index.setdefault(hanri, []).append(entry)
                continue

            if not field_is_plain_cjk_key(hanri):
                continue

            index.setdefault(hanri, []).append(entry)

        break

    for entries in index.values():
        entries.sort(key=lambda item: (item['priority'], item['row'], item['reading']))
    for entries in mixed_index.values():
        entries.sort(key=lambda item: (item['priority'], item['row'], item['reading']))

    _HANRI_READING_INDEX = index
    _HANRI_READING_KEYS = sorted(index, key=len, reverse=True)
    _MIXED_HANRI_READING_INDEX = mixed_index
    _MIXED_HANRI_READING_KEYS = sorted(mixed_index, key=len, reverse=True)
    _HANGUL_OVERRIDE_INDEX = {key: value[0] for key, value in overrides.items()}
    _HANGUL_OVERRIDE_KEYS = sorted(_HANGUL_OVERRIDE_INDEX, key=len, reverse=True)
    return _HANRI_READING_INDEX

def apply_hangul_overrides_from_tsv(text: str) -> str:
    load_hanri_reading_index()
    overrides = _HANGUL_OVERRIDE_INDEX or {}
    keys = _HANGUL_OVERRIDE_KEYS or []
    if not overrides:
        return text

    out = []
    i = 0
    post_apostrophe_force_tone3 = False
    tone_symbols = set("12345Ë†`Ë‹ËŠË‰êžˆËŽËË")
    while i < len(text):
        if text[i] == '[':
            end = text.find(']', i + 1)
            if end != -1:
                out.append(text[i:end + 1])
                i = end + 1
                continue

        ch = text[i]
        if ch in {"'", '’', '‘'}:
            normalized_tail = '’' + text[i + 1:]
            for key in keys:
                if key and key[0] in {"'", '’', '‘'} and normalized_tail.startswith('’' + key[1:]):
                    reading = overrides[key]
                    out.append(reading)
                    i += len(key)
                    post_apostrophe_force_tone3 = True
                    break
            else:
                post_apostrophe_force_tone3 = True
                out.append(ch)
                i += 1
            continue
        if ch.isspace():
            post_apostrophe_force_tone3 = False

        matched = False
        if not post_apostrophe_force_tone3:
            mixed_match = mixed_tsv_hanri_match(text, i)
            if mixed_match:
                hanri_key, _reading = mixed_match
                out.append(text[i:i + len(hanri_key)])
                i += len(hanri_key)
                matched = True

        if not matched and not post_apostrophe_force_tone3:
            for key in keys:
                if text.startswith(key, i):
                    after = i + len(key)
                    if after < len(text) and text[after] in tone_symbols:
                        continue
                    reading = overrides[key]
                    if is_followed_by_hanri(text, after - 1):
                        reading = citation_to_sandhi_reading(reading) or reading
                    out.append(reading)
                    i = after
                    matched = True
                    break
        if matched:
            continue

        out.append(text[i])
        i += 1
    return ''.join(out)

def cjk_run_end(text: str, index: int) -> int:
    end = index
    while end < len(text) and is_cjk_char(text[end]):
        end += 1
    return end


def tsv_hanri_segment_for_run(text: str, index: int) -> tuple[str, str] | None:
    """Choose the best TSV-backed first Hanri segment for the current CJK run.

    Scoring is phrase-aware rather than purely greedy: prefer segmentations that
    cover more Hanri characters, then lower summed TSV priority, then fewer
    segments. This lets 用 + 心肝 beat 用心 + unknown 肝 when the TSV priority says
    心肝 is the better phrase.
    """
    readings = load_hanri_reading_index()
    keys = _HANRI_READING_KEYS or []
    if index >= len(text) or not is_cjk_char(text[index]):
        return None

    run_end = cjk_run_end(text, index)
    memo: dict[int, tuple[tuple[int, int, int], tuple[str, str] | None]] = {}

    def best_at(pos: int) -> tuple[tuple[int, int, int], tuple[str, str] | None]:
        if pos >= run_end:
            return (0, 0, 0), None
        if pos in memo:
            return memo[pos]

        best_score = (1_000_000, 1_000_000, 1_000_000)
        best_first: tuple[str, str] | None = None

        for hanri in keys:
            if not hanri or not text.startswith(hanri, pos):
                continue
            after = pos + len(hanri)
            if after > run_end:
                continue
            entries = readings.get(hanri) or []
            if not entries:
                continue
            reading = entries[0].get('reading', '')
            if not reading:
                continue

            rest_score, _rest_first = best_at(after)
            priority = int(entries[0].get('priority', 9999))
            score = (rest_score[0], priority + rest_score[1], 1 + rest_score[2])
            if score < best_score:
                best_score = score
                best_first = (hanri, reading)

        # Allow an unmatched Hanri character so a partly-covered run can still
        # be scored. A complete TSV cover always wins because unmatched count is
        # the first score component.
        rest_score, _rest_first = best_at(pos + 1)
        unmatched_score = (1 + rest_score[0], 9999 + rest_score[1], 1 + rest_score[2])
        if unmatched_score < best_score:
            best_score = unmatched_score
            best_first = None

        memo[pos] = (best_score, best_first)
        return memo[pos]

    _score, first = best_at(index)
    return first


def tsv_hanri_match(text: str, index: int) -> tuple[str, str] | None:
    info = tsv_hanri_match_info(text, index)
    if not info:
        return None
    hanri, reading, _sandhi_applied = info
    return hanri, reading


def tsv_hanri_match_info(text: str, index: int) -> tuple[str, str, bool] | None:
    match = tsv_hanri_segment_for_run(text, index)
    if not match:
        return None
    hanri, reading = match
    sandhi_applied = False
    if is_followed_by_hanri(text, index + len(hanri) - 1):
        sandhi_reading = citation_to_sandhi_reading(reading)
        if sandhi_reading and sandhi_reading != reading:
            reading = sandhi_reading
            sandhi_applied = True
    return hanri, reading, sandhi_applied

def mixed_tsv_hanri_match(text: str, index: int) -> tuple[str, str] | None:
    info = mixed_tsv_hanri_match_info(text, index)
    if not info:
        return None
    hanri, reading, _sandhi_applied = info
    return hanri, reading


def mixed_tsv_hanri_match_info(text: str, index: int) -> tuple[str, str, bool] | None:
    load_hanri_reading_index()
    readings = _MIXED_HANRI_READING_INDEX or {}
    keys = _MIXED_HANRI_READING_KEYS or []

    for hanri in keys:
        if not hanri or not text.startswith(hanri, index):
            continue
        entries = readings.get(hanri) or []
        if not entries:
            continue
        reading = entries[0].get('reading', '')
        if not reading:
            continue
        sandhi_applied = False
        if is_followed_by_hanri(text, index + len(hanri) - 1):
            sandhi_reading = citation_to_sandhi_reading(reading)
            if sandhi_reading and sandhi_reading != reading:
                reading = sandhi_reading
                sandhi_applied = True
        return hanri, reading, sandhi_applied

    return None

def known_hanri_match(text: str, index: int) -> tuple[str, str] | None:
    info = known_hanri_match_info(text, index)
    if not info:
        return None
    hanri, reading, _sandhi_applied = info
    return hanri, reading


def known_hanri_match_info(text: str, index: int) -> tuple[str, str, bool] | None:
    # Two-character vocabulary entries with established special readings first.
    if text.startswith("永遠", index):
        after_index = index + len("永遠") - 1
        followed = is_followed_by_hanri(text, after_index)
        return "永遠", "옝1완1" if followed else "옝1완2", followed

    if text.startswith("親像", index):
        after_index = index + len("親像") - 1
        followed = is_followed_by_hanri(text, after_index)
        return "親像", "친5츌" if followed else "친5츌5", followed

    if text.startswith("天頂", index):
        after_index = index + len("天頂") - 1
        followed = is_followed_by_hanri(text, after_index)
        return "天頂", "틸5뎽1" if followed else "틸5뎽2", followed

    tsv_match = tsv_hanri_match_info(text, index)
    if tsv_match:
        return tsv_match

    ch = text[index] if index < len(text) else ''
    if ch == "講":
        followed = is_followed_by_hanri(text, index)
        return ch, "겅1" if followed else "겅2", followed

    if ch == "問":
        followed = is_followed_by_hanri(text, index)
        return ch, "믕" if followed else "믕5", followed

    if ch == "來":
        followed = is_followed_by_hanri(text, index)
        return ch, "래" if followed else "래4", followed

    return None

def known_hanri_reading(ch: str, text: str, index: int) -> str | None:
    """Return automatic Hangul reading for known or TSV-backed Hanri."""
    match = known_hanri_match(text, index)
    if not match:
        return None
    _hanri_word, reading = match
    return reading

def protect_known_hanri_annotations(
    text: str,
    include_lomari_title: bool = True,
    use_wiktionary: bool = False,
):
    """
    Automatically annotate known Hanri characters in normal sentence mode.

    This skips anything inside [ ... ] so that:
      [人生띤솅1] keeps using explicit Hanri-Hangul annotation
      [띤솅1人生] keeps using old gloss mode

    Known unbracketed Hanri are replaced with placeholders first,
    then restored after normal Hangul ruby conversion.
    """
    protected = {}
    out = []
    i = 0

    while i < len(text):
        ch = text[i]

        # Skip bracketed content completely
        if ch == "[":
            end = text.find("]", i + 1)
            if end == -1:
                out.append(ch)
                i += 1
            else:
                out.append(text[i:end + 1])
                i = end + 1
            continue

        if ch in SC_FONT_HANRI_CHARS:
            key = f"@@KNOWN_HANRI_{len(protected)}@@"
            protected[key] = escape_visible_html_text(ch)
            out.append(key)
            i += 1
            continue

        mixed_match = mixed_tsv_hanri_match_info(text, i)
        if mixed_match:
            hanri_key, reading, sandhi_applied = mixed_match
            continuation_hyphen = is_followed_by_hanri(text, i + len(hanri_key) - 1)
            key = f"@@KNOWN_HANRI_{len(protected)}@@"
            protected[key] = render_mixed_tsv_hanri_match(
                hanri_key,
                reading,
                use_wiktionary=use_wiktionary,
                include_lomari_title=include_lomari_title,
                continuation_hyphen=continuation_hyphen,
            )
            out.append(key)
            i += len(hanri_key)
            continue

        match = known_hanri_match_info(text, i)

        if match:
            hanri_word, reading, sandhi_applied = match
            continuation_hyphen = is_followed_by_hanri(text, i + len(hanri_word) - 1)

            key = f"@@KNOWN_HANRI_{len(protected)}@@"
            protected[key] = annotate_chinese_word(
                hanri_word,
                reading,
                use_wiktionary=use_wiktionary,
                include_lomari_title=include_lomari_title,
                continuation_hyphen=continuation_hyphen,
            )
            out.append(key)
            i += len(hanri_word)
            continue
        else:
            out.append(ch)
            i += 1
            continue

    return "".join(out), protected

def mixed_sentence_to_hangul_reading(text: str) -> str:
    """
    Convert a Hanri-Hangul mixed sentence into Hangul-only reading
    for automatic Lomari generation.

    Handles:
      1. Known Hanri dictionary entries, e.g. 講 → 겅1 / 겅2
      2. Explicit [Hanri + Hangul] annotations, e.g. [話웨5] → 웨5
      3. Normal Hangul text remains as-is
      4. Unknown Hanri is skipped
    """
    out = []
    i = 0

    while i < len(text):
        ch = text[i]

        # Explicit [Hanri + Hangul] annotation
        if ch == "[":
            end = text.find("]", i + 1)

            if end == -1:
                i += 1
                continue

            inner = text[i + 1:end]
            inferred_hanri_only = is_inferred_hanri_only_bracket(inner)
            parsed = split_hanri_hangul_bracket(inner)

            if parsed:
                hanri_word, hangul_reading = parsed
                explicit_continuation_marker = end + 1 < len(text) and text[end + 1] == '-'
                # Keep the explicit surface reading for the Lomari line too.
                # The bracket reading must not be sandhied a second time merely
                # because another bracket/Hanri unit follows it.
                if (
                    (inferred_hanri_only and is_followed_by_hanri(text, end))
                    or (
                        explicit_continuation_marker
                        and last_tone_digit_index(normalize_annotation_tones(hangul_reading)) is None
                    )
                ):
                    hangul_reading = citation_to_sandhi_reading(hangul_reading) or hangul_reading

                if out and out[-1] not in (" ", "-", "—"):
                    out.append("")

                out.append(hangul_reading)
            else:
                # Old [Hangul + gloss] mode:
                # keep only the Hangul side by letting auto_lomari_from_hangul handle it later
                out.append("[" + inner + "]")

            i = end + 1
            continue

        # Mixed TSV-backed entries, e.g. 뽀彩工 -> 뽀채1강1.
        mixed_match = mixed_tsv_hanri_match(text, i)
        if mixed_match:
            hanri_key, reading = mixed_match
            out.append(reading)
            i += len(hanri_key)
            continue

        # Known or TSV-backed Hanri dictionary entry
        match = known_hanri_match(text, i)
        if match:
            hanri_word, reading = match
            out.append(reading)
            i += len(hanri_word)
            continue

        if is_latin_word_start(ch):
            latin_end = latin_word_end(text, i)
            out.append(text[i:latin_end])
            i = latin_end
            continue

        # Keep Hangul/Jamo/tone/punctuation/space
        if (
            is_hangul_precomposed(ch)
            or is_jamo(ch)
            or ch in TONE_DIGITS
            or ch in "ˆ`ˋˊˉꞈˎˏˍ"
            or ch.isspace()
            or ch in ",.!?:;‘’'‧~()“”-—"
        ):
            out.append(ch)

        # Unknown Hanri is skipped for Lomari line
        i += 1

    return "".join(out)

# ==== 6. FINAL WRAPPER ====
def convert_sentence(input_sentence: str) -> str:
    # 0) Count precomposed Hangul syllables in the raw input
    hangul_count = sum(1 for ch in input_sentence if '\uAC00' <= ch <= '\uD7A3')
    has_terminal_punct = any(p in input_sentence for p in ('.', '?', '!'))

    # 1) Protect explicit [Hanri + Hangul] annotations first.
    protected_input, protected_hanri = protect_hanri_hangul_annotations(input_sentence, include_lomari_title)

    # 2) Then protect automatic known Hanri annotations.
    protected_input, protected_known_hanri = protect_known_hanri_annotations(protected_input, include_lomari_title)

    # 3) Convert normal Hangul tones
    processed = convert_segment_to_ruby(protected_input)

    # 4) Old [Hangul + gloss/Hanri] Wiktionary-link mode has been removed.
    # Leaving unmatched brackets as ordinary text is safer than guessing.
    wrapped = processed

    # 5) Restore protected annotations
    wrapped = restore_hanri_hangul_annotations(wrapped, protected_hanri)
    wrapped = restore_hanri_hangul_annotations(wrapped, protected_known_hanri)

    # 6) Prevent line-break between </ruby>/<a> and following punctuation
    wrapped = nowrap_after_annotation(wrapped)

    # 7) Only add <p> wrapper if there are ≥10 Hangul syllables OR terminal punctuation
    if hangul_count < 10 and not has_terminal_punct:
        return wrapped
    else:
        return f'<p style="font-family:Sans-serif, Noto Sans TC;text-indent:2em">\n{wrapped}\n</p>'
    
# ==== PREVIEW FOR CONSOLE ====
def preview_tones(input_sentence: str, max_cells_per_line: int = 42) -> str:
    # first normalize 앚/쟞-type syllables into special jamo sequences
    input_sentence = normalize_yyae(input_sentence)

    # normalize any '한글+ㅜ+digit' sequences so preview sees the jamo cluster
    input_sentence = normalize_compat_jamo(input_sentence)
    
    tone_map    = {'1':'ꞈ','2':'ˎ','4':'ˏ','5':'ˍ'}
    punctuation = set(" ,.!?:;'-–—`‘’。，。“”()…‧~")

    def cell_width(s: str) -> int:
        w = 0
        for ch in s:
            ea = unicodedata.east_asian_width(ch)
            w += 2 if ea in ('W','F') else 1
        return w

    def is_jamo(ch: str) -> bool:
        return (
            ('\u1100' <= ch <= '\u1112')     # Leading jamo
            or ('\u1161' <= ch <= '\u1175')  # ✅ Medial jamo (THIS WAS MISSING)
            or ('\u11A8' <= ch <= '\u11FF')  # Jongseong jamo
            or ('\u3130' <= ch <= '\u318F')  # Compatibility jamo
            or ch in special_jamo
            or ch in extra_consonants
        )

    # exceptional "bad actors" here:
    exceptional = {
        "ᄀᅷᇂ", "ᄆᅷᇂ", "ᄂᅷᇂ", "ᄃᅷᇂ",
        "ᄅᅷᇂ", "ᄑᅷᇂ", "ᄎᅷᇂ", "ᄋᆤᆯ",
        "흐ᇡ"
    }

    # 1) Collect (cell_text, tone_or_None) tuples
    cells = []
    i = 0
    while i < len(input_sentence):        
        # 1a) Exceptional combos + optional tone
        for combo in exceptional:
            if input_sentence.startswith(combo, i):
                j = i + len(combo)
                tone = None
                if j < len(input_sentence) and input_sentence[j] in tone_map:
                    tone = tone_map[input_sentence[j]]
                    j += 1
                cells.append((combo, tone))
                i = j
                break
        else:
            # 1b) Jamo‐cluster (initial + medial/special + optional jongseong)
            c = input_sentence[i]
            if is_hangul_consonant(c) and i+1 < len(input_sentence) and is_jamo(input_sentence[i+1]):
                # initial + any medial (ᅡ–ᅵ or special) or final jamo
                cluster = c + input_sentence[i+1]
                j = i + 2
                # absorb optional jongseong (ᆰ…ᇂ)
                if j < len(input_sentence) and is_hangul_jongseong(input_sentence[j]):
                    cluster += input_sentence[j]
                    j += 1
                # now look for a tone digit
                tone = tone_map.get(input_sentence[j]) if j < len(input_sentence) else None
                if tone:
                    cells.append((cluster, tone))
                    i = j + 1
                else:
                    cells.append((cluster, None))
                    i = j
                continue

            # 1c) Plain-English letter → show as a cell
            if c.isascii() and c.isalpha():
                cells.append((c, None))
                i += 1
                continue

            # 1d) Precomposed Hangul + tone
            if is_hangul_precomposed(c) and i+1 < len(input_sentence) and input_sentence[i+1] in tone_map:
                cells.append((c, tone_map[input_sentence[i+1]]))
                i += 2
                continue

            # 1e) Hangul alone (precomposed or single jamo)
            if is_hangul_precomposed(c) or is_jamo(c):
                cells.append((c, None))
                i += 1
                continue

            # 1f) Punctuation
            if c in punctuation:
                cells.append((c, None))
                i += 1
                continue
            
            # 1g) Standalone digits (not part of a tone marker) → show as their own cell
            if c.isdigit():
                cells.append((c, None))
                i += 1
                continue

            # 1h) Bracket handling: drop the brackets and non-Hangul inside; show only Hangul (with tones)
            if input_sentence[i] == '[':
                # skip the opening bracket
                i += 1
                # consume until closing ']'
                while i < len(input_sentence) and input_sentence[i] != ']':
                    ch = input_sentence[i]
                    # Precomposed Hangul + tone
                    if is_hangul_precomposed(ch) and i+1 < len(input_sentence) and input_sentence[i+1] in tone_map:
                        cells.append((ch, tone_map[input_sentence[i+1]]))
                        i += 2
                        continue
                    # Any jamo or precomposed Hangul
                    if is_hangul_precomposed(ch) or is_jamo(ch):
                        cells.append((ch, None))
                    # everything else inside brackets is dropped
                    i += 1
                # skip the closing bracket
                if i < len(input_sentence) and input_sentence[i] == ']':
                    i += 1
                # move on to next character
                continue

            # 1i) Allow English, French, Chinese, Japanese, Korean — skip everything else
            # English letters
            if c.isascii() and c.isalpha():
                cells.append((c, None))
            # French letters (Latin-1 Supplement, e.g. é, è, ç, à)
            elif '\u00C0' <= c <= '\u00FF':
                cells.append((c, None))
            # CJK Unified Ideographs (Chinese)
            elif '\u3400' <= c <= '\u4DBF' or '\u4E00' <= c <= '\u9FFF':
                cells.append((c, None))
            # Japanese Hiragana/Katakana
            elif '\u3040' <= c <= '\u309F' or '\u30A0' <= c <= '\u30FF':
                cells.append((c, None))
            # Korean precomposed Hangul
            elif '\uAC00' <= c <= '\uD7A3':
                cells.append((c, None))
            # anything else gets skipped
            i += 1

    # 2) Break into lines of max_cells_per_line
    lines = []
    for start in range(0, len(cells), max_cells_per_line):
        chunk = cells[start:start+max_cells_per_line]
        tone_line = []
        base_line = []
        for ch, t in chunk:
            if ch in punctuation:
                # one‐col punctuation
                tone_line.append(" ")
                base_line.append(ch)
            else:
                # two‐col Hangul/Jamo
                if t:
                    tone_line.append(" " + t)
                else:
                    tone_line.append("  ")
                # pad base to 2 cols
                pad = max(0, 2 - cell_width(ch))
                base_line.append(ch + " " * pad)
        lines.append("".join(tone_line))
        lines.append("".join(base_line))

    # join all chunks with newlines
    return "\n".join(lines)

# ==== PREVIEW FOR HTML ====
def preview_tones_html(input_sentence: str) -> str:
    tone_map = {'1':'ꞈ','2':'ˎ','4':'ˏ','5':'ˍ'}
    tone_cells = []
    hangul_cells = []
    i = 0
    punc = set([',', '.', '!', '?', ':', ';', "'", '`', '’', '-', '–', '—', '，', '。', '“', '”', '‧', '~'])

    while i < len(input_sentence):
        c = input_sentence[i]

        # Hangul + tone
        if is_hangul_precomposed(c) and i+1 < len(input_sentence) and input_sentence[i+1] in tone_map:
            tone_cells.append(f"<td style='text-align:center'>{tone_map[input_sentence[i+1]]}</td>")
            hangul_cells.append(f"<td style='text-align:center'>{c}</td>")
            i += 2

        # Hangul alone
        elif is_hangul_precomposed(c):
            tone_cells.append("<td style='text-align:center'>&nbsp;</td>")
            hangul_cells.append(f"<td style='text-align:center'>{c}</td>")
            i += 1

        # punctuation or gloss → skip
        else:
            i += 1

    return (
        "<table style='font-family:Sans-serif, Noto Sans TC; border-collapse: collapse;'>"
        f"<tr>{''.join(tone_cells)}</tr>"
        f"<tr>{''.join(hangul_cells)}</tr>"
        "</table>"
    )

def core_convert(
    input_sentence: str,
    include_lomari_title: bool = True,
    use_wiktionary: bool = False,
) -> str:
    """Produce the inner HTML (ruby + <a> tooltips) but no <p> wrapper."""

    # 1) Protect explicit [Hanri + Hangul] annotations first.  This prevents
    # old [Hangul + gloss] mode from seeing a half-converted bracket if the
    # bracket contains Hanri followed by tone-marked Hangul.
    protected_input, protected_hanri = protect_hanri_hangul_annotations(
        input_sentence,
        include_lomari_title,
        use_wiktionary=use_wiktionary,
    )

    # 2) Then protect automatic known Hanri annotations.
    protected_input, protected_known_hanri = protect_known_hanri_annotations(
        protected_input,
        include_lomari_title,
        use_wiktionary=use_wiktionary,
    )

    # 3) Convert normal Hangul tones
    processed = convert_segment_to_ruby(protected_input)

    # 4) Old [Hangul + gloss/Hanri] Wiktionary-link mode has been removed.
    wrapped = processed

    # 5) Restore protected annotations
    wrapped = restore_hanri_hangul_annotations(wrapped, protected_hanri)
    wrapped = restore_hanri_hangul_annotations(wrapped, protected_known_hanri)

    return wrapped

def wrap_default(html: str) -> str:
    return f'<p style="font-family:Sans-serif, Noto Sans TC;text-indent:2em">\n{html}\n</p>'

def wrap_no_indent(html: str) -> str:
    return f"<p style='font-family:Sans-serif, Noto Sans TC;'>\n{html}\n</p>"

# ==== 7. CHINESE WORD ANNOTATOR ====

import html as html_lib

SC_FONT_HANRI_CHARS = {'㩼'}


def escape_visible_html_text(text: str) -> str:
    """Escape visible HTML text, with per-glyph font exceptions."""
    out: list[str] = []
    for ch in str(text):
        escaped = html_lib.escape(ch)
        if ch in SC_FONT_HANRI_CHARS:
            out.append(f'<span style=";font-family: Noto Sans SC">{escaped}</span>')
        else:
            out.append(escaped)
    return ''.join(out)


# Extra tone symbols for the newer annotation style:
# ˆ = tone 1, ` = tone 2, no mark = tone 3, ˊ = tone 4, ˉ = tone 5
ANNOTATION_SYMBOL_TO_DIGIT = str.maketrans({
    'ˆ': '1',
    '`': '2',
    'ˋ': '2',
    'ˊ': '4',
    'ˉ': '5',

    # keep compatibility with your older symbols too
    'ꞈ': '1',
    'ˎ': '2',
    'ˏ': '4',
    'ˍ': '5',
})

ANNOTATION_DIGIT_TO_SYMBOL = str.maketrans({
    '1': 'ˆ',
    '2': '`',
    '4': 'ˊ',
    '5': 'ˉ',
})


def normalize_annotation_tones(s: str) -> str:
    """
    Accepts either:
      챠5호5
      챠ˉ호ˉ
      디2뼹5
      디`뼹ˉ

    Converts all tone symbols internally to digits,
    so auto_lomari_from_hangul() can process them.
    """
    return s.translate(ANNOTATION_SYMBOL_TO_DIGIT)


def hangul_digits_to_annotation_symbols(s: str) -> str:
    """
    Converts internal digit tones back into the display style:
      1 -> ˆ
      2 -> `
      4 -> ˊ
      5 -> ˉ
    Tone 3 stays unmarked.
    """
    return s.translate(ANNOTATION_DIGIT_TO_SYMBOL).replace('3', '')


def clean_chinese_annotation_hangul_input(s: str) -> str:
    """
    Chinese annotation mode should receive only the Hangul reading.
    This removes sentence punctuation accidentally typed after the reading.
    Example:
      띤솅ꞈ. → 띤솅ꞈ
      띤솅ˆ， → 띤솅ˆ
    """
    return s.strip().strip(".,!?;:’“”。，！？；：、")


def chinese_wiktionary_url(word: str) -> str:
    """
    Build Wiktionary URL for Chinese annotation mode.

    Display text stays unchanged, but Wiktionary lookup can use
    a normalised form for selected characters.

    Example:
      displayed text: 个
      Wiktionary link: 個
    """
    lookup_word = word.replace("个", "個")

    return "https://en.wiktionary.org/wiki/" + quote(lookup_word, safe="") + "#Chinese"

def rt_left_for_chinese_word(word: str, hangul_display: str) -> str:
    """
    Rough visual alignment for the Hangul <rt> above Chinese words.

    Special rules:
      1 Chinese char + 1 Hangul syllable-unit with no tone mark → 0.4em.

      2 Chinese chars + 2 Hangul syllable-units,
      where the FIRST syllable-unit has no tone mark → 0.8em.

      3 Chinese chars + 3 Hangul syllable-units,
      where the FIRST syllable-unit has no tone mark → 1.1em.

      3 Chinese chars + 2 Hangul syllable-units,
      where the FIRST syllable-unit has a tone mark → 1.6em.

      3 Chinese chars + 2 Hangul syllable-units,
      where only the SECOND syllable-unit has a tone mark → 1.2em.

      4 Chinese chars + 4 Hangul syllable-units,
      where the FIRST syllable-unit has no tone mark → 1.5em.
    """
    length = len(word)

    syllable_unit = (
        r'(?:'
        r'[\uAC00-\uD7A3]'
        r'|'
        r'[\u1100-\u1112ᅙ][\u1161-\u1175ᅷᆤ](?:[\u11A8-\u11FFᇍᇎ])?'
        r')'
    )

    # 1 Chinese character + 1 Hangul syllable-unit with NO tone mark
    if length == 1:
        if re.fullmatch(
            syllable_unit,
            hangul_display
        ):
            return "0.4em"

    # 2 Chinese characters + 2 Hangul syllable-units,
    # where the first Hangul syllable-unit has NO tone mark
    if length == 2:
        if re.fullmatch(
            syllable_unit
            + syllable_unit + r'[ˆ`ˊˉ]?',
            hangul_display
        ):
            return "0.8em"

    # 3 Chinese characters + 3 Hangul syllable-units,
    # where the first Hangul syllable-unit has NO tone mark
    if length == 3:
        if re.fullmatch(
            syllable_unit
            + syllable_unit + r'[ˆ`ˊˉ]?'
            + syllable_unit + r'[ˆ`ˊˉ]?',
            hangul_display
        ):
            return "1.1em"

    # 3 Chinese characters + 2 Hangul syllable-units,
    # where the first Hangul syllable-unit HAS a tone mark → 1.6em
    # Example: 下昏暗 / 옝ˉ암
    if length == 3:
        if re.fullmatch(
            syllable_unit + r'[ˆ`ˊˉ]'
            + syllable_unit + r'[ˆ`ˊˉ]?',
            hangul_display
        ):
            return "1.6em"

    # 3 Chinese characters + 2 Hangul syllable-units,
    # where only the second Hangul syllable-unit HAS a tone mark → 1.2em
    if length == 3:
        if re.fullmatch(
            syllable_unit
            + syllable_unit + r'[ˆ`ˊˉ]',
            hangul_display
        ):
            return "1.2em"

    # 4 Chinese characters + 4 Hangul syllable-units,
    # where the FIRST has no tone mark,
    # but the SECOND has a tone mark → 1.2em
    # Example: 틍감ˉ삗딜ˆ
    if length == 4:
        if re.fullmatch(
            syllable_unit
            + syllable_unit + r'[ˆ`ˊˉ]'
            + syllable_unit + r'[ˆ`ˊˉ]?'
            + syllable_unit + r'[ˆ`ˊˉ]?',
            hangul_display
        ):
            return "1.2em"

    # 4 Chinese characters + 4 Hangul syllable-units,
    # where the first Hangul syllable-unit has NO tone mark → 1.5em
    if length == 4:
        if re.fullmatch(
            syllable_unit
            + syllable_unit + r'[ˆ`ˊˉ]?'
            + syllable_unit + r'[ˆ`ˊˉ]?'
            + syllable_unit + r'[ˆ`ˊˉ]?',
            hangul_display
        ):
            return "1.5em"

    # Default fallback rules
    if length <= 1:
        return "0.25em"
    if length == 2:
        return "0.55em"
    if length == 3:
        return "0.8em"
    return "1em"


def ruby_display_ends_with_hangul_unit(hangul_display: str) -> bool:
    """Return True when a ruby reading visibly ends on a Hangul/Jamo unit."""
    text = str(hangul_display or '').rstrip()
    if not text or text.endswith('-'):
        return False

    i = len(text) - 1
    while i >= 0 and text[i] in 'ˆ`ˊˉꞈˎˏˍ':
        i -= 1
    if i < 0:
        return False

    ch = text[i]
    return (
        is_hangul_precomposed(ch)
        or is_jamo(ch)
        or ('\u3130' <= ch <= '\u318F')
    )


def add_ruby_continuation_hyphen(hangul_display: str) -> str:
    """Mark a sandhi ruby reading as visibly continuing to the next word."""
    if ruby_display_ends_with_hangul_unit(hangul_display):
        return str(hangul_display).rstrip() + '-'
    return hangul_display


def annotate_chinese_word(
    chinese_word: str,
    hangul_input: str,
    use_wiktionary: bool = False,
    include_lomari_title: bool = True,
    continuation_hyphen: bool = False,
) -> str:
    """
    Produces Chinese ruby annotation.

    If use_wiktionary is False:
      <ruby>中文<rt>한글</rt></ruby>

    If use_wiktionary is True:
      <a href="Wiktionary URL" title="romanisation" ...>
        <ruby>中文<rt>한글</rt></ruby>
      </a>
    """

    chinese_word = chinese_word.strip()
    hangul_raw = normalize_apostrophes(hangul_input.strip())

    # 1. Normalise tone symbols to internal digits
    hangul_digit = normalize_annotation_tones(hangul_raw)

    # 2. Automatically generate romanisation
    lomari = auto_lomari_from_hangul(hangul_digit)

    # 3. Convert tone digits to display symbols for the ruby text
    # Also normalise 앚/쟞-type syllables into special jamo display forms
    hangul_display = hangul_digits_to_annotation_symbols(normalize_yyae(hangul_digit))

    left = rt_left_for_chinese_word(chinese_word, hangul_display)

    if continuation_hyphen:
        hangul_display = add_ruby_continuation_hyphen(hangul_display)

    # 4. Escape HTML-sensitive characters
    chinese_escaped = escape_visible_html_text(chinese_word)
    hangul_escaped = html_lib.escape(hangul_display)
    lomari_escaped = html_lib.escape(lomari, quote=True)

    title_attr = f' title="{lomari_escaped}"' if include_lomari_title and not use_wiktionary else ''
    ruby_style = 'position: relative' if use_wiktionary else 'position: relative;white-space: nowrap'
    ruby_html = (
        f'<ruby style="{ruby_style}"{title_attr}>{chinese_escaped}'
        f'<rt style="font-size: 57%;position: absolute;top: -1.2em;left: {left}">'
        f'{hangul_escaped}</rt></ruby>'
    )

    # Default: no Wiktionary link
    if not use_wiktionary:
        return ruby_html

    # Optional: wrap with Wiktionary link
    url = chinese_wiktionary_url(chinese_word)
    url_escaped = html_lib.escape(url, quote=True)

    return (
        f'<a href="{url_escaped}" title="{lomari_escaped}" '
        f'style="color: var(--wp--preset--color--primary);'
        f'text-decoration: underline dotted;cursor: help;white-space: nowrap">'
        f'{ruby_html}</a>'
    )

def take_hangul_reading_units(reading: str, index: int, unit_count: int) -> tuple[str, int]:
    """Take unit_count Hangul/Jamo reading units from reading[index:]."""
    out: list[str] = []
    i = index
    units_left = unit_count

    while i < len(reading) and units_left > 0:
        unit = hangul_reading_unit_at(reading, i)
        if unit is not None:
            text, i = unit
            out.append(text)
            units_left -= 1
            continue

        # Preserve internal reading separators, but do not count them as units.
        out.append(reading[i])
        i += 1

    return ''.join(out), i

def render_mixed_tsv_hanri_match(
    hanri_key: str,
    reading: str,
    include_lomari_title: bool = True,
    use_wiktionary: bool = False,
    continuation_hyphen: bool = False,
) -> str:
    """Render a TSV key that mixes Hangul text with Hanri characters."""
    key = normalize_compat_jamo(normalize_yyae(str(hanri_key or '')))
    reading_text = normalize_compat_jamo(normalize_yyae(normalize_annotation_tones(str(reading or ''))))
    out: list[str] = []
    i = 0
    reading_i = 0

    while i < len(key):
        if is_cjk_char(key[i]):
            start = i
            while i < len(key) and is_cjk_char(key[i]):
                i += 1
            hanri_run = key[start:i]
            hangul_run, reading_i = take_hangul_reading_units(reading_text, reading_i, len(hanri_run))
            run_continuation_hyphen = continuation_hyphen and i >= len(key)
            out.append(annotate_chinese_word(
                hanri_run,
                hangul_run,
                use_wiktionary=use_wiktionary,
                include_lomari_title=include_lomari_title,
                continuation_hyphen=run_continuation_hyphen,
            ))
            continue

        unit = hangul_reading_unit_at(key, i)
        if unit is not None:
            key_unit, i = unit
            reading_unit, reading_i = take_hangul_reading_units(reading_text, reading_i, 1)
            out.append(convert_segment_to_ruby(reading_unit or key_unit))
            continue

        if key[i] in {"'", '’', '‘'}:
            out.append(escape_visible_html_text(key[i]))
            if reading_i < len(reading_text) and reading_text[reading_i] in {"'", '’', '‘'}:
                reading_i += 1
            i += 1
            continue

        out.append(escape_visible_html_text(key[i]))
        i += 1

    return ''.join(out)

def render_mixed_tsv_lomari_ruby_below(hanri_key: str, reading: str) -> str:
    """Render a mixed TSV key for the Lomari-ruby-below HTML mode."""
    key = normalize_compat_jamo(normalize_yyae(str(hanri_key or '')))
    reading_text = normalize_compat_jamo(normalize_yyae(normalize_annotation_tones(str(reading or ''))))
    out: list[str] = []
    i = 0
    reading_i = 0

    while i < len(key):
        if is_cjk_char(key[i]):
            start = i
            while i < len(key) and is_cjk_char(key[i]):
                i += 1
            hanri_run = key[start:i]
            hangul_run, reading_i = take_hangul_reading_units(reading_text, reading_i, len(hanri_run))
            out.append(lomari_ruby_below(hanri_run, hangul_run))
            continue

        unit = hangul_reading_unit_at(key, i)
        if unit is not None:
            key_unit, i = unit
            reading_unit, reading_i = take_hangul_reading_units(reading_text, reading_i, 1)
            out.append(lomari_ruby_below(visible_hangul_with_tone_symbols(reading_unit or key_unit), reading_unit or key_unit))
            continue

        if key[i] in {"'", '’', '‘'}:
            out.append(escape_visible_html_text(key[i]))
            if reading_i < len(reading_text) and reading_text[reading_i] in {"'", '’', '‘'}:
                reading_i += 1
            i += 1
            continue

        out.append(escape_visible_html_text(key[i]))
        i += 1

    return ''.join(out)

def contains_hangul_or_jamo(s: str) -> bool:
    return any(
        is_hangul_precomposed(ch)
        or is_jamo(ch)
        or ('\u3130' <= ch <= '\u318F')  # compatibility jamo
        for ch in s
    )


# ==== 8. HTML CONVERTER API ==== 

HTML_STYLES = {
    "plain": "Plain inline fragment (no wrapper)",
    "lomari_ruby_below": "Lomari ruby below (<span>)",
    "lomari_next_line": "Mandarin + Lomari (<span>)",
    "song": "Lyric / Song block (Hangul + Lomari)",
    "novel": "Novel paragraph (<p>, 2em indent)",
    "novel_first": "Novel first line (<p>, enlarged first unit + Lomari)",
    "title": "Title span (<span>)",
}



def text_has_hangul_or_jamo(s: str) -> bool:
    """True if text contains Hangul syllables, jamo, or compatibility jamo."""
    return any(
        is_hangul_precomposed(ch)
        or is_jamo(ch)
        or ('\u3130' <= ch <= '\u318F')
        for ch in s
    )


def autocorrect_checked_tone_on_entering_final(s: str) -> tuple[str, bool]:
    """
    Auto-correct a checked-syllable typo:
      final ㄱ/ㄷ/ㅂ/ㅎ + tone 2 digit → tone 1 digit.

    This preserves the behaviour of the old main loop.
    """
    def ends_with_checked_final(ch: str, tone_char: str) -> bool:
        if tone_char != '2':
            return False

        if is_hangul_precomposed(ch):
            # final indices: ㄱ=1, ㄷ=7, ㅂ=17, ㅎ=27
            return ((ord(ch) - 0xAC00) % 28) in {1, 7, 17, 27}

        return '\u11A8' <= ch <= '\u11FF' and (ord(ch) - 0x11A7) in {1, 7, 17, 27}

    corrected = []
    i = 0
    changed = False

    while i < len(s):
        c = s[i]
        if i + 1 < len(s) and ends_with_checked_final(c, s[i + 1]):
            corrected.extend([c, '1'])
            changed = True
            i += 2
        else:
            corrected.append(c)
            i += 1

    return ''.join(corrected), changed


def visible_hangul_with_tone_symbols(reading: str) -> str:
    """Return Hangul/Jamo display text with digit tones shown as symbols."""
    return hangul_digits_to_annotation_symbols(normalize_yyae(normalize_annotation_tones(reading)))


def lomari_ruby_below(base_text: str, reading: str) -> str:
    """Return one ruby unit with Lomari <rt> positioned below the base text."""
    base = escape_visible_html_text(base_text)
    lomari = auto_lomari_from_hangul(reading)
    rt = html_lib.escape(lomari, quote=True).replace("--", "&#045;&#045;")
    return (
        '<ruby style="position: relative;white-space: nowrap;ruby-position: under">'
        f'{base}<rt style="font-size: 70%;position: absolute;top: 1.2em;'
        f'left: 0;font-family: Calibri">{rt}</rt></ruby>'
    )


def hangul_reading_unit_at(text: str, index: int) -> tuple[str, int] | None:
    """Return one visible Hangul/Jamo unit plus any attached tone marker."""
    if index < 0 or index >= len(text):
        return None

    tone_chars = set("12345ˆ`ˋˊˉꞈˎˏˍ")
    ch = text[index]
    end = index

    if ch == hangul_choseong_filler and index + 1 < len(text) and text[index + 1] in special_jamo:
        end = index + 2
        if end < len(text) and is_hangul_jongseong(text[end]):
            end += 1
    elif is_hangul_precomposed(ch):
        end = index + 1
    elif is_hangul_consonant(ch) and index + 1 < len(text) and is_jamo(text[index + 1]):
        end = index + 2
        if end < len(text) and is_hangul_jongseong(text[end]):
            end += 1
    elif is_jamo(ch) or ('\u3130' <= ch <= '\u318F'):
        end = index + 1
    else:
        return None

    while end < len(text) and text[end] in tone_chars:
        end += 1

    return text[index:end], end


def sandhi_raw_hangul_before_explicit_hyphen(text: str) -> str:
    """Treat ASCII hyphen after raw Hangul like a following readable unit."""
    source = str(text or '')
    out: list[str] = []
    i = 0

    while i < len(source):
        if source[i] == '[':
            end = source.find(']', i + 1)
            if end != -1:
                out.append(source[i:end + 1])
                i = end + 1
                continue

        unit = hangul_reading_unit_at(source, i)
        if unit is not None:
            unit_text, end = unit
            if end < len(source) and source[end] == '-':
                unit_digits = normalize_annotation_tones(unit_text)
                if last_tone_digit_index(unit_digits) is None:
                    unit_text = citation_to_sandhi_reading(unit_digits) or unit_text
            out.append(unit_text)
            i = end
            continue

        out.append(source[i])
        i += 1

    return ''.join(out)


def convert_to_lomari_ruby_below(input_sentence: str) -> str:
    """Produce a span-only fragment with Lomari ruby placed below text."""
    source = normalize_compat_jamo(normalize_yyae(str(input_sentence or '')))
    out: list[str] = []
    i = 0

    while i < len(source):
        ch = source[i]

        if ch == "[":
            end = source.find("]", i + 1)
            if end != -1:
                parsed = split_hanri_hangul_bracket(source[i + 1:end])
                if parsed:
                    hanri_word, hangul_reading = parsed
                    out.append(lomari_ruby_below(hanri_word, hangul_reading))
                    i = end + 1
                    continue
            out.append(escape_visible_html_text(ch))
            i += 1
            continue

        mixed_match = mixed_tsv_hanri_match(source, i)
        if mixed_match:
            hanri_key, reading = mixed_match
            out.append(render_mixed_tsv_lomari_ruby_below(hanri_key, reading))
            i += len(hanri_key)
            continue

        match = known_hanri_match(source, i)
        if match:
            hanri_word, reading = match
            out.append(lomari_ruby_below(hanri_word, reading))
            i += len(hanri_word)
            continue

        hangul_unit = hangul_reading_unit_at(source, i)
        if hangul_unit is not None:
            unit, i = hangul_unit
            out.append(lomari_ruby_below(visible_hangul_with_tone_symbols(unit), unit))
            continue

        out.append(escape_visible_html_text(ch))
        i += 1

    return (
        '<span style="font-family:Sans-serif, Noto Sans TC;line-height: 2.2">'
        + ''.join(out)
        + '</span>'
    )


def make_song_block(core_html: str, lomari: str) -> str:
    """Return combined Hangul + smaller Lomari HTML block."""
    escaped_lomari = lomari.replace("--", "&#045;&#045;")
    return (
        "<p style='font-family:Sans-serif, Noto Sans TC'>\n"
        "  <span style=\"display: block;font-size: 1em\">\n"
        f"    {core_html}\n"
        "  </span>\n"
        "  <span style=\"display: block;font-size: 0.7em;color: gray;"
        "margin-top: -5px;font-family: Calibri\">\n"
        f"    {escaped_lomari}\n"
        "  </span>\n"
        "</p>"
    )


def make_multiline_song_html(source_text: str) -> tuple[str, str]:
    """Render each non-empty lyric line as its own song <p> block."""
    lines = [line.strip() for line in str(source_text or '').splitlines() if line.strip()]
    if not lines:
        lines = [str(source_text or '').strip()]

    html_blocks: list[str] = []
    lomari_lines: list[str] = []
    numbered = len(lines) > 1

    for index, line in enumerate(lines, start=1):
        core = core_convert(
            line,
            include_lomari_title=False,
            use_wiktionary=False,
        )
        html, lomari = wrap_core_html(core, "song", line)
        if numbered:
            html = f"<!-- #{index} -->\n{html}"
        html_blocks.append(html)
        lomari_lines.append(lomari)

    if numbered and html_blocks:
        html_blocks[-1] = f"{html_blocks[-1]}\n<br>"

    return "\n\n".join(html_blocks), "\n".join(lomari_lines)


def visible_source_for_lomari_next_line(input_sentence: str) -> str:
    """Return the visible source line without adding ruby annotations."""
    source = normalize_compat_jamo(normalize_yyae(str(input_sentence or '')))
    out: list[str] = []
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
            continue
        if source[i] in {"'", "’", "‘"}:
            i += 1
            continue

        if source[i] == "[":
            end = source.find("]", i + 1)
            if end != -1:
                parsed = split_hanri_hangul_bracket(source[i + 1:end])
                if parsed:
                    hanri_word, _hangul_reading = parsed
                    out.append(hanri_word)
                    i = end + 1
                    continue
        unit = hangul_reading_unit_at(source, i)
        if unit is not None:
            text, i = unit
            out.append(visible_hangul_with_tone_symbols(text))
            continue
        out.append(source[i])
        i += 1
    return ''.join(out)


def capitalize_first_lomari_letter(text: str) -> str:
    """Uppercase the first alphabetic Lomari letter, preserving tone marks."""
    for idx, ch in enumerate(str(text or '')):
        if ('a' <= ch <= 'z') or ('A' <= ch <= 'Z'):
            return text[:idx] + ch.upper() + text[idx + 1:]
    return text


def make_lomari_next_line_span(visible_text: str, lomari: str) -> str:
    """Return plain visible text plus a Lomari line, using only span wrappers."""
    escaped_visible = escape_visible_html_text(visible_text)
    lomari = capitalize_first_lomari_letter(lomari)
    escaped_lomari = html_lib.escape(lomari, quote=True).replace("--", "&#045;&#045;")
    return (
        '<span style="font-family:Sans-serif, Noto Sans TC">'
        '<span style="display: block;font-size: 1em">'
        f'{escaped_visible}'
        '</span>'
        '<span style="display: block;font-size: 0.7em;'
        'margin-top: -5px;font-family: Calibri">'
        f'{escaped_lomari}'
        '</span>'
        '</span>'
    )


def emphasize_first_annotation(core_html: str) -> str:
    """Wrap the first ruby/link annotation for novel first-line styling."""
    pattern = (
        r'^(\s*)'
        r'((?:<a\b(?:(?!<a\b).)*?</a>)|(?:<ruby\b(?:(?!<ruby\b).)*?</ruby>))'
    )
    return re.sub(
        pattern,
        r'\1<span style="font-size: 150%;color: black">\2</span>',
        core_html,
        count=1,
        flags=re.DOTALL,
    )


def make_novel_first_line_block(core_html: str, lomari: str) -> str:
    """Return a novel opening-line block with large first unit and Lomari line."""
    escaped_lomari = lomari.replace("--", "&#045;&#045;")
    emphasized = emphasize_first_annotation(core_html)
    return (
        '<p style="font-family:Sans-serif, Noto Sans TC;text-indent:2em">\n'
        '  <span style="display: block;font-size: 1em">\n'
        f'    {emphasized}\n'
        '  </span>\n'
        '  <span style="display: block;font-size: 0.7em;color: gray;'
        'margin-top: -5px;font-family: Calibri">\n'
        f'    {escaped_lomari}\n'
        '  </span>\n'
        '</p>'
    )


def wrap_core_html(core_html: str, style: str, source_text: str = "") -> tuple[str, str]:
    """
    Wrap an already-converted Hangul HTML fragment.

    Returns:
      (html_output, lomari_output)

    lomari_output is filled only for song style.
    """
    if style == "novel":
        html = wrap_default(core_html)
        lomari = ""
    elif style == "novel_first":
        reading_for_lomari = mixed_sentence_to_hangul_reading(source_text)
        lomari = auto_lomari_from_hangul(reading_for_lomari)
        html = make_novel_first_line_block(core_html, lomari)
    elif style == "song":
        reading_for_lomari = mixed_sentence_to_hangul_reading(source_text)
        lomari = auto_lomari_from_hangul(reading_for_lomari)
        html = make_song_block(core_html, lomari)
    elif style == "lomari_next_line":
        reading_for_lomari = mixed_sentence_to_hangul_reading(source_text)
        lomari = auto_lomari_from_hangul(reading_for_lomari)
        visible_text = visible_source_for_lomari_next_line(source_text)
        html = make_lomari_next_line_span(visible_text, lomari)
    elif style == "plain":
        html = f'<span style="font-family:Sans-serif, Noto Sans TC">{core_html}</span>'
        lomari = ""
    elif style == "title":
        html = f'<span style="font-family:Sans-serif, Noto Sans TC">{core_html}</span>'
        lomari = ""
    else:
        raise ValueError(f"Unknown HTML style: {style}")

    return nowrap_after_annotation(html), lomari


def convert_hangul_to_html(input_text: str, style: str = "plain") -> dict:
    """
    Convert Hangul / Hanri-Hangul text to HTML.

    Returns a small result dictionary so both GUI and console can share logic.
    """
    s = normalize_tone_symbols_to_digits(input_text.strip())
    if not s:
        raise ValueError("Input is empty.")

    s = apply_hangul_overrides_from_tsv(s)
    s, changed = autocorrect_checked_tone_on_entering_final(s)

    if not (text_has_hangul_or_jamo(s) or field_contains_cjk(s)):
        raise ValueError("No Hangul or Hanri detected. Please enter Hangul or Hanri-Hangul text.")

    s = normalize_apostrophes(s)
    s = sandhi_raw_hangul_before_explicit_hyphen(s)
    if style == "song":
        html, lomari = make_multiline_song_html(s)
        return {
            "input": s,
            "core": html,
            "html": html,
            "lomari": lomari,
            "tone_autocorrected": changed,
            "preview": preview_tones(s),
        }

    if style == "lomari_next_line":
        reading_for_lomari = mixed_sentence_to_hangul_reading(s)
        lomari = auto_lomari_from_hangul(reading_for_lomari)
        visible_text = visible_source_for_lomari_next_line(s)
        html = make_lomari_next_line_span(visible_text, lomari)
        return {
            "input": s,
            "core": html,
            "html": html,
            "lomari": lomari,
            "tone_autocorrected": changed,
            "preview": preview_tones(s),
        }

    if style == "lomari_ruby_below":
        html = convert_to_lomari_ruby_below(s)
        return {
            "input": s,
            "core": html,
            "html": html,
            "lomari": "",
            "tone_autocorrected": changed,
            "preview": preview_tones(s),
        }

    core = core_convert(
        s,
        include_lomari_title=(style != "song"),
        use_wiktionary=False,
    )
    html, lomari = wrap_core_html(core, style, s)

    return {
        "input": s,
        "core": core,
        "html": html,
        "lomari": lomari,
        "tone_autocorrected": changed,
        "preview": preview_tones(s),
    }
