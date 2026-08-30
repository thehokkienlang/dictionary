"""
Hokkien Tangliengim IME Pad

A lightweight typing pad for 泉漳諺文 / Hokkien Hangul.

What it does
------------
1. Uses the standard Korean 2-beolsik keyboard layout.
2. Composes normal Hangul syllables where Unicode supports them.
3. Allows Hokkien-specific jamo clusters such as:
   ᄋᅷ, ᄋᆤ, ᄋힻ, ᅙᅡ
4. Can show a Hanri candidate popup for selected Hangul readings.
5. Copies the typed text to the clipboard.
6. Plays recorded syllable audio from public/audio_files.

How to run
----------
    python "Hokkien Tangliengim IME Pad.py"

Keyboard basics
---------------
Standard Korean keyboard:
    r = ㄱ, R = ㄲ, s = ㄴ, e = ㄷ, E = ㄸ, f = ㄹ, a = ㅁ
    q = ㅂ, Q = ㅃ, t = ㅅ, d = ㅇ, w = ㅈ, W = ㅉ
    c = ㅊ, z = ㅋ, x = ㅌ, v = ㅍ, g = ㅎ, G = ㆆ
    k = ㅏ, o = ㅐ, i = ㅑ, j = ㅓ, p = ㅔ, P = ㅖ
    u = ㅕ, h = ㅗ, y = ㅛ, n = ㅜ, b = ㅠ, m = ㅡ, l = ㅣ

Hokkien raw-key shortcuts
--------------------------
These rewrite the normal Korean keyboard sequence after the full sequence is typed:
    initial + k+n = initial + ᅷ   e.g. zkn = ᄏᅷ
    initial + i+n = initial + ᆤ   e.g. din = ᄋᆤ
    initial + mp = initial + ힻ  e.g. dmp = ᄋힻ
    mdk = ᅙᅡ

Tone digits 1 2 3 4 5 can be typed after a reading to filter Hanri candidates. Alt+0–9 inserts a literal Arabic numeral for audio/Lomari.

Hanri dictionary
----------------
When Hanri candidates are ON, completed readings show a popup.
The dictionary is loaded from data/hokkien_hanri_dict.tsv in the repo.
If the TSV is missing, a tiny built-in fallback dictionary is used.
"""

from __future__ import annotations

import csv
import difflib
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import threading
import unicodedata
import wave
from array import array
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from dataclasses import dataclass
from pathlib import Path


def bundled_resource_path(name: str) -> Path:
    """Return a resource path in source runs or PyInstaller one-file bundles."""
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        return Path(bundle_dir) / name
    return Path(__file__).resolve().with_name(name)


def source_repo_root() -> Path:
    """Return the repo root when running from the source tree."""
    script_dir = Path(__file__).resolve().parent
    if script_dir.name.lower() == 'desktop':
        return script_dir.parent
    return script_dir


def repo_data_path(name: str) -> Path:
    return source_repo_root() / 'data' / name


def repo_public_path(name: str) -> Path:
    return source_repo_root() / 'public' / name


def hanri_tsv_path_candidates() -> list[Path]:
    env_path = os.environ.get('HOKKIEN_HANRI_DICT_PATH')
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([
        bundled_resource_path(HANRI_TSV_FILENAME),
        repo_data_path(HANRI_TSV_FILENAME),
        Path.cwd() / HANRI_TSV_FILENAME,
        Path.cwd() / 'data' / HANRI_TSV_FILENAME,
    ])
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


TONE_MARKER_MODULE_PATH = Path(
    os.environ.get(
        'HOKKIEN_TONE_MARKER_PATH',
        str(bundled_resource_path('hokkien_tone_marker_gui.py')),
    )
)

APP_TITLE_EN = 'Hokkien Tangliengim IME Pad'
APP_TITLE_ZH = '東寧音輸入法'
ROMAN_PREVIEW_DEBOUNCE_MS = 120
ROMAN_PREVIEW_MIN_LINES = 1
ROMAN_PREVIEW_MAX_LINES = 3
TEXT_CURSOR_WIDTH = 1
TEXT_CURSOR_COLOR = '#5f6368'
TEXT_CURSOR_BLINK_ON_MS = 600
TEXT_CURSOR_BLINK_OFF_MS = 300
TEXT_CURSOR_TYPING_STEADY_MS = 450
HTML_JOINABLE_SUFFIX_HANRI = {'仔', '上', '中', '內'}
SC_FONT_HANRI_CHARS = {'㩼'}


def is_cjk_extension_b_char(ch: str) -> bool:
    code = ord(ch) if ch else 0
    return 0x20000 <= code <= 0x2A6DF


def tk_text_column_units(ch: str) -> int:
    """Absolute Text columns count supplementary-plane characters as two units."""
    return 2 if ch and ord(ch) > 0xFFFF else 1


def is_html_joinable_suffix_boundary(text: str, suffix_index: int) -> bool:
    """Joinable Hanri suffixes are only suffixes at a word boundary."""
    next_index = suffix_index + 1
    if next_index >= len(text):
        return True
    next_char = text[next_index]
    return next_char.isspace() or next_char in '.,;:!?)]}，。；：！？、」』）】'


UI_TEXT = {
    'en': {
        'app_title': APP_TITLE_EN,
        'language_toggle': '中文',
        'settings': 'Settings',
        'keep_top': 'Keep window on top',
        'hanri': 'Hanri',
        'ime': 'IME',
        'keyboard': 'Keyboard:',
        'hangul': 'Hangul',
        'lomari': 'Lomari (QWERTY)',
        'bopomofo': 'Bopomofo-style',
        'navigation_hint': 'Use Tab or arrow keys to navigate selections.',
        'hokkien_tab': 'Hokkien',
        'keyboard_guide_closed': 'Keyboard guide ▼',
        'keyboard_guide_open': 'Keyboard guide ▲',
        'keyboard_guide_title': 'Keyboard guide',
        'clear_text': 'Clear text',
        'copy_text': 'Copy text',
        'copy_html': 'Copy current text as HTML',
        'listen': 'Listen',
        'stop': 'Stop',
        'play': 'Play',
        'sandhi': 'Sandhi:',
        'taipei': 'Taipei',
        'singapore': 'Singapore',
        'tone_marks': 'Tone marks:',
        'tone_1': 'High',
        'tone_2': 'Falling',
        'tone_4': 'Rising',
        'tone_5': 'Mid-level',
        'ready': 'Ready.',
        'copied': 'Copied to clipboard.',
        'copied_html': 'Copied as {style}.',
        'copied_html_identical_tsv': 'Identical entry detected; copied HTML to clipboard.',
        'html_plain': 'plain HTML fragment',
        'html_lomari_ruby_below': 'Lomari ruby-below HTML span',
        'html_lomari_next_line': 'Mandarin + Lomari HTML span',
        'html_song': 'lyric/song HTML block',
        'html_novel': 'novel HTML paragraph',
        'html_novel_first': 'novel first-line HTML paragraph',
        'html_title': 'title HTML span',
        'html_error': 'Could not copy HTML: {error}',
        'copy_html_dialog': 'Copy as HTML',
        'tone_autocorrected': ' Tone-2 after checked final was auto-changed to Tone-1.',
        'confirm_hanri': 'Confirm Hanri reading',
        'add_tsv': 'Add this reading to the TSV dictionary?',
        'different_tsv': 'An entry for this Hanri already exists:\n{existing}\n\nAdd this different reading too?',
        'join_suffix_tsv': 'Connect the suffix into one ruby annotation?\n\nCurrent: {hanri} ({reading}) + {suffix} ({suffix_reading})\nConnected: {combined_hanri} ({combined_reading})',
        'yes': 'Yes',
        'ambiguous_prompt': 'This non-final Tone 3 could come from citation Tone 4 or Tone 5.\nWhich reading should be added to the TSV dictionary?',
        'yes_tone_4': 'Yes, Tone 4 (Rising ˊ)',
        'yes_tone_5': 'Yes, Tone 5 (Mid ˉ)',
        'no': 'No',
        'settings_e_to_ye_autocorrect': 'Autocorrect ㅔ+ㄱ/ㅇ to ㅖ+ㄱ/ㅇ',
        'settings_lomari_key_style': 'Use POJ/Tai-lo style for Lomari keys',
        'settings_lomari_key_style_standard': 'Standard Lomari',
        'settings_lomari_key_style_poj': 'POJ style',
        'settings_lomari_key_style_tailo': 'Tai-lo style',
        'settings_plain': 'HTML: Plain inline fragment',
        'settings_lomari_ruby_below': 'HTML: Lomari ruby below',
        'settings_lomari_next_line': 'HTML: Mandarin + Lomari mode',
        'settings_song': 'HTML: Lyric / song block',
        'settings_novel': 'HTML: Novel paragraph',
        'settings_novel_first': 'HTML: Novel first line',
        'settings_title': 'HTML: Title span',
        'hangul_help_title': 'Hangul keyboard',
        'hangul_help_subtitle': 'Click keys to type. Shift allows more letters to be typed.',
        'lomari_help_title': 'Lomari keyboard',
        'lomari_help_subtitle': 'Click keys to type. Shift allows more letters to be typed.',
        'lomari_help_lower_title': 'Lowercase',
        'lomari_help_shift_title': 'Shift → letter (jamo)',
        'lomari_shift_initials_hint': 'Shift: U/I→으/의\nor→어',
        'lomari_key_style_hint_ir': 'POJ/Tai-lo: ir→으',
    },
    'zh': {
        'app_title': APP_TITLE_ZH,
        'language_toggle': 'English',
        'settings': '設定',
        'keep_top': '置頂',
        'hanri': '漢字',
        'ime': '輸入法',
        'keyboard': '鍵盤：',
        'hangul': '諺文',
        'lomari': '羅馬字（QWERTY）',
        'bopomofo': '注音式',
        'navigation_hint': '可用 Tab 或方向鍵切換選項。',
        'hokkien_tab': '福建話–台灣話',
        'keyboard_guide_closed': '鍵盤初學 ▼',
        'keyboard_guide_open': '鍵盤初學 ▲',
        'keyboard_guide_title': '鍵盤初學',
        'clear_text': '清除文字',
        'copy_text': '複製文字',
        'copy_html': '複製為 HTML',
        'listen': '聆聽',
        'stop': '停止',
        'play': '播放',
        'sandhi': '變調：',
        'taipei': '台北',
        'singapore': '新加坡',
        'tone_marks': '聲調符號：',
        'tone_1': '高平',
        'tone_2': '低降',
        'tone_4': '升調',
        'tone_5': '中平',
        'ready': '就緒。',
        'copied': '已複製到剪貼簿。',
        'copied_html': '已複製為{style}。',
        'copied_html_identical_tsv': '偵測到相同條目；HTML 已複製到剪貼簿。',
        'html_plain': '純 HTML 片段',
        'html_lomari_ruby_below': '羅馬字下方 ruby HTML span',
        'html_lomari_next_line': '華語＋羅馬字 HTML span',
        'html_song': '歌詞 HTML 區塊',
        'html_novel': '小說 HTML 段落',
        'html_novel_first': '小說首行 HTML 段落',
        'html_title': '標題 HTML span',
        'html_error': '無法複製 HTML：{error}',
        'copy_html_dialog': '複製為 HTML',
        'tone_autocorrected': ' 入聲後的第 2 聲已自動改為第 1 聲。',
        'confirm_hanri': '確認漢字讀音',
        'add_tsv': '是否將這個讀音加入 TSV 字典？',
        'different_tsv': '這個漢字已有讀音：\n{existing}\n\n仍要加入這個不同讀音嗎？',
        'join_suffix_tsv': '是否將後綴接成同一個 ruby 標註？\n\n目前：{hanri}（{reading}）＋{suffix}（{suffix_reading}）\n接成：{combined_hanri}（{combined_reading}）',
        'yes': '是',
        'ambiguous_prompt': '這個非句末第 3 聲可能來自本調第 4 聲或第 5 聲。\n要將哪個讀音加入 TSV 字典？',
        'yes_tone_4': '是，第 4 聲（升 ˊ）',
        'yes_tone_5': '是，第 5 聲（中 ˉ）',
        'no': '否',
        'settings_e_to_ye_autocorrect': '自動將 ㅔ+ㄱ/ㅇ 改為 ㅖ+ㄱ/ㅇ',
        'settings_lomari_key_style': '羅馬字按鍵使用 POJ／台羅風格',
        'settings_lomari_key_style_standard': '標準羅馬字',
        'settings_lomari_key_style_poj': 'POJ 風格',
        'settings_lomari_key_style_tailo': '台羅風格',
        'settings_plain': 'HTML：純行內片段',
        'settings_lomari_ruby_below': 'HTML：下方羅馬字 ruby',
        'settings_lomari_next_line': 'HTML：華語＋羅馬字模式',
        'settings_song': 'HTML：歌詞／歌曲區塊',
        'settings_novel': 'HTML：小說段落',
        'settings_novel_first': 'HTML：小說首行',
        'settings_title': 'HTML：標題 span',
        'hangul_help_title': '諺文鍵盤',
        'hangul_help_subtitle': '點按按鍵即可輸入。Shift 可輸入更多字母。',
        'lomari_help_title': '羅馬字鍵盤',
        'lomari_help_subtitle': '點按按鍵即可輸入。Shift 可輸入更多字母。',
        'lomari_help_lower_title': '小寫',
        'lomari_help_shift_title': 'Shift → 字母',
        'lomari_shift_initials_hint': 'Shift：U/I→으/의\nor→어',
        'lomari_key_style_hint_ir': 'POJ／台羅：ir→으',
    },
}

# -----------------------------
# Unicode Hangul composition data
# -----------------------------

L_TABLE = [chr(codepoint) for codepoint in range(0x1100, 0x1113)]
V_TABLE = [chr(codepoint) for codepoint in range(0x1161, 0x1176)]
T_TABLE = [''] + [chr(codepoint) for codepoint in range(0x11A8, 0x11C3)]

L_INDEX = {ch: i for i, ch in enumerate(L_TABLE)}
V_INDEX = {ch: i for i, ch in enumerate(V_TABLE)}
T_INDEX = {ch: i for i, ch in enumerate(T_TABLE)}

# Compatibility consonants/medials from a standard Korean keyboard.
KEY_TO_JAMO = {
    'r': 'ㄱ', 'R': 'ㄲ', 's': 'ㄴ', 'e': 'ㄷ', 'E': 'ㄸ', 'f': 'ㄹ',
    'a': 'ㅁ', 'q': 'ㅂ', 'Q': 'ㅃ', 't': 'ㅅ', 'd': 'ㅇ',
    'w': 'ㅈ', 'W': 'ㅉ', 'c': 'ㅊ', 'z': 'ㅋ', 'x': 'ㅌ', 'v': 'ㅍ', 'g': 'ㅎ', 'G': 'ㆆ',
    'k': 'ㅏ', 'o': 'ㅐ', 'i': 'ㅑ', 'j': 'ㅓ', 'p': 'ㅔ', 'P': 'ㅖ',
    'u': 'ㅕ', 'h': 'ㅗ', 'y': 'ㅛ', 'n': 'ㅜ', 'b': 'ㅠ', 'm': 'ㅡ', 'l': 'ㅣ',
}

BOPOMOFO_INITIAL_KEYS = {
    '1': 'ㅂ', '2': 'ㄷ', '5': 'ㅃ',
    'q': 'ㅍ', 'w': 'ㅌ', 'e': 'ㄱ', 'r': 'ㅈ', 't': 'ㄲ',
    'a': 'ㅁ', 's': 'ㄴ', 'd': 'ㅋ', 'f': 'ㅊ', 'g': 'ㆆ',
    'z': 'ㅉ', 'x': 'ㄹ', 'c': 'ㅎ', 'v': 'ㅅ', 'b': 'ㄸ',
}
BOPOMOFO_SYLLABIC_KEYS = {'y': 'ㅈ', 'h': 'ㅊ', 'n': 'ㅅ'}
BOPOMOFO_VOWEL_KEYS = {
    '8': 'ㅏ', '9': 'ㅐ',
    'u': 'ㅣ', 'i': 'ㅓ', ',': 'ㅔ',
    'j': 'ㅜ', 'k': 'ힻ', 'l': 'ᅷ',
    'm': 'ㅕ', '.': 'ㅗ',
}
BOPOMOFO_LITERAL_KEYS = {'o': '’에 '}
BOPOMOFO_SHIFT_VOWEL_KEYS = {'J': 'ㅡ', 'U': 'ㅢ'}
BOPOMOFO_FINAL_KEYS = {'p': 'ㄴ', '/': 'ㅇ'}
BOPOMOFO_RIME_KEYS = {'0': ('ᅡ', 'ᆫ'), ';': ('ᅡ', 'ᆼ')}
BOPOMOFO_TONE_KEYS = {'3': '1', '4': '2', '6': '4', '7': '5'}
BOPOMOFO_SHIFTED_PUNCTUATION = {',': '<', '.': '>', '/': '?', ';': ':', '-': '_'}
BOPOMOFO_SHIFTED_PUNCTUATION_TO_KEY = {value: key for key, value in BOPOMOFO_SHIFTED_PUNCTUATION.items()}
BOPOMOFO_CTRL_PUNCTUATION = {',': ',', '.': '.', '/': '/', ';': ';'}
BOPOMOFO_GUIDE_SYMBOLS = {
    '1': 'ㄅ', '2': 'ㄉ', '3': '', '4': 'ˋ', '5': 'ㆠ',
    '6': 'ˊ', '7': '', '8': 'ㄚ', '9': 'ㄞ', '0': 'ㄢ',
    'q': 'ㄆ', 'w': 'ㄊ', 'e': 'ㄍ', 'r': 'ㄐ', 't': 'ㆣ',
    'y': 'ㄗ', 'u': 'ㄧ', 'i': 'ㄛ', 'o': 'ㄟ', 'p': 'ㄣ',
    'a': 'ㄇ', 's': 'ㄋ', 'd': 'ㄎ', 'f': 'ㄑ', 'g': 'ㄫ',
    'h': 'ㄘ', 'j': 'ㄨ', 'k': 'ㄜ', 'l': 'ㄠ', ';': 'ㄤ',
    'z': '', 'x': 'ㄌ', 'c': 'ㄏ', 'v': 'ㄒ', 'b': 'ㄖ',
    'n': 'ㄙ', 'm': 'ㄩ', ',': 'ㄝ', '.': 'ㄡ', '/': 'ㄥ',
}
BOPOMOFO_GUIDE_OUTPUTS = {
    **BOPOMOFO_INITIAL_KEYS,
    'y': '즈', 'h': '츠', 'n': '스',
    '3': 'ˆ', '4': 'ˋ', '6': 'ˊ', '7': 'ˉ',
    '8': '아', '9': '애',
    'u': '이', 'i': '어', 'o': '’에',
    'J': '으', 'U': '의',
    'j': '우', 'k': 'ᄋힻ', 'l': 'ᄋᅷ',
    'm': '여', ',': '에', '.': '오',
    'p': '은', ';': '앙', '/': '응', '0': '안',
}
BOPOMOFO_KEYS = (
    set(BOPOMOFO_INITIAL_KEYS)
    | set(BOPOMOFO_SYLLABIC_KEYS)
    | set(BOPOMOFO_VOWEL_KEYS)
    | set(BOPOMOFO_LITERAL_KEYS)
    | set(BOPOMOFO_FINAL_KEYS)
    | set(BOPOMOFO_RIME_KEYS)
    | set(BOPOMOFO_TONE_KEYS)
    | set(BOPOMOFO_SHIFTED_PUNCTUATION)
)

# Shift should not insert Latin capitals. Preserve uppercase keys that have
# real IME values; every other shifted letter is treated as its lowercase key.
SHIFT_PRESERVED_KEYS = {'R', 'E', 'Q', 'W', 'P', 'G'}


def normalize_keyboard_char(char: str) -> str:
    if len(char) == 1 and char.isalpha() and char.upper() == char and char not in SHIFT_PRESERVED_KEYS:
        return char.lower()
    return char


COMPAT_TO_L = {
    'ㄱ': 'ᄀ', 'ㄲ': 'ᄁ', 'ㄴ': 'ᄂ', 'ㄷ': 'ᄃ', 'ㄸ': 'ᄄ', 'ㄹ': 'ᄅ',
    'ㅁ': 'ᄆ', 'ㅂ': 'ᄇ', 'ㅃ': 'ᄈ', 'ㅅ': 'ᄉ', 'ㅇ': 'ᄋ',
    'ㅈ': 'ᄌ', 'ㅉ': 'ᄍ', 'ㅊ': 'ᄎ', 'ㅋ': 'ᄏ', 'ㅌ': 'ᄐ', 'ㅍ': 'ᄑ', 'ㅎ': 'ᄒ',
    'ㆆ': 'ᅙ',
}
COMPAT_TO_V = {
    'ㅏ': 'ᅡ', 'ㅐ': 'ᅢ', 'ㅑ': 'ᅣ', 'ㅓ': 'ᅥ', 'ㅔ': 'ᅦ',
    'ㅕ': 'ᅧ', 'ㅖ': 'ᅨ', 'ㅗ': 'ᅩ', 'ㅛ': 'ᅭ', 'ㅜ': 'ᅮ', 'ㅠ': 'ᅲ',
    'ㅡ': 'ᅳ', 'ㅣ': 'ᅵ', 'ㅢ': 'ᅴ',
}
# Hokkien Hangul does not use every Korean batchim.
# Allowed final consonants here are only the finals used by the IME.
# Banned finals: ㄲ ㄳ ㄵ ㄶ ㄺ ㄻ ㄼ ㄽ ㄾ ㄿ ㅄ ㅋ ㅌ ㅍ.
COMPAT_TO_T = {
    'ㄱ': 'ᆨ', 'ㄴ': 'ᆫ', 'ㄷ': 'ᆮ', 'ㄹ': 'ᆯ', 'ㅁ': 'ᆷ',
    'ㅂ': 'ᆸ', 'ㅅ': 'ᆺ', 'ㅇ': 'ᆼ', 'ㅈ': 'ᆽ', 'ㅊ': 'ᆾ',
    'ㅎ': 'ᇂ',
}
T_TO_L = {
    'ᆨ': 'ᄀ', 'ᆩ': 'ᄁ', 'ᆫ': 'ᄂ', 'ᆮ': 'ᄃ', 'ᆯ': 'ᄅ', 'ᆷ': 'ᄆ',
    'ᆸ': 'ᄇ', 'ᆺ': 'ᄉ', 'ᆼ': 'ᄋ', 'ᆽ': 'ᄌ', 'ᆾ': 'ᄎ',
    'ᆿ': 'ᄏ', 'ᇀ': 'ᄐ', 'ᇁ': 'ᄑ', 'ᇂ': 'ᄒ',
}

# Display standalone Hangul letters as compatibility jamo, matching normal Korean IME behavior.
L_TO_COMPAT = {v: k for k, v in COMPAT_TO_L.items()}
V_TO_COMPAT = {v: k for k, v in COMPAT_TO_V.items()}
# Compatibility forms for standalone compound vowels.
# Example: h+k should display/commit as ㅘ, not the medial jamo ᅪ.
V_TO_COMPAT.update({
    'ᅪ': 'ㅘ',
    'ᅫ': 'ㅙ',
    'ᅬ': 'ㅚ',
    'ᅰ': 'ㅞ',
    'ᅱ': 'ㅟ',
    'ᅴ': 'ㅢ',
})
T_TO_COMPAT = {v: k for k, v in COMPAT_TO_T.items()}
# Compatibility forms for the Hokkien-allowed final clusters.
T_TO_COMPAT.update({
    'ᆶ': 'ㅀ',
})

V_COMBINE = {
    ('ᅩ', 'ᅡ'): 'ᅪ', ('ᅩ', 'ᅢ'): 'ᅫ', ('ᅩ', 'ᅵ'): 'ᅬ',
    ('ᅮ', 'ᅦ'): 'ᅰ', ('ᅮ', 'ᅵ'): 'ᅱ',
    ('ᅳ', 'ᅵ'): 'ᅴ',
}
# Only keep final clusters that are not in the banned Hokkien batchim list.
T_COMBINE = {
    ('ᆯ', 'ᇂ'): 'ᆶ',
}
T_SPLIT = {v: k for k, v in T_COMBINE.items()}

SPECIAL_MEDIALS = {'ᅷ', 'ᆤ', 'ힻ'}
HANGUL_CHOSEONG_FILLER = '\u115F'
# Backspace should peel Hokkien non-precomposed vowels back to the
# closest ordinary Hangul vowel first, rather than leaving only the initial.
# Example: ᄋᅷ -> 아 -> ㅇ.
SPECIAL_MEDIAL_BACKSPACE_BASE = {
    'ᅷ': 'ᅡ',   # au -> a
    'ᆤ': 'ᅣ',   # iau -> ia
    'ힻ': 'ᅳ',   # er -> w/ㅡ base
}
EXTRA_INITIALS = {'ᅙ'}

# Raw-key Hokkien shortcut sequences.
# They are generated systematically, so every standard Korean initial supports:
#     initial + mp -> initial + ힻ
#     initial + k+n -> initial + ᅷ
#     initial + i+n -> initial + ᆤ
# Example: dmp -> ᄋힻ, dkn -> ᄋᅷ, din -> ᄋᆤ.
INITIAL_KEY_TO_L = {
    key: COMPAT_TO_L[jamo]
    for key, jamo in KEY_TO_JAMO.items()
    if jamo in COMPAT_TO_L
}

HOKKIEN_SEQUENCE_MAP = {}
for _key, _initial in INITIAL_KEY_TO_L.items():
    HOKKIEN_SEQUENCE_MAP[_key + 'mp'] = _initial + 'ힻ'
    HOKKIEN_SEQUENCE_MAP[_key + 'kn'] = _initial + 'ᅷ'
    HOKKIEN_SEQUENCE_MAP[_key + 'in'] = _initial + 'ᆤ'

# Extra Hokkien initial shortcut.
HOKKIEN_SEQUENCE_MAP.update({
    # Standalone special medial: m+p -> ᅟힻ.
    # There is no compatibility-jamo form for this Hokkien vowel, so use a
    # leading Hangul choseong filler instead of bare ힻ.
    'mp': '\u115Fힻ',
    'kn': '\u115Fᅷ',
    'in': '\u115Fᆤ',
    'mdk': 'ᅙᅡ',
})

DISPLAY_SHORTCUT_HELP = """k+n→ᅷ   i+n→ᆤ   Systematic shortcut: initial+mp→ힻ
Examples: zkn→ᄏᅷ   din→ᄋᆤ   dmp→ᄋힻ   mdk→ᅙᅡ
Tone buttons: ˆ  ˋ  ˊ  ˉ     Tone 3 stays unmarked. Alt+digit inserts a literal numeral. Banned batchim are blocked."""

# Hanri dictionary entries are stored internally as:
#     base_reading_without_tones -> [{'reading': tone_marked_reading, 'hanri': str, 'priority': int, 'row': int}, ...]
# Tones are written directly inside the reading column in the TSV.  Example:
#     랑4    人
#     랑5    弄
# The IME also lets plain 랑 show both candidates, while 랑4 filters to 人 only.
FALLBACK_HANRI_DICT = {
    '가ᄉᅷ': [{'reading': '가ᄉᅷ', 'hanri': '咳嗽', 'priority': 1, 'row': 0}],
    '띤': [{'reading': '띤', 'hanri': '人', 'priority': 1, 'row': 0}],
    '띤심': [{'reading': '띤심', 'hanri': '人參', 'priority': 1, 'row': 0}],
    '띤솅': [{'reading': '띤솅', 'hanri': '人生', 'priority': 1, 'row': 0}],
    '띤수': [{'reading': '띤수', 'hanri': '人事', 'priority': 1, 'row': 0}],
    '겅': [
        {'reading': '겅2', 'hanri': '講', 'priority': 1, 'row': 0, 'form': '本'},
        {'reading': '겅1', 'hanri': '講', 'priority': 2, 'row': 0, 'form': '變'},
    ],
    '랑': [
        {'reading': '랑4', 'hanri': '人', 'priority': 1, 'row': 0},
        {'reading': '랑5', 'hanri': '弄', 'priority': 2, 'row': 0},
    ],
    '세개': [{'reading': '세2개', 'hanri': '世界', 'priority': 1, 'row': 0}],
    '짇띧': [{'reading': '짇띧', 'hanri': '一日', 'priority': 1, 'row': 0}],
    '활히': [{'reading': '활5히2', 'hanri': '歡喜', 'priority': 1, 'row': 0}],
}

HANRI_TSV_FILENAME = 'hokkien_hanri_dict.tsv'
HANRI_DICT_SOURCE = 'built-in fallback'
TONE_DIGITS = set('12345')
# Invisible marker used before an Arabic numeral inserted with Alt+digit.
# The visible text still looks like an ordinary digit, but audio/Lomari can
# distinguish it from a tone digit directly attached to Hangul.
LITERAL_DIGIT_MARK = '​'
ARABIC_NUMERAL_DIGITS = set('0123456789')
LITERAL_DIGIT_DEFAULT_PRONUNCIATIONS = {
    '0': '컹',
    '1': '짇1',
    '2': '띠5',
    '3': '살1',
    '4': '시',
    '5': '꺼5',
    '6': '락1',
    '7': '칟',
    '8': '뵣',
    '9': 'ᄀᅷ2',
}
LITERAL_DIGIT_CONTEXT_PRONUNCIATIONS = {
    ('2', '箍'): '능5',
    ('2', '个'): '능5',
    ('2', '人'): '능5',
}
# Built-in two-digit number patterns before numeric/classifier context characters.
# These are context selectors only: 10號 matches the pronunciation for 10,
# consumes only the Arabic numerals, then leaves the following context character
# to be read normally.
LITERAL_TWO_DIGIT_DATE_NUMBER_TENS = {
    '1': '잡1',
    '2': '띠5잡1',
    '3': '살5잡1',
    '4': '시2잡1',
    '5': '꺼잡1',
    '6': '락잡1',
    '7': '칟1잡1',
    '8': '뵣1잡1',
    '9': 'ᄀᅷ1잡1',
}
LITERAL_TWO_DIGIT_DATE_NUMBER_CONTEXTS = {'號', '日', '月', '歲', '點', '分', '秒', '樓', '層', '章', '節'}
# Before these context characters, digit 1 is pronounced as citation-tone 읻;
# the normal sandhi engine may still change it to 읻1 when connected.
LITERAL_CONTEXTUAL_ONE_READING = '읻'
# Invisible internal tone markers.  They allow the IME to remember tones even
# when the displayed output has no visible mark, especially tone 3.
INTERNAL_TONE_MARKS = {
    '1': '\u2060',
    '2': '\u2061',
    '3': '\u2062',
    '4': '\u2063',
    '5': '\u2064',
}
INTERNAL_TONE_MARK_TO_DIGIT = {v: k for k, v in INTERNAL_TONE_MARKS.items()}
INTERNAL_TONE_MARK_CHARS = set(INTERNAL_TONE_MARK_TO_DIGIT)
NONSTANDARD_READING_MARK = '*'


def reading_is_marked_nonstandard(reading: str) -> bool:
    """True when a TSV reading ends in * to mark a non-standard spelling."""
    return str(reading).strip().endswith(NONSTANDARD_READING_MARK)


def strip_nonstandard_reading_mark(reading: str) -> str:
    """Remove a rightmost TSV non-standard marker without touching content."""
    text = str(reading).strip()
    if text.endswith(NONSTANDARD_READING_MARK):
        return text[:-1].rstrip()
    return text


def strip_reading_tones(reading: str) -> str:
    """Remove tone digits 1-5 and TSV non-standard marker from a reading.

    The TSV writes tones directly in the reading, e.g. 세2개 / 활5히2 / 랑4.
    A rightmost * marks a wrong/non-standard spelling and is ignored for lookup.
    The base reading is used for plain input and pure-Hangul alternatives.
    """
    reading = strip_nonstandard_reading_mark(reading)
    return ''.join(
        ch for ch in reading.strip()
        if (
            ch not in TONE_DIGITS
            and ch not in INTERNAL_TONE_MARK_CHARS
            and ch != NONSTANDARD_READING_MARK
            and ch != LITERAL_DIGIT_MARK
        )
    )


def reading_has_tones(reading: str) -> bool:
    return any((ch in TONE_DIGITS) or (ch in INTERNAL_TONE_MARK_CHARS) for ch in str(reading) if ch != LITERAL_DIGIT_MARK)


def tones_by_base_position(reading: str) -> tuple[str, dict[int, str]]:
    """Return (base_without_tones, tone_by_base_index).

    Tones are stored as digits or internal hidden tone markers after the Hangul
    unit they belong to.  This helper records the tone against the preceding
    base character position after tones are stripped.

    Example:
        옝1완2 -> ('옝완', {0: '1', 1: '2'})
        옝완1  -> ('옝완', {1: '1'})
    """
    base_chars: list[str] = []
    tone_by_pos: dict[int, str] = {}

    for ch in normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(reading)):
        if ch == LITERAL_DIGIT_MARK:
            continue
        if ch in TONE_DIGITS:
            if base_chars:
                tone_by_pos[len(base_chars) - 1] = ch
            continue
        if ch in INTERNAL_TONE_MARK_CHARS:
            if base_chars:
                tone_by_pos[len(base_chars) - 1] = INTERNAL_TONE_MARK_TO_DIGIT[ch]
            continue
        base_chars.append(ch)

    return ''.join(base_chars), tone_by_pos


def typed_tones_are_compatible_with_entry(typed_form: str, entry_reading: str) -> bool:
    """True when a less-strict typed tone form can select an entry.

    This allows the user to omit earlier syllable tones while still using the
    final tone to choose citation/sandhi candidates.

    Example:
        typed 옝완2 matches entry 옝1완2  (citation)
        typed 옝완1 matches entry 옝1완1  (sandhi)
        typed 옝완1 does not match entry 옝1완2
    """
    typed_base, typed_tones = tones_by_base_position(typed_form)
    entry_base, entry_tones = tones_by_base_position(entry_reading)

    if typed_base != entry_base:
        return False

    if not typed_tones:
        return typed_base == entry_base

    # Every tone the user explicitly typed must match the corresponding tone in
    # the entry.  The entry may contain extra earlier tones that the user omitted.
    for pos, tone in typed_tones.items():
        if entry_tones.get(pos) != tone:
            return False

    return True


def toned_suffix_match_start(text: str, base_reading: str) -> int | None:
    """Return the start index if text ends with base_reading plus optional tone digits.

    Example:
        text='활5히2', base_reading='활히' -> 0
        text='abc활5히2', base_reading='활히' -> 3

    This lets a TSV entry written as untoned 활히 still match typed 활5히2,
    while exact toned TSV entries such as 랑4 / 랑5 can still filter candidates.
    """
    if not base_reading:
        return None
    i = len(text) - 1
    j = len(base_reading) - 1

    while j >= 0:
        while i >= 0 and text[i] in TONE_DIGITS:
            i -= 1
        if i < 0 or text[i] != base_reading[j]:
            return None
        i -= 1
        j -= 1

    return i + 1


def last_non_tone_char(text: str) -> str:
    """Return the final non-tone character used for suffix lookup bucketing."""
    for ch in reversed(str(text or '')):
        if ch not in TONE_DIGITS:
            return ch
    return ''


TONE_DIGIT_TO_SYMBOL = str.maketrans({
    '1': 'ˆ',
    '2': 'ˋ',
    '3': '',
    '4': 'ˊ',
    '5': 'ˉ',
    **{ord(mark): '' for mark in INTERNAL_TONE_MARK_CHARS},
})


def display_reading_tones(reading: str) -> str:
    """Convert internal tone digits to display tone symbols for candidate menus.

    Examples:
        랑4 -> 랑ˊ
        세2개 -> 세ˋ개
        활5히2 -> 활ˉ히ˋ
        tone 3 is removed/unmarked.
    """
    return strip_nonstandard_reading_mark(reading).translate(TONE_DIGIT_TO_SYMBOL)


TONE_SYMBOL_TO_DIGIT = str.maketrans({
    # Primary Hangul tone marks.
    'ˆ': '1',
    'ˋ': '2',
    '`': '2',
    'ˊ': '4',
    'ˉ': '5',

    # Alternative tone marks used by the tone-marker/converter output.
    'ꞈ': '1',
    'ˎ': '2',
    'ˏ': '4',
    'ˍ': '5',

    **{ord(mark): digit for mark, digit in INTERNAL_TONE_MARK_TO_DIGIT.items()},
})
TONE_SYMBOLS = set('ˆˋ`ˊˉꞈˎˏˍ') | INTERNAL_TONE_MARK_CHARS


def normalize_tone_symbols_to_digits(text: str) -> str:
    """Convert typed/display tone symbols back to internal digit tones."""
    return text.translate(TONE_SYMBOL_TO_DIGIT)


def remove_apostrophes_for_lookup(text: str) -> str:
    """Remove apostrophe separators for looser dictionary lookup.

    This lets an input such as 쟣바ᄅᆤ match a TSV reading such as
    쟣바2’ᄅᆤ2.  The committed candidates still keep the TSV spelling,
    including the apostrophe.
    """
    return str(text).replace("'", '').replace('’', '')


def has_relaxable_apostrophe(text: str) -> bool:
    """True when apostrophe can be ignored for lookup.

    Internal apostrophes are separators and may be omitted by the user, e.g.
    쟣바ᄅᆤ can match TSV 쟣바’ᄅᆤ.  A leading apostrophe is meaningful,
    so 래 should not match a TSV reading such as ’래.
    """
    text = str(text)
    for i, ch in enumerate(text):
        if ch in {"'", '’'} and 0 < i < len(text) - 1:
            return True
    return False


def lookup_key(text: str) -> str:
    """Normalise text for relaxed candidate matching."""
    return remove_apostrophes_for_lookup(normalize_tone_symbols_to_digits(text))


def is_toned_output_different(text: str) -> bool:
    """True if visible tone formatting changes this text."""
    return format_text_tones_for_output(text, True) != format_text_tones_for_output(text, False)


def is_fully_toned_reading(text: str) -> str:
    """Return the visible pronunciation form with tone marks preserved."""
    return format_text_tones_for_output(text, True)


def is_hangulish_for_tone(ch: str) -> bool:
    """True for Hangul/Jamo characters that may carry a following tone."""
    return (
        ('\uAC00' <= ch <= '\uD7A3')
        or ('\u1100' <= ch <= '\u11FF')
        or ('\u3130' <= ch <= '\u318F')
        or ch in SPECIAL_MEDIALS
        or ch in EXTRA_INITIALS
    )


def can_attach_tone_to_text(text: str, index: int) -> bool:
    """True if a tone at text[index + 1] may attach to text[index]."""
    if index < 0 or index >= len(text):
        return False
    ch = text[index]
    if '\uAC00' <= ch <= '\uD7A3':
        return True
    if ch in T_INDEX and ch != '':
        j = index - 1
        while j >= 0 and text[j] in T_INDEX and text[j] != '':
            j -= 1
        return j >= 1 and (text[j] in V_INDEX or text[j] in SPECIAL_MEDIALS) and (text[j - 1] in L_INDEX or text[j - 1] in EXTRA_INITIALS)
    if ch in V_INDEX or ch in SPECIAL_MEDIALS:
        return index >= 1 and (text[index - 1] in L_INDEX or text[index - 1] in EXTRA_INITIALS or text[index - 1] == HANGUL_CHOSEONG_FILLER)
    return False


def can_attach_tone_to_output_chars(chars: list[str]) -> bool:
    return bool(chars) and can_attach_tone_to_text(''.join(chars), len(chars) - 1)



def is_hanri_char(ch: str) -> bool:
    """True for CJK/Hanri characters."""
    if not ch:
        return False
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF      # CJK Extension A
        or 0x4E00 <= code <= 0x9FFF   # CJK Unified Ideographs
        or 0xF900 <= code <= 0xFAFF   # CJK Compatibility Ideographs
        or 0x20000 <= code <= 0x2A6DF # CJK Extension B
        or 0x2A700 <= code <= 0x2B73F # CJK Extension C
        or 0x2B740 <= code <= 0x2B81F # CJK Extension D
        or 0x2B820 <= code <= 0x2CEAF # CJK Extension E/F
        or 0x2CEB0 <= code <= 0x2EBEF # CJK Extension F/G/H area
        or 0x30000 <= code <= 0x3134F # CJK Extension G/H
    )


def is_hangul_or_hanri_char(ch: str) -> bool:
    """True if a character counts as Hangul/Hokkien-Hangul or Hanri."""
    return is_hangulish_for_tone(ch) or is_hanri_char(ch)


def is_reading_followed_by_connected_text(text: str, index: int) -> bool:
    """True when text[index] is directly followed by a readable unit."""
    j = index + 1
    if j >= len(text):
        return False
    ch = text[j]
    if ch.isspace():
        return False
    if ch in ",.!?:;，。！？：；、’'“”()「」『』…‧~":
        return False
    return bool(ch == '-' or is_hangul_or_hanri_char(ch) or is_latin_word_start(ch) or ch == '[')


def previous_non_tone_char(text: str, pos: int) -> str:
    """Return previous non-tone character before pos, ignoring visible/internal tones."""
    i = min(pos, len(text)) - 1
    while i >= 0:
        ch = text[i]
        if ch not in TONE_DIGITS and ch not in TONE_SYMBOLS:
            return ch
        i -= 1
    return ''


def is_hangul_only_field(text: str) -> bool:
    """True if a TSV field contains only Hangul/Jamo plus tones/spaces.

    This is used to avoid treating Hangul-only values in the hanri column as
    actual Hanri candidates.  For example, if both reading and hanri are
    Hangul-only, the menu should not display the hanri column as a separate
    conversion candidate.
    """
    meaningful_chars = []
    for ch in normalize_tone_symbols_to_digits(str(text).strip()):
        if ch.isspace() or ch in TONE_DIGITS or ch in INTERNAL_TONE_MARK_CHARS:
            continue
        meaningful_chars.append(ch)

    return bool(meaningful_chars) and all(is_hangulish_for_tone(ch) for ch in meaningful_chars)


def field_has_hanri(text: str) -> bool:
    """True if a TSV field contains at least one real Hanri/CJK character."""
    return any(is_hanri_char(ch) for ch in str(text))


def field_is_plain_hanri(text: str) -> bool:
    """True when a field is made only of Hanri/CJK characters."""
    value = str(text or '').strip()
    return bool(value) and all(is_hanri_char(ch) for ch in value)


def split_hanri_hangul_bracket_inner(inner: str) -> tuple[str, str] | None:
    """Parse an explicit [Hanri + Hangul reading] annotation."""
    text = str(inner or '').strip()
    if not text or not is_hanri_char(text[0]):
        return None

    split_at = 0
    while split_at < len(text) and is_hanri_char(text[split_at]):
        split_at += 1

    hanri = text[:split_at].strip()
    reading = text[split_at:].strip()
    if not hanri or not reading:
        return None

    meaningful_reading_chars = [
        ch for ch in normalize_tone_symbols_to_digits(reading)
        if not ch.isspace() and ch not in TONE_DIGITS and ch not in INTERNAL_TONE_MARK_CHARS
    ]
    if not meaningful_reading_chars or not all(
        is_hangulish_for_tone(ch)
        or ch in {"'", '’', '‘', '-', '–', '—'}
        for ch in meaningful_reading_chars
    ):
        return None

    return hanri, reading


def should_display_hanri_entry(entry: dict, base_reading: str = '') -> bool:
    """Return True when the TSV hanri-column value should appear.

    Normal Hanri/CJK candidates are always displayed.  Hangul-only hanri fields
    are displayed only when they are genuine Hangul-to-Hangul replacements,
    not duplicates/helper rows.

    Examples:
        reading=리1호2, hanri=릐ˆ호ˋ  -> display, because 릐호 != 리호
        reading=주ˋ락, hanri=주ˋ락   -> hide duplicate
        reading=주ˋ락, hanri='락     -> hide punctuation/helper fragment
    """
    hanri = str(entry.get('hanri', ''))
    if field_has_hanri(hanri):
        return True

    if not is_hangul_only_field(hanri):
        return False

    entry_reading = str(entry.get('reading', base_reading))
    hanri_base = strip_reading_tones(normalize_tone_symbols_to_digits(hanri))
    reading_base = strip_reading_tones(normalize_tone_symbols_to_digits(entry_reading or base_reading))
    return bool(hanri_base) and hanri_base != reading_base

def format_text_tones_for_output(text: str, show_tones: bool = True, keep_literal_digit_markers: bool = False) -> str:
    """Format tone digits/symbols in Hangul output.

    Tone input remains internal as digits 1-5.  This function is used when
    copying output: digits after Hangul become tone symbols if show_tones=True,
    or are removed if show_tones=False.  Hanri/Chinese characters are left
    alone, so Hanri candidates never receive tone marks.

    Alt+digit inserts an invisible LITERAL_DIGIT_MARK before the digit.  For
    normal display/copy this marker is removed while the digit remains literal;
    for audio/Lomari processing it can be kept so the parser knows the digit is
    not a tone marker.
    """
    out: list[str] = []
    literal_next_digit = False

    for ch in str(text):
        if ch == LITERAL_DIGIT_MARK:
            literal_next_digit = True
            if keep_literal_digit_markers:
                out.append(ch)
            continue

        if literal_next_digit and ch in ARABIC_NUMERAL_DIGITS:
            out.append(ch)
            literal_next_digit = False
            continue
        literal_next_digit = False

        if (ch in TONE_DIGITS or ch in TONE_SYMBOLS) and can_attach_tone_to_output_chars(out):
            if show_tones:
                if ch in TONE_DIGITS:
                    out.append(display_reading_tones(ch))
                elif ch in INTERNAL_TONE_MARK_CHARS:
                    # Internal hidden tone markers are never copied visibly.
                    # Tone 3 remains unmarked.
                    out.append(display_reading_tones(INTERNAL_TONE_MARK_TO_DIGIT[ch]))
                elif ch == '`':
                    out.append('ˋ')
                else:
                    out.append(ch)
            # show_tones=False: skip the tone entirely.
        else:
            out.append(ch)
    return ''.join(out)


def _safe_priority(value: str, default: int = 9999) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def is_single_untoned_precomposed_hangul(reading: str) -> bool:
    """True for one precomposed Hangul syllable with no explicit tone digit.

    Tone 3 is unmarked in the writing system, so single-syllable TSV rows like
    기 記 are interpreted as citation tone 3.  This lets the menu display
    기 (本) and lets the program generate the sandhi form 기2 / 기ˋ (變).
    """
    reading = str(reading).strip()
    return len(reading) == 1 and ('\uAC00' <= reading <= '\uD7A3')


# Hokkien tone sandhi cycles used to generate sandhi candidates automatically.
#
# General open/non-checked syllables:
#   Citation → sandhi: 1→5→3→2→1 and 4→3.
#
# Checked syllables ending in ㄱ ㄷ ㅂ ㅎ ㅀ use a separate entering-tone pattern:
#   Citation → sandhi: 1→3 and 3→1.
# Pronunciation-equivalent finals follow the same class for tone sandhi:
#   final ㅈ behaves like ㄷ; final ㅊ behaves like ㅎ.
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
CHECKED_FINALS_FOR_SANDHI = {'ᆨ', 'ᆮ', 'ᆸ', 'ᇂ', 'ᆶ'}
SANDHI_EQUIVALENT_FINALS = {
    'ᆽ': 'ᆮ',  # final ㅈ is pronounced/sandhis as ㄷ
    'ᆾ': 'ᇂ',  # final ㅊ is pronounced/sandhis as ㅎ
}


def canonicalize_sandhi_final_jamo(final: str) -> str:
    """Return the final-jamo class used by tone sandhi.

    This is separate from spelling: the IME still displays 갗/짖 as written,
    but tone sandhi treats final ㅊ as ㅎ and final ㅈ as ㄷ.
    """
    return SANDHI_EQUIVALENT_FINALS.get(final, final)


def contains_precomposed_hangul(reading: str) -> bool:
    """True if the reading contains at least one ordinary Hangul syllable."""
    return any('\uAC00' <= ch <= '\uD7A3' for ch in str(reading))


def contains_hangul_reading_unit(reading: str) -> bool:
    """True if a TSV reading contains Hangul/Jamo that can carry tone.

    Earlier versions only treated precomposed Hangul syllables such as 기/혱헉
    as unmarked citation tone 3.  Hokkien-specific readings can also be written
    directly as jamo clusters, e.g. ᄀᅷ / 到, so those must also be treated as
    citation forms and displayed with (本).
    """
    return any(is_hangulish_for_tone(ch) for ch in str(reading))


def is_only_compatibility_jamo_reading(reading: str) -> bool:
    """True if the reading column is made only of compatibility jamo.

    Pure compatibility-jamo spellings such as ㅋㅂㅋㅃ are usually sound
    effects or literal jamo strings, not normal syllabic readings.  They should
    still be searchable, but they should not be labelled 本/變 and should not
    receive an automatic sandhi candidate.
    """
    meaningful_chars = []
    for ch in normalize_tone_symbols_to_digits(str(reading).strip()):
        if ch.isspace() or ch in TONE_DIGITS or ch in INTERNAL_TONE_MARK_CHARS:
            continue
        meaningful_chars.append(ch)

    return bool(meaningful_chars) and all('\u3130' <= ch <= '\u318F' for ch in meaningful_chars)


def infer_default_form(reading: str) -> str:
    """Return the automatically inferred 本/變 display label for TSV rows.

    Every normal Hanri reading is treated as a citation form (本).  If no tone
    digit is written, the final character is interpreted as citation tone 3.
    Multi-syllable untoned entries such as 혱헉 / 幸福 and jamo-cluster entries
    such as ᄀᅷ / 到 still display (本) and can generate a sandhi form.

    Exception: if the reading column contains only compatibility jamo such as
    ㅋㅂㅋㅃ, it is treated as a literal jamo string, so no 本/變 label is shown.
    """
    if is_only_compatibility_jamo_reading(reading):
        return ''
    if reading_has_tones(reading):
        return '本'
    if contains_hangul_reading_unit(reading):
        return '本'
    return ''


def last_tone_digit_index(reading: str) -> int | None:
    """Return the index of the last tone digit in a reading, if any."""
    for i in range(len(reading) - 1, -1, -1):
        if reading[i] in TONE_DIGITS:
            return i
    return None


def final_jamo_before_tone(reading: str, tone_index: int) -> str:
    """Return the final jamo of the syllable immediately before a tone digit.

    This works before decompose_precomposed_syllable() is defined, because the
    Hanri TSV is loaded early during module startup.  It supports both ordinary
    precomposed Hangul syllables such as 각/갇/갑/갛/갏 and jamo-cluster forms
    where the final jongseong appears directly before the tone digit.
    """
    if tone_index <= 0:
        return ''

    ch = reading[tone_index - 1]

    # Jamo-cluster readings may end directly in a jongseong jamo before the tone.
    if ch in T_INDEX:
        return ch

    # Ordinary precomposed Hangul syllable.
    if '\uAC00' <= ch <= '\uD7A3':
        final_index = (ord(ch) - 0xAC00) % 28
        return T_TABLE[final_index]

    return ''


def is_checked_final_before_tone(reading: str, tone_index: int) -> bool:
    """True if the syllable before the tone uses the checked-tone class.

    Besides written ㄱ/ㄷ/ㅂ/ㅎ/ㅀ, pronunciation-equivalent final ㅈ and ㅊ
    are handled as ㄷ and ㅎ respectively.
    """
    final = canonicalize_sandhi_final_jamo(final_jamo_before_tone(reading, tone_index))
    return final in CHECKED_FINALS_FOR_SANDHI


def final_hangul_unit_needs_implicit_tone(reading: str) -> tuple[int, str] | None:
    """Return (tone_insert_index, implicit_reading) if final unit has no tone.

    TSV readings may record earlier syllable tones while leaving the final
    syllable unmarked because tone 3 is written without a visible mark.

    Example:
        세2개   -> final 개 is implicit citation tone 3, so sandhi is 세2개2
        활5히2  -> final 히 already has explicit tone 2, so no implicit tone
    """
    last_hangul_index = None
    for i in range(len(reading) - 1, -1, -1):
        if is_hangulish_for_tone(reading[i]):
            last_hangul_index = i
            break

    if last_hangul_index is None:
        return None

    # If a tone digit appears after the final Hangul/Jamo unit, the final tone
    # is already explicit.
    for ch in reading[last_hangul_index + 1:]:
        if ch in TONE_DIGITS or ch in INTERNAL_TONE_MARK_CHARS:
            return None
        if is_hangulish_for_tone(ch):
            return None

    tone_insert_index = last_hangul_index + 1
    implicit_reading = reading[:tone_insert_index] + '3' + reading[tone_insert_index:]
    return tone_insert_index, implicit_reading


def is_apostrophe_boundary_after_tone(reading: str, tone_index: int) -> bool:
    """True if this tone belongs to a Hangul/Hanri unit before an apostrophe.

    Project rule: when Hangul/Hanri is immediately followed by ' or ’, that
    pre-apostrophe unit is citation-final and must not receive an automatically
    generated sandhi (變) tone.

    TSV readings normally write tone digits after the Hangul unit and before
    the apostrophe, e.g. 등1’래.  In that case the digit at tone_index is
    directly followed by the apostrophe.
    """
    if tone_index <= 0 or tone_index + 1 >= len(reading):
        return False
    return (
        reading[tone_index + 1] in {"'", '’'}
        and is_hangulish_for_tone(reading[tone_index - 1])
    )


def is_post_apostrophe_tone(reading: str, tone_index: int) -> bool:
    """True if the tone belongs to a post-apostrophe Hangul/Jamo segment.

    Project rule: forms such as ’ᄅᆤˋ are citation-like attached forms and
    should never create an automatic sandhi (變) candidate.  This is handled
    generally: if the syllable carrying the tone is in the same word segment
    after an apostrophe, the IME does not generate a sandhi variant for it.

    Examples blocked from auto-sandhi:
        ’ᄅᆤ2
        쟣바2’ᄅᆤ2
        食飽’ᄅᆤ2
    """
    if tone_index <= 0:
        return False

    i = tone_index - 1
    saw_hangul_or_hanri = False
    while i >= 0:
        ch = reading[i]
        if ch in {"'", '’'}:
            return saw_hangul_or_hanri
        if ch.isspace():
            return False
        if is_hangul_or_hanri_char(ch):
            saw_hangul_or_hanri = True
        i -= 1
    return False


def citation_to_sandhi_reading(reading: str) -> str | None:
    """Generate the sandhi form for the final syllable of a TSV reading.

    TSV readings are citation forms.  The final syllable may have an explicit
    tone digit, or it may be unmarked tone 3 even when earlier syllables have
    written tones.

    Examples:
        겅2    -> 겅1
        랑4    -> 랑3  (displayed as 랑)
        활5히2 -> 활5히1
        세개   -> 세개2
        세2개  -> 세2개2
    """
    if is_only_compatibility_jamo_reading(reading):
        return None

    implicit_final = final_hangul_unit_needs_implicit_tone(reading)
    if implicit_final is not None:
        idx, implicit_reading = implicit_final
        citation_tone = '3'

        # Apostrophe-attached forms remain citation-like and should not create
        # automatic 變 forms.
        if (
            is_apostrophe_boundary_after_tone(implicit_reading, idx)
            or is_post_apostrophe_tone(implicit_reading, idx)
        ):
            return None

        if is_checked_final_before_tone(implicit_reading, idx):
            sandhi_tone = CHECKED_TONE_SANDHI_MAP.get(citation_tone)
        else:
            sandhi_tone = TONE_SANDHI_MAP.get(citation_tone)

        if sandhi_tone and sandhi_tone != citation_tone:
            return reading[:idx] + sandhi_tone + reading[idx:]
        return None

    idx = last_tone_digit_index(reading)
    if idx is None:
        return None

    # A tone attached to a Hangul/Hanri unit immediately before an apostrophe
    # should remain citation-final, so do not generate a 變 candidate.
    # Likewise, a tone inside a post-apostrophe attached form such as ’ᄅᆤˋ
    # should not create an automatic 變 candidate.
    # Examples blocked:
    #   등1’래      -> no 등5’래
    #   ’ᄅᆤ2       -> no ’ᄅᆤ1
    #   쟣바2’ᄅᆤ2  -> no 쟣바2’ᄅᆤ1
    if is_apostrophe_boundary_after_tone(reading, idx) or is_post_apostrophe_tone(reading, idx):
        return None

    citation_tone = reading[idx]
    if is_checked_final_before_tone(reading, idx):
        sandhi_tone = CHECKED_TONE_SANDHI_MAP.get(citation_tone)
    else:
        sandhi_tone = TONE_SANDHI_MAP.get(citation_tone)

    if not sandhi_tone or sandhi_tone == citation_tone:
        return None
    return reading[:idx] + sandhi_tone + reading[idx + 1:]


def _fallback_hanri_dict() -> dict[str, list[dict]]:
    return {
        reading: [dict(entry) for entry in entries]
        for reading, entries in FALLBACK_HANRI_DICT.items()
    }


def load_hanri_dict(tsv_path: Path | None = None) -> dict[str, list[dict]]:
    """
    Load Hanri candidates from a TSV file.

    Recommended TSV columns:
        reading    hanri    priority    corrected

    If reading ends in *, it is treated as a wrong/non-standard spelling.
    The corrected column can then store the standard Hangul spelling shown on
    the right-hand side of the candidate menu.

    TSV readings are assumed to be citation tone (本), and the program
    automatically generates the corresponding sandhi tone (變).

    Tones are written directly in the reading column, not in a separate tone
    column:
        랑4      人      1
        랑5      弄      2
        세2개    世界    1
        활5히2   歡喜    1

    The program stores these under their tone-stripped base readings.  Therefore
    plain 랑 shows the TSV citation candidates, while 랑4 shows only citation 人 and generated 랑3/랑 can show the sandhi form when typed explicitly.
    """
    global HANRI_DICT_SOURCE

    if tsv_path is None:
        tsv_path = next((path for path in hanri_tsv_path_candidates() if path.exists()), bundled_resource_path(HANRI_TSV_FILENAME))

    if not tsv_path.exists():
        HANRI_DICT_SOURCE = 'built-in fallback; TSV not found'
        return _fallback_hanri_dict()

    entries: dict[str, list[dict]] = {}

    try:
        with tsv_path.open('r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f, delimiter='\t'))

        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if not rows:
            raise ValueError('TSV has no valid rows.')

        first = [cell.strip().lower() for cell in rows[0]]
        has_header = 'reading' in first and 'hanri' in first

        if has_header:
            header = first
            data_rows = rows[1:]
            reading_col = header.index('reading')
            hanri_col = header.index('hanri')
            priority_col = header.index('priority') if 'priority' in header else None
            corrected_col = header.index('corrected') if 'corrected' in header else None
            row_offset = 2
        else:
            # Headerless TSV: reading / hanri / priority.
            # The corrected column requires a header so old 3-column files remain unambiguous.
            data_rows = rows
            reading_col = 0
            hanri_col = 1
            priority_col = 2
            corrected_col = None
            row_offset = 1

        for offset, row in enumerate(data_rows, start=row_offset):
            reading_cell = row[reading_col].strip() if len(row) > reading_col else ''
            hanri = row[hanri_col].strip() if len(row) > hanri_col else ''
            corrected_cell = row[corrected_col].strip() if corrected_col is not None and len(row) > corrected_col else ''

            if not reading_cell or not hanri:
                continue

            is_nonstandard = reading_is_marked_nonstandard(reading_cell)
            reading_raw = strip_nonstandard_reading_mark(reading_cell)
            corrected = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(corrected_cell)) if corrected_cell else ''

            # Arabic-numeral pronunciation rows are read by
            # load_literal_digit_pronunciations().  They should not become Hanri
            # candidates or ordinary reading entries.
            if reading_raw and reading_raw[0] in ARABIC_NUMERAL_DIGITS and corrected:
                continue

            base_reading = strip_reading_tones(reading_raw)
            priority_text = row[priority_col].strip() if priority_col is not None and len(row) > priority_col else ''
            priority = _safe_priority(priority_text, default=9999)
            form = infer_default_form(reading_raw)

            if not base_reading:
                continue

            citation_entry = {
                'reading': reading_raw,
                'hanri': hanri,
                'priority': priority,
                'row': offset,
                'form': form,
                'auto_sandhi': False,
                'nonstandard': is_nonstandard,
                'corrected': corrected,
            }
            entries.setdefault(base_reading, []).append(citation_entry)

            # Auto-generate sandhi form from citation-toned TSV rows.
            # Example: TSV only needs 겅2 講; the IME also recognises 겅1
            # and labels it as 變.  Generated sandhi entries are labelled 變 automatically.
            if form == '本':
                sandhi_reading = citation_to_sandhi_reading(reading_raw)
                if sandhi_reading and sandhi_reading != reading_raw:
                    sandhi_base = strip_reading_tones(sandhi_reading)
                    corrected_sandhi = citation_to_sandhi_reading(corrected) if corrected else ''
                    if not corrected_sandhi:
                        corrected_sandhi = corrected
                    if sandhi_base:
                        entries.setdefault(sandhi_base, []).append({
                            'reading': sandhi_reading,
                            'citation_reading': reading_raw,
                            'hanri': hanri,
                            'priority': priority,
                            # Put the generated sandhi just after its citation row.
                            'row': offset + 0.01,
                            'form': '變',
                            'auto_sandhi': True,
                            'nonstandard': is_nonstandard,
                            'corrected': corrected_sandhi,
                        })

        loaded: dict[str, list[dict]] = {}
        for reading, rows_for_reading in entries.items():
            seen = set()
            candidates = []
            for entry in sorted(rows_for_reading, key=lambda e: (e['priority'], e['row'], e['hanri'])):
                key = (entry['hanri'], entry.get('reading', ''), entry.get('form', ''), entry.get('corrected', ''))
                if key not in seen:
                    candidates.append(entry)
                    seen.add(key)
            if candidates:
                loaded[reading] = candidates

        if loaded:
            total = sum(len(v) for v in loaded.values())
            HANRI_DICT_SOURCE = f'{tsv_path.name}: {total} Hanri entries / {len(loaded)} readings'
            return loaded

        HANRI_DICT_SOURCE = 'built-in fallback; TSV had no valid entries'
        return _fallback_hanri_dict()

    except Exception as exc:
        HANRI_DICT_SOURCE = f'built-in fallback; could not load TSV ({exc})'
        return _fallback_hanri_dict()


HANRI_DICT = load_hanri_dict()



def numeric_key_digit_prefix_len(key: str) -> int:
    """Return how many leading Arabic digits a numeric TSV key has."""
    count = 0
    for ch in str(key):
        if ch in ARABIC_NUMERAL_DIGITS:
            count += 1
        else:
            break
    return count


def load_literal_digit_pronunciations(
    tsv_path: Path | None = None,
) -> tuple[dict[str, str], dict[tuple[str, str], str], list[tuple[str, str, int]]]:
    """Load Arabic-numeral pronunciation overrides from the normal Hanri TSV.

    Rows are written in the same TSV as ordinary entries, using corrected as the
    hidden Hangul pronunciation:
        reading  hanri  priority  corrected
        1        1      1         짇1
        2        2      1         띠5
        2箍      2箍    1         능5
        10號     10號   1         잡1

    Numeric keys are matched longest-first.  If a key has trailing context such
    as 2箍 or 10號, the context only chooses the pronunciation; the parser
    consumes the numeric part and then continues with 箍/號 normally.
    Built-in fallback patterns also cover 10-99 before the numeric context
    characters in LITERAL_TWO_DIGIT_DATE_NUMBER_CONTEXTS, so those do not
    have to be listed one by one in the TSV.
    """
    defaults = dict(LITERAL_DIGIT_DEFAULT_PRONUNCIATIONS)
    contexts = dict(LITERAL_DIGIT_CONTEXT_PRONUNCIATIONS)
    pattern_map: dict[str, str] = {}

    # Built-in fallback patterns.  TSV rows below can overwrite these.
    for digit, reading in defaults.items():
        pattern_map[digit] = reading
    for (digit, following), reading in contexts.items():
        pattern_map[digit + following] = reading
    for following in LITERAL_TWO_DIGIT_DATE_NUMBER_CONTEXTS:
        pattern_map['1' + following] = LITERAL_CONTEXTUAL_ONE_READING

    # Hardcoded date/number-label pattern requested for the context set:
    #   10-19 -> 잡1 + ones
    #   20-29 -> 띠5잡1 + ones
    #   30    -> 살5잡1, 40 -> 시2잡1, etc.
    # x=0 is silent after 十, so 10 is 잡1, 20 is 띠5잡1, ...
    for tens_digit, tens_reading in LITERAL_TWO_DIGIT_DATE_NUMBER_TENS.items():
        for ones_digit in ARABIC_NUMERAL_DIGITS:
            if ones_digit == '0':
                ones_reading = ''
            elif ones_digit == '1':
                ones_reading = LITERAL_CONTEXTUAL_ONE_READING
            else:
                ones_reading = defaults.get(ones_digit, ones_digit)
            number_key = tens_digit + ones_digit
            number_reading = tens_reading + ones_reading
            for following in LITERAL_TWO_DIGIT_DATE_NUMBER_CONTEXTS:
                pattern_map[number_key + following] = number_reading

    if tsv_path is None:
        tsv_path = next((path for path in hanri_tsv_path_candidates() if path.exists()), bundled_resource_path(HANRI_TSV_FILENAME))

    if not tsv_path.exists():
        patterns = sorted(
            ((key, reading, numeric_key_digit_prefix_len(key)) for key, reading in pattern_map.items()),
            key=lambda item: (len(item[0]), item[2]), 
            reverse=True,
        )
        return defaults, contexts, patterns

    try:
        with tsv_path.open('r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f, delimiter='\t'))
    except Exception:
        patterns = sorted(
            ((key, reading, numeric_key_digit_prefix_len(key)) for key, reading in pattern_map.items()),
            key=lambda item: (len(item[0]), item[2]),
            reverse=True,
        )
        return defaults, contexts, patterns

    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        patterns = sorted(
            ((key, reading, numeric_key_digit_prefix_len(key)) for key, reading in pattern_map.items()),
            key=lambda item: (len(item[0]), item[2]),
            reverse=True,
        )
        return defaults, contexts, patterns

    first = [cell.strip().lower() for cell in rows[0]]
    has_header = 'reading' in first and 'corrected' in first
    if has_header:
        header = first
        data_rows = rows[1:]
        reading_col = header.index('reading')
        corrected_col = header.index('corrected')
    else:
        patterns = sorted(
            ((key, reading, numeric_key_digit_prefix_len(key)) for key, reading in pattern_map.items()),
            key=lambda item: (len(item[0]), item[2]),
            reverse=True,
        )
        return defaults, contexts, patterns

    for row in data_rows:
        reading_cell = row[reading_col].strip() if len(row) > reading_col else ''
        corrected_cell = row[corrected_col].strip() if len(row) > corrected_col else ''
        if not reading_cell or not corrected_cell:
            continue

        reading_key = strip_nonstandard_reading_mark(reading_cell)
        corrected = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(corrected_cell))
        if not corrected:
            continue

        digit_prefix_len = numeric_key_digit_prefix_len(reading_key)
        if digit_prefix_len <= 0:
            continue

        pattern_map[reading_key] = corrected
        if len(reading_key) == 1 and reading_key in ARABIC_NUMERAL_DIGITS:
            defaults[reading_key] = corrected
        elif digit_prefix_len == 1 and len(reading_key) == 2:
            contexts[(reading_key[0], reading_key[1])] = corrected

    patterns = sorted(
        ((key, reading, numeric_key_digit_prefix_len(key)) for key, reading in pattern_map.items()),
        key=lambda item: (len(item[0]), item[2]),
        reverse=True,
    )
    return defaults, contexts, patterns


DIGIT_PRONUNCIATIONS, DIGIT_CONTEXT_PRONUNCIATIONS, DIGIT_PRONUNCIATION_PATTERNS = load_literal_digit_pronunciations()


def literal_digit_reading(digit: str, following_char: str = '') -> str:
    """Return hidden Hangul reading for one Arabic numeral."""
    digit = str(digit)
    following_char = str(following_char or '')[:1]
    return DIGIT_CONTEXT_PRONUNCIATIONS.get(
        (digit, following_char),
        DIGIT_PRONUNCIATIONS.get(digit, digit),
    )


def literal_digit_token_at(text: str, index: int) -> tuple[str, int] | None:
    """Return (digit, end_index) for a literal Arabic numeral at index."""
    if index < 0 or index >= len(text):
        return None
    ch = text[index]
    if ch == LITERAL_DIGIT_MARK and index + 1 < len(text) and text[index + 1] in ARABIC_NUMERAL_DIGITS:
        return text[index + 1], index + 2
    if ch in ARABIC_NUMERAL_DIGITS:
        return ch, index + 1
    return None


def literal_digit_sequence_at(text: str, index: int) -> tuple[str, int] | None:
    """Return (visible_digits, end_index) for a run of literal Arabic digits.

    The visible digits may be stored plainly (pasted text) or as Alt+digit
    markers, where the internal marker precedes the visible numeral.
    """
    if index < 0 or index >= len(text):
        return None

    digits: list[str] = []
    i = index
    while i < len(text):
        ch = text[i]
        if ch == LITERAL_DIGIT_MARK and i + 1 < len(text) and text[i + 1] in ARABIC_NUMERAL_DIGITS:
            digits.append(text[i + 1])
            i += 2
            continue
        if ch in ARABIC_NUMERAL_DIGITS:
            digits.append(ch)
            i += 1
            continue
        break

    if not digits:
        return None
    return ''.join(digits), i


def literal_digit_source_end_after_count(text: str, index: int, count: int) -> int | None:
    """Return source index after consuming count literal digits."""
    if count <= 0:
        return index

    seen = 0
    i = index
    while i < len(text) and seen < count:
        ch = text[i]
        if ch == LITERAL_DIGIT_MARK and i + 1 < len(text) and text[i + 1] in ARABIC_NUMERAL_DIGITS:
            i += 2
            seen += 1
            continue
        if ch in ARABIC_NUMERAL_DIGITS:
            i += 1
            seen += 1
            continue
        return None
    return i if seen == count else None


def literal_number_reading_at(text: str, index: int) -> tuple[str, int] | None:
    """Return (hidden_reading, end_index) for a numeric TSV pronunciation.

    Longest TSV pattern wins.  Pure numeric keys consume that many digits.
    Contextual keys such as 2人 or 10號 check the following context but consume
    only the Arabic numeral part, so the following Hanri character is still read
    normally after the number.
    """
    digit_run = literal_digit_sequence_at(text, index)
    if digit_run is None:
        return None
    digits, _run_end = digit_run

    for key, reading, digit_count in DIGIT_PRONUNCIATION_PATTERNS:
        numeric_part = key[:digit_count]
        suffix = key[digit_count:]
        if not numeric_part or not digits.startswith(numeric_part):
            continue
        digit_end = literal_digit_source_end_after_count(text, index, digit_count)
        if digit_end is None:
            continue
        if suffix and not text.startswith(suffix, digit_end):
            continue
        return reading, digit_end

    first = literal_digit_token_at(text, index)
    if first is None:
        return None
    digit, digit_end = first
    following_char = text[digit_end] if digit_end < len(text) else ''
    return literal_digit_reading(digit, following_char), digit_end


def decompose_precomposed_syllable(ch: str) -> tuple[str, str, str] | None:
    """Return (initial, medial, final) for a normal Hangul syllable."""
    if not ('\uAC00' <= ch <= '\uD7A3'):
        return None
    idx = ord(ch) - 0xAC00
    initial = L_TABLE[idx // 588]
    medial = V_TABLE[(idx % 588) // 28]
    final = T_TABLE[idx % 28]
    return initial, medial, final




def medial_typing_components(medial: str) -> list[str]:
    """Return the simple vowel components used to type a medial.

    This lets the predictive menu stay open while the user is midway through
    a compound-vowel syllable.  Example: 쀄 is typed as ㅃ + ㅜ + ㅔ, so the
    intermediate display 쟣바뿌 should still be recognised as a prefix for
    쟣바’쀄.
    """
    reverse_v = {v: k for k, v in V_COMBINE.items()}
    if medial in reverse_v:
        first, second = reverse_v[medial]
        return [first, second]
    if medial in V_INDEX:
        return [medial]
    return []


def precomposed_syllable_typing_prefixes(ch: str) -> set[str]:
    """Return normal IME midway displays for one precomposed syllable.

    For a dictionary syllable like 쀄, this returns ㅃ and 뿌.  For a checked
    syllable like 힐, this returns ㅎ and 히.  These prefixes are used only for
    prediction, not for committed output.
    """
    decomposed = decompose_precomposed_syllable(ch)
    if decomposed is None:
        return set()

    initial, medial, final = decomposed
    result: set[str] = set()

    compat_initial = L_TO_COMPAT.get(initial)
    if compat_initial:
        result.add(compat_initial)

    components = medial_typing_components(medial)
    if components:
        # The first vowel component is the most important midway state for
        # compound vowels: ㅃ+ㅜ -> 뿌 before ㅃ+ㅜ+ㅔ -> 쀄.
        first_medial = components[0]
        result.add(compose_syllable(initial, first_medial, ''))

        # If the syllable has a final consonant, the no-final syllable is also
        # a midway state: 히 before 힐.
        if final:
            result.add(compose_syllable(initial, medial, ''))

    return {item for item in result if item and item != ch}


def raw_keyboard_prefix_display(raw_prefix: str) -> str:
    """Display state after typing a raw keyboard prefix normally.

    This is used for Hokkien shortcut readings.  Example: the final dictionary
    unit ᄅힻ is typed by f+m+p; before p is pressed, the visible state is 르.
    Therefore forms midway through raw shortcuts can keep their menu alive.
    """
    output = ''
    initial = ''
    medial = ''
    final = ''

    def buffer_text() -> str:
        if initial and medial:
            return compose_syllable(initial, medial, final)
        if initial:
            return L_TO_COMPAT.get(initial, initial)
        if medial:
            return V_TO_COMPAT.get(medial, medial)
        if final:
            return T_TO_COMPAT.get(final, final)
        return ''

    def commit() -> None:
        nonlocal output, initial, medial, final
        if initial or medial or final:
            output += buffer_text()
            initial = medial = final = ''

    for raw_ch in raw_prefix:
        raw_ch = normalize_keyboard_char(raw_ch)
        compat = KEY_TO_JAMO.get(raw_ch)
        if not compat:
            commit()
            output += raw_ch
            continue

        if compat in COMPAT_TO_V:
            v = COMPAT_TO_V[compat]
            if not initial and not medial and not final:
                medial = v
            elif initial and not medial:
                medial = v
            elif initial and medial and not final:
                candidate = V_COMBINE.get((medial, v))
                if candidate:
                    medial = candidate
                else:
                    commit()
                    medial = v
            else:
                commit()
                medial = v
            continue

        if compat in COMPAT_TO_L:
            # Mirror the ㅡ+ㅇ -> ㆆ convenience used by the main composer.
            if (not initial) and medial == 'ᅳ' and not final and compat == 'ㅇ':
                medial = ''
                initial = 'ᅙ'
                continue

            new_initial = COMPAT_TO_L[compat]
            if not initial and not medial and not final:
                initial = new_initial
            elif initial and not medial:
                commit()
                initial = new_initial
            elif initial and medial and not final and compat in COMPAT_TO_T:
                final = COMPAT_TO_T[compat]
            else:
                commit()
                initial = new_initial
            continue

        commit()
        output += compat

    return output + buffer_text()


def hokkien_shortcut_midway_prefixes(units: list[tuple[str, str]], use_tones: bool) -> set[str]:
    """Return midway displays for Hokkien raw-key shortcut clusters.

    If a TSV reading contains the final mapped cluster ᄅᆤ, the menu should also
    recognise the normal halfway typing state 랴.  This is generated from the
    same HOKKIEN_SEQUENCE_MAP used by the composer, so it stays systematic.
    """
    result: set[str] = set()
    chars = [c for c, _t in units]

    for i in range(len(units)):
        remaining = ''.join(chars[i:])
        previous = ''.join(c + (t if use_tones else '') for c, t in units[:i])

        for raw_seq, mapped in HOKKIEN_SEQUENCE_MAP.items():
            if not remaining.startswith(mapped):
                continue

            for end in range(1, len(raw_seq)):
                display = raw_keyboard_prefix_display(raw_seq[:end])
                if display:
                    result.add(previous + display)

    return result

def hanri_reading_prefixes(reading: str) -> set[str]:
    """Predictive prefixes generated generally from a TSV reading.

    Tones may be embedded in the reading, e.g. 세2개 or 활5히2.
    Prefixes are generated in two ways:
        - tone-stripped base form: 세ㄱ, 섹
        - tone-written form: 세2ㄱ
    """
    prefixes: set[str] = set()

    def split_units(text: str) -> list[tuple[str, str]]:
        units: list[tuple[str, str]] = []
        i = 0
        while i < len(text):
            ch = text[i]
            tones = ''
            j = i + 1
            while j < len(text) and text[j] in TONE_DIGITS:
                tones += text[j]
                j += 1
            units.append((ch, tones))
            i = j
        return units

    for use_tones in (False, True):
        units = split_units(reading)

        # Midway states for Hokkien raw-key shortcut clusters, generated
        # from HOKKIEN_SEQUENCE_MAP.
        prefixes.update(hokkien_shortcut_midway_prefixes(units, use_tones))

        # Absorbed-initial prefixes for readings where the next syllable is
        # written as jamo, optionally after an apostrophe separator.  This is
        # the same general idea as 세ㄱ -> 섹, but it also works for mixed
        # forms such as 쟣바’ᄅᆤ: while the user is midway through typing the
        # following ᄅ-syllable, their IME may temporarily show 쟣발.
        for i, (ch, tones) in enumerate(units):
            if i == 0 or not (ch in L_INDEX or ch in EXTRA_INITIALS):
                continue

            prev_i = i - 1
            boundary = ''
            if units[prev_i][0] in {"'", '’'}:
                boundary = units[prev_i][0] + (units[prev_i][1] if use_tones else '')
                prev_i -= 1

            if prev_i < 0:
                continue

            prev_ch, prev_tones = units[prev_i]
            prev_decomposed = decompose_precomposed_syllable(prev_ch)
            compat_initial = L_TO_COMPAT.get(ch)
            if (
                prev_decomposed is not None
                and compat_initial
                and compat_initial in COMPAT_TO_T
            ):
                prev_initial, prev_medial, prev_final = prev_decomposed
                if prev_final == '':
                    before_prev = ''.join(c + (t if use_tones else '') for c, t in units[:prev_i])
                    absorbed_previous = before_prev + compose_syllable(prev_initial, prev_medial, COMPAT_TO_T[compat_initial])
                    prefixes.add(absorbed_previous)
                    # Also keep a boundary-preserving form for users who type
                    # the separator before the next initial.
                    if boundary:
                        prefixes.add(before_prev + prev_ch + (prev_tones if use_tones else '') + boundary + L_TO_COMPAT.get(ch, ch))

        # General progressive prefixes.  This keeps the candidate menu stable
        # while typing through mixed jamo/precomposed readings.  For example,
        # if the dictionary contains ᄎᅷ힐ㄹ, the menu can stay visible at
        # ᄎᅷ히, ᄎᅷ힐, and ᄎᅷ힐ㄹ instead of disappearing at the completed
        # intermediate syllable ᄎᅷ힐.  Single-character prefixes are still
        # ignored so bare initials such as ㄸ do not trigger menus too early.
        for end in range(2, len(units)):
            prefix = ''.join(c + (t if use_tones else '') for c, t in units[:end])
            if len(strip_reading_tones(prefix)) >= 2:
                prefixes.add(prefix)

        for i, (ch, tones) in enumerate(units):
            if i == 0:
                continue

            decomposed = decompose_precomposed_syllable(ch)
            if decomposed is None:
                continue

            initial, medial, final = decomposed
            previous = ''.join(c + (t if use_tones else '') for c, t in units[:i])

            for partial in precomposed_syllable_typing_prefixes(ch):
                prefixes.add(previous + partial)

            compat_initial = L_TO_COMPAT.get(initial)

            if compat_initial and compat_initial in COMPAT_TO_T and i > 0:
                prev_ch, prev_tones = units[i - 1]
                prev_decomposed = decompose_precomposed_syllable(prev_ch)
                if prev_decomposed is not None:
                    prev_initial, prev_medial, prev_final = prev_decomposed
                    if prev_final == '' and not use_tones:
                        absorbed_previous = (
                            ''.join(c for c, _t in units[:i - 1])
                            + compose_syllable(prev_initial, prev_medial, COMPAT_TO_T[compat_initial])
                        )
                        prefixes.add(absorbed_previous)

            if final:
                partial_syllable = compose_syllable(initial, medial, '')
                prefixes.add(previous + partial_syllable)

    return {p for p in prefixes if p and p != reading and p != strip_reading_tones(reading)}


def build_hanri_prefix_index(hanri_dict: dict[str, list[dict]]) -> dict[str, list[tuple[str, dict]]]:
    """Map predictive typed prefixes to (base reading, Hanri entry) candidates.

    The index also keeps complete readings of length 2 or more as stable
    predictive keys.  Exact matches are still handled first in
    find_hanri_candidate(), but this prevents the menu from disappearing at
    the moment an absorbed-final prefix becomes a completed syllable.

    Example:
        주재 can be reached through the typing state 줒 -> 주재.
        If 줒 shows a menu, 주재 should keep showing it instead of closing.
    """
    index: dict[str, list[tuple[str, dict]]] = {}

    def add_index(prefix: str, item: tuple[str, dict]) -> None:
        if not prefix:
            return
        # Avoid very early popups from bare one-character readings/initials.
        if len(strip_reading_tones(prefix)) < 2:
            return
        index.setdefault(prefix, [])
        if item not in index[prefix]:
            index[prefix].append(item)

    for base_reading, hanri_entries in hanri_dict.items():
        for entry in hanri_entries:
            # Build prediction prefixes for both plain and tone-written readings.
            # Example: 세2개 gives 세ㄱ/섹 and also 세2ㄱ.
            item = (base_reading, entry)
            for source_reading in {base_reading, entry.get('reading', base_reading)}:
                add_index(source_reading, item)
                add_index(strip_reading_tones(source_reading), item)
                for prefix in hanri_reading_prefixes(source_reading):
                    add_index(prefix, item)
    return index


def build_hanri_prefix_lookup_buckets(prefix_index: dict[str, list[tuple[str, dict]]]) -> dict[str, list[str]]:
    """Bucket predictive prefixes by possible final lookup character."""
    buckets: dict[str, list[str]] = {}
    for prefix in prefix_index:
        if not prefix:
            continue
        bucket_keys = {prefix[-1]}
        if has_relaxable_apostrophe(prefix):
            loose = remove_apostrophes_for_lookup(prefix)
            if loose:
                bucket_keys.add(loose[-1])
        for key in bucket_keys:
            buckets.setdefault(key, []).append(prefix)
    return buckets


DISPLAY_HANRI_HELP = "Hanri candidates: numerals 1–5 after Hangul are tones; Alt+digit inserts a literal number. ↑/↓ choose, Enter commits, Space keeps Hangul, Esc closes. (本)=citation, (變)=auto sandhi; checked finals ㄱ/ㄷ/ㅂ/ㅎ/ㅀ use 1↔3."


def compose_syllable(initial: str, medial: str, final: str = '') -> str:
    """Compose a normal Unicode Hangul syllable, or return a jamo cluster if needed."""
    if initial in L_INDEX and medial in V_INDEX and final in T_INDEX:
        code = 0xAC00 + (L_INDEX[initial] * 21 + V_INDEX[medial]) * 28 + T_INDEX[final]
        return chr(code)
    return initial + medial + final


def should_autocorrect_e_to_ye_before_final(initial: str, medial: str, final: str) -> bool:
    """Autocorrect ㅔ+ㄱ/ㅇ to ㅖ+ㄱ/ㅇ only for readings present in the TSV."""
    if medial != 'ᅦ' or final not in {'ᆨ', 'ᆼ'}:
        return False
    corrected = compose_syllable(initial, 'ᅨ', final)
    return corrected in HANRI_DICT


# Build the predictive Hanri prefix index only after compose_syllable() exists.
HANRI_PREFIX_INDEX = build_hanri_prefix_index(HANRI_DICT)
HANRI_PREFIX_LOOKUP_BUCKETS = build_hanri_prefix_lookup_buckets(HANRI_PREFIX_INDEX)


def build_hanri_candidate_tests(hanri_dict: dict) -> tuple[list[tuple[str, str, list[dict]]], list[tuple[str, list[dict]]]]:
    """Precompute candidate suffix tests so keypress lookup does not rebuild them."""
    exact_tests: list[tuple[str, str, list[dict]]] = []
    for base_reading, entries in hanri_dict.items():
        exact_tests.append((base_reading, base_reading, entries))
        for entry in entries:
            written = entry.get('reading', base_reading)
            if written != base_reading:
                exact_tests.append((written, base_reading, entries))

    seen_tests = set()
    unique_exact_tests: list[tuple[str, str, list[dict]]] = []
    for typed_form, base_reading, entries in exact_tests:
        key = (typed_form, base_reading)
        if key not in seen_tests:
            unique_exact_tests.append((typed_form, base_reading, entries))
            seen_tests.add(key)

    seen_base_tests = set()
    base_tests: list[tuple[str, list[dict]]] = []
    for base_reading, entries in hanri_dict.items():
        if base_reading not in seen_base_tests:
            base_tests.append((base_reading, entries))
            seen_base_tests.add(base_reading)

    return unique_exact_tests, base_tests


def build_hanri_candidate_test_buckets(
    exact_tests: list[tuple[str, str, list[dict]]],
    base_tests: list[tuple[str, list[dict]]],
) -> tuple[dict[str, list[tuple[str, str, list[dict]]]], dict[str, list[tuple[str, list[dict]]]]]:
    """Bucket candidate suffix tests by the only final character that can match."""
    exact_buckets: dict[str, list[tuple[str, str, list[dict]]]] = {}
    base_buckets: dict[str, list[tuple[str, list[dict]]]] = {}

    for typed_form, base_reading, entries in exact_tests:
        key = str(typed_form or '')[-1:]
        if key:
            exact_buckets.setdefault(key, []).append((typed_form, base_reading, entries))

    for base_reading, entries in base_tests:
        key = last_non_tone_char(base_reading)
        if key:
            base_buckets.setdefault(key, []).append((base_reading, entries))

    return exact_buckets, base_buckets


HANRI_EXACT_CANDIDATE_TESTS, HANRI_BASE_CANDIDATE_TESTS = build_hanri_candidate_tests(HANRI_DICT)
HANRI_EXACT_CANDIDATE_BUCKETS, HANRI_BASE_CANDIDATE_BUCKETS = build_hanri_candidate_test_buckets(
    HANRI_EXACT_CANDIDATE_TESTS,
    HANRI_BASE_CANDIDATE_TESTS,
)


def reload_hanri_resources() -> None:
    """Reload TSV-backed dictionaries and every derived lookup index."""
    global HANRI_DICT, HANRI_PREFIX_INDEX, HANRI_PREFIX_LOOKUP_BUCKETS
    global HANRI_EXACT_CANDIDATE_TESTS, HANRI_BASE_CANDIDATE_TESTS
    global HANRI_EXACT_CANDIDATE_BUCKETS, HANRI_BASE_CANDIDATE_BUCKETS
    global DIGIT_PRONUNCIATIONS, DIGIT_CONTEXT_PRONUNCIATIONS, DIGIT_PRONUNCIATION_PATTERNS
    global AUDIO_HANRI_INDEX, MIXED_AUDIO_HANRI_INDEX, AUDIO_HANRI_PRIORITY_INDEX
    global AUDIO_READING_INDEX, AUDIO_READING_INDEX_BY_FIRST

    HANRI_DICT = load_hanri_dict()
    HANRI_PREFIX_INDEX = build_hanri_prefix_index(HANRI_DICT)
    HANRI_PREFIX_LOOKUP_BUCKETS = build_hanri_prefix_lookup_buckets(HANRI_PREFIX_INDEX)
    HANRI_EXACT_CANDIDATE_TESTS, HANRI_BASE_CANDIDATE_TESTS = build_hanri_candidate_tests(HANRI_DICT)
    HANRI_EXACT_CANDIDATE_BUCKETS, HANRI_BASE_CANDIDATE_BUCKETS = build_hanri_candidate_test_buckets(
        HANRI_EXACT_CANDIDATE_TESTS,
        HANRI_BASE_CANDIDATE_TESTS,
    )
    DIGIT_PRONUNCIATIONS, DIGIT_CONTEXT_PRONUNCIATIONS, DIGIT_PRONUNCIATION_PATTERNS = load_literal_digit_pronunciations()
    AUDIO_HANRI_INDEX = build_audio_hanri_index(HANRI_DICT)
    MIXED_AUDIO_HANRI_INDEX = build_mixed_audio_hanri_index(AUDIO_HANRI_INDEX)
    AUDIO_HANRI_PRIORITY_INDEX = build_audio_hanri_priority_index(HANRI_DICT)
    AUDIO_READING_INDEX = build_audio_reading_index(HANRI_DICT)
    AUDIO_READING_INDEX_BY_FIRST = build_audio_reading_index_by_first(AUDIO_READING_INDEX)


# -----------------------------
# Recorded-syllable audio playback
# -----------------------------
AUDIO_FOLDER_NAME = 'audio_files'
AUDIO_TEMP_FILENAME = '_hokkien_ime_playback.wav'
AUDIO_FILE_EXTENSIONS = ('.wav', '.wave')
# Audio smoothing trims phrase-internal recordings:
#   - start trim: skip the first 0.20s of every audio unit except the first
#     unit of a phrase;
#   - end trim: remove the final 0.15s of every audio unit except the final
#     unit of a phrase.
# A phrase starts at the literal beginning of the IME text, or immediately after
# comma/period/exclamation/question/colon/semicolon/hyphen/em-dash punctuation.
# Spaces do not reset this. Apostrophes are deliberately not phrase boundaries.
#
# A 0.25s leading silent buffer is inserted before playback so the first
# recording does not get clipped by the audio device.
#
# Speed-up is not spacing-based: when the whole playback contains more than one
# pronounceable syllable/audio unit, every segment is shortened using the
# pitch-preserving routine.  Normal segments use 1.10x.  Tone 4 segments
# use a gentler 1.03x so the 214 contour is not clipped into 21.
# ㄹ-final segments use the stronger 1.45x only when adjacent to another
# ㄹ-final segment; otherwise they stay at the normal multi-syllable speed.
# Adjacent audio units inside the same phrase are also overlapped/crossfaded
# slightly to reduce the stitched-together feeling.  The overlap is determined
# by the boundary type:
#   previous ㄱ/ㄷ/ㅀ/ㅂ/ㅎ-final unit -> 0.05s
#   previous ㄹ-final unit -> 0.15s
#   otherwise -> 0.10s
AUDIO_CONNECTED_TRIM_SECONDS = 0.20
AUDIO_END_TRIM_SECONDS = 0.15
AUDIO_UNIT_OVERLAP_SECONDS = 0.10
AUDIO_L_FINAL_UNIT_OVERLAP_SECONDS = 0.15
AUDIO_CHECKED_FINAL_UNIT_OVERLAP_SECONDS = 0.05
# Add a short leading silence so Windows/audio devices do not clip the first syllable.
AUDIO_INITIAL_BUFFER_SECONDS = 0.25
AUDIO_MULTI_SYLLABLE_SPEED_FACTOR = 1.10
AUDIO_TONE4_SPEED_FACTOR = 1.03
AUDIO_L_FINAL_SPEED_FACTOR = 1.45
# English-cluster ㅡ-helper syllables keep their consonant onset, then get
# clipped to a short natural lead-in.  This avoids the rushed sound caused by
# globally speeding them up, while still preventing a full extra ㅡ vowel.
AUDIO_ENGLISH_CLUSTER_SPEED_FACTOR = 1.0
AUDIO_ENGLISH_CLUSTER_START_TRIM_SECONDS = 0.24
AUDIO_ENGLISH_CLUSTER_MAX_SECONDS = 0.24
AUDIO_ENGLISH_CLUSTER_FADE_SECONDS = 0.015
AUDIO_ENGLISH_CLUSTER_PREVIOUS_OVERLAP_SECONDS = 0.04
AUDIO_ENGLISH_CLUSTER_NEXT_OVERLAP_SECONDS = 0.04
AUDIO_PHRASE_BOUNDARY_PUNCTUATION = set(',，.。!?！？:：;；-－—\n\r')
AUDIO_IGNORED_PUNCTUATION = set(""" 	
'’‘\"“”.,，。!?！？;；:：、()（）[]【】{}《》〈〉…—-_/\\|·・~～""")
AUDIO_MODE_TAIPEI = 'taipei'
AUDIO_MODE_SINGAPORE = 'singapore'


def singapore_tone1_audio_replacement(
    next_unit: str,
    next_tone: str,
    next_has_explicit_separator_after: bool = False,
) -> str:
    """Return Singapore-mode replacement for non-final non-checked tone 1 audio.

    This affects audio-file selection only.  A current tone 1 syllable is
    replaced only if the current syllable itself is NOT checked-final and is
    directly connected to the following syllable with no intervening separator.

    If the following syllable is citation-final, Singapore mode now uses rising
    tone 4 consistently, regardless of that final syllable's tone/final class.
    Inside a consecutive sandhi chain, the existing dynamic rule still applies
    right-to-left, so a changed tone can compound into the syllable before it.

    If the following syllable itself is immediately followed by an explicit
    separator such as a space, apostrophe, comma, period, bracket, slash, etc.,
    that following syllable is treated as citation-final for this decision.
    Example: 總統 and 總督 both use 정4 before the final syllable, while
    米粉粿 remains 삐5훈4궤2.

        next citation-final any tone/final    -> tone 4 audio
        next dynamic normal tone 3/5          -> tone 4 audio
        next dynamic normal tone 1/2/4        -> tone 5 audio
        next checked tone 1                   -> tone 4 audio
        next checked tone 3                   -> tone 5 audio

    Checked means pronounced with final ㄱ/ㄷ/ㅀ/ㅂ/ㅎ.
    Pronunciation-equivalent finals are handled through audio_unit_has_short_overlap_final(),
    so ㅈ behaves like ㄷ and ㅊ behaves like ㅎ for this decision.
    If the following category is outside the specified set, keep tone 1.
    """
    next_tone = str(next_tone or '3')
    if next_has_explicit_separator_after:
        return '4'

    next_is_checked = audio_unit_has_short_overlap_final(next_unit)

    if next_is_checked:
        if next_tone == '1':
            return '4'
        if next_tone == '3':
            return '5'
        return '1'

    if next_tone in {'3', '5'}:
        return '4'
    if next_tone in {'1', '2', '4'}:
        return '5'
    return '1'

def entry_audio_reading(entry: dict, base_reading: str = '') -> str:
    """Return the Hangul reading that should drive recorded audio playback."""
    corrected = entry.get('corrected', '')
    if entry.get('nonstandard') and corrected:
        return corrected
    return entry.get('reading', base_reading) or base_reading


def build_audio_hanri_index(hanri_dict: dict[str, list[dict]]) -> list[tuple[str, str]]:
    """Map visible Hanri strings back to Hangul readings for audio/playback.

    If multiple TSV rows have the same visible Hanri text, choose the row with
    the best TSV priority.  This matters for homographs/homophones such as:
        치뎔2    市長    2
        치듈2    市長    1
    where visible 市長 must default to 치듈2, not whichever row/base reading was
    loaded first.  Auto-generated sandhi rows are kept behind real TSV rows.
    """
    records: list[tuple[str, str, bool, int, float, str]] = []

    for base_reading, entries in hanri_dict.items():
        for entry in entries:
            hanri = str(entry.get('hanri', ''))
            if not field_has_hanri(hanri):
                continue
            reading = entry_audio_reading(entry, base_reading)
            auto_sandhi = bool(entry.get('auto_sandhi'))
            priority = int(entry.get('priority', 9999))
            try:
                row_value = float(entry.get('row', 9999))
            except Exception:
                row_value = 9999.0

            for key in (
                hanri,
                format_text_tones_for_output(hanri, True),
                format_text_tones_for_output(hanri, False),
            ):
                key = str(key)
                if key:
                    records.append((key, reading, auto_sandhi, priority, row_value, hanri))

    # Longest visible key still wins for parsing, so longer Hanri phrases beat
    # shorter component characters.  For the same key, priority decides the
    # default pronunciation, then row order as a deterministic tie-break.
    records.sort(key=lambda item: (-len(item[0]), item[0], item[2], item[3], item[4], item[5], item[1]))

    items: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for key, reading, _auto_sandhi, _priority, _row_value, _hanri in records:
        if key not in seen_keys:
            items.append((key, reading))
            seen_keys.add(key)

    return items

def is_audio_hangul_only_override_field(text: str) -> bool:
    """True when a TSV hanri field is a Hangul-only audio override.

    Unlike the candidate-menu helper, this deliberately allows a leading
    connector apostrophe.  Rows such as:
        ’꽈    ’꽈
    mean the attached form ’꽈 is an explicit pronunciation override, so
    typed 等’꽈 should use 꽈3 instead of falling through to the bare 꽈2 row.
    Apostrophes are separators/attachment marks, not pronunciation units.
    """
    meaningful_chars = []
    for ch in normalize_tone_symbols_to_digits(str(text).strip()):
        if (
            ch.isspace()
            or ch in TONE_DIGITS
            or ch in INTERNAL_TONE_MARK_CHARS
            or ch in {"'", '’', '‘'}
        ):
            continue
        meaningful_chars.append(ch)

    return bool(meaningful_chars) and all(is_hangulish_for_tone(ch) for ch in meaningful_chars)


def build_audio_hanri_priority_index(hanri_dict: dict[str, list[dict]]) -> list[tuple[str, str, int]]:
    records: list[tuple[str, str, bool, int, float, str]] = []

    for base_reading, entries in hanri_dict.items():
        for entry in entries:
            hanri = str(entry.get('hanri', ''))
            if not field_has_hanri(hanri):
                continue
            reading = entry_audio_reading(entry, base_reading)
            auto_sandhi = bool(entry.get('auto_sandhi'))
            priority = int(entry.get('priority', 9999))
            try:
                row_value = float(entry.get('row', 9999))
            except Exception:
                row_value = 9999.0

            for key in (
                hanri,
                format_text_tones_for_output(hanri, True),
                format_text_tones_for_output(hanri, False),
            ):
                key = str(key)
                if key:
                    records.append((key, reading, auto_sandhi, priority, row_value, hanri))

    records.sort(key=lambda item: (-len(item[0]), item[0], item[2], item[3], item[4], item[5], item[1]))

    items: list[tuple[str, str, int]] = []
    seen_keys: set[str] = set()
    for key, reading, _auto_sandhi, priority, _row_value, _hanri in records:
        if key not in seen_keys:
            items.append((key, reading, priority))
            seen_keys.add(key)

    return items


def audio_hanri_run_end(text: str, index: int) -> int:
    end = index
    while end < len(text) and is_hanri_char(text[end]):
        end += 1
    return end


def priority_audio_hanri_match(text: str, index: int) -> tuple[str, str] | None:
    if index >= len(text) or not is_hanri_char(text[index]):
        return None

    run_end = audio_hanri_run_end(text, index)
    records = AUDIO_HANRI_PRIORITY_INDEX
    memo: dict[int, tuple[tuple[int, int, int], tuple[str, str] | None]] = {}

    def best_at(pos: int) -> tuple[tuple[int, int, int], tuple[str, str] | None]:
        if pos >= run_end:
            return (0, 0, 0), None
        if pos in memo:
            return memo[pos]

        best_score = (1_000_000, 1_000_000, 1_000_000)
        best_first: tuple[str, str] | None = None

        for key, reading, priority in records:
            if not key or contains_apostrophe_boundary(key):
                continue
            if not text.startswith(key, pos):
                continue
            after = pos + len(key)
            if after > run_end:
                continue
            rest_score, _rest_first = best_at(after)
            score = (rest_score[0], int(priority) + rest_score[1], 1 + rest_score[2])
            if score < best_score:
                best_score = score
                best_first = (key, reading)

        rest_score, _rest_first = best_at(pos + 1)
        unmatched_score = (1 + rest_score[0], 9999 + rest_score[1], 1 + rest_score[2])
        if unmatched_score < best_score:
            best_score = unmatched_score
            best_first = None

        memo[pos] = (best_score, best_first)
        return memo[pos]

    _score, first = best_at(index)
    return first

def build_audio_reading_index(hanri_dict: dict[str, list[dict]]) -> list[tuple[str, str]]:
    """Map visible Hangul spellings to tone-written readings for audio.

    Important rule for raw unmarked Hangul:
        Unmarked Hangul typed by the user is tone 3 by default and is already
        treated as the surface/sandhi value.  It must not be re-sandhied just
        because another syllable follows.

    Therefore ordinary Hanri rows such as:
        시4    時
        시     時
    must NOT make plain typed 시 play as 시4 or sandhi as 시2.

    Exception:
        If the TSV hanri column itself is Hangul-only, it is being used as an
        explicit Hangul-to-Hangul pronunciation entry.  In that case its
        unmarked visible form may map to the TSV's tone-written reading, e.g.:
        쉬2    쉬ˋ
    lets typed 쉬 play as 쉬2, and that TSV-owned unit can still undergo normal
    connected-speech sandhi when appropriate.

    Apostrophe-attached Hangul-only rows are also explicit overrides. Example:
        ’꽈    ’꽈
    lets typed 等’꽈 use 꽈3 from the exact attached TSV row, instead of the
    separate bare 꽈2 entry.
    """
    items: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(key: str, reading: str) -> None:
        key = str(key)
        reading = str(reading)
        if key and reading and (key, reading) not in seen:
            items.append((key, reading))
            seen.add((key, reading))

    def add_exact_toned_forms(source: str, reading: str) -> None:
        """Add only tone-explicit spellings for source -> reading.

        These are safe because the user explicitly typed/committed the tone.
        We deliberately do not add tone-stripped keys here.  Tone 3 is visually
        unmarked, so its display form is not added as a dictionary key; plain
        unmarked Hangul must remain raw tone 3 instead of a TSV match.
        """
        source = str(source)
        if not source or not reading_has_tones(normalize_tone_symbols_to_digits(source)):
            return

        source_digits = normalize_tone_symbols_to_digits(source)
        bare = strip_reading_tones(source_digits)
        add(source, reading)
        add(source_digits, reading)

        visible = display_reading_tones(source_digits)
        if visible != bare:
            add(visible, reading)

        formatted = format_text_tones_for_output(source_digits, True)
        if formatted != bare:
            add(formatted, reading)

    def add_unmarked_override_forms(source: str, reading: str) -> None:
        """Add tone-free keys that are allowed to override raw tone-3 default."""
        source = str(source)
        if not source:
            return
        add(source, reading)
        add(strip_reading_tones(source), reading)
        add(display_reading_tones(source), reading)
        add(format_text_tones_for_output(source, True), reading)
        add(format_text_tones_for_output(source, False), reading)

    for base_reading, entries in hanri_dict.items():
        for entry in entries:
            reading = entry_audio_reading(entry, base_reading)
            written = str(entry.get('reading', base_reading) or base_reading)
            hanri_raw = str(entry.get('hanri', ''))
            hanri_is_hangul_only = is_audio_hangul_only_override_field(hanri_raw) and not field_has_hanri(hanri_raw)

            # 1) Exact tone-written/readable forms always work.
            #    Example: typed 시4 / 시ˊ should use 시4 audio.
            for source in {written, reading}:
                add_exact_toned_forms(source, reading)

            # 2) Do NOT add tone-free keys for ordinary Hanri TSV rows,
            #    even if their reading column is unmarked.  Plain typed Hangul
            #    is treated as already-sandhied tone 3 unless a Hangul-only
            #    hanri-column override below explicitly says otherwise.
            #
            #    Example: 시 / 時 must not make plain 시 become dictionary-owned
            #    and then sandhi as 시2 in 시뎋....  Only actual Hanri 時 uses
            #    the TSV reading.

            # 3) Hangul-only hanri fields are explicit pronunciation overrides.
            #    This is the only case where an unmarked typed Hangul form may
            #    inherit a tone from a TSV row with explicit tones.
            #    Example: 쉬2    쉬ˋ  means typed 쉬 should play 쉬2.
            if hanri_is_hangul_only:
                add_unmarked_override_forms(hanri_raw, reading)

            # 4) Non-standard spelling rows still allow the wrong visible spelling
            #    to route to the corrected audio reading, but only for that exact
            #    dictionary-marked spelling.
            if entry.get('nonstandard') and entry.get('corrected'):
                add_unmarked_override_forms(written, reading)

    return sorted(
        items,
        key=lambda item: (len(strip_reading_tones(item[0])), reading_has_tones(item[0])),
        reverse=True,
    )


def contains_apostrophe_boundary(text: str) -> bool:
    """True if a lookup key/reading contains an apostrophe boundary.

    Audio/Lomari parsing must see apostrophes as real boundaries.  If a long
    TSV key such as 飲’롷킈 is matched before the parser reaches the apostrophe,
    the pre-apostrophe syllable can be treated as connected speech in Singapore
    mode.  Skipping such long keys lets the parser first match 飲, then handle
    ’ as a citation-final boundary.
    """
    return any(ch in str(text) for ch in {"'", '’', '‘'})


def field_is_plain_hanri_key(text: str) -> bool:
    value = str(text or '').strip()
    return bool(value) and all(is_hanri_char(ch) for ch in value)


def build_mixed_audio_hanri_index(audio_hanri_index: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Pre-filter visible keys that mix Hangul/Jamo with Hanri."""
    return [
        (key, reading)
        for key, reading in audio_hanri_index
        if (
            key
            and field_has_hanri(key)
            and not field_is_plain_hanri_key(key)
            and not contains_apostrophe_boundary(key)
        )
    ]


def mixed_audio_hanri_match(text: str, index: int) -> tuple[str, str] | None:
    """Match TSV visible keys that mix Hangul/Jamo with Hanri, e.g. 뽀彩工."""
    source = str(text or '')
    for key, reading in MIXED_AUDIO_HANRI_INDEX:
        if source.startswith(key, index):
            return key, reading
    return None


def build_audio_reading_index_by_first(audio_reading_index: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Bucket audio reading overrides by first visible character."""
    buckets: dict[str, list[tuple[str, str]]] = {}
    for key, reading in audio_reading_index:
        if key:
            buckets.setdefault(str(key)[0], []).append((key, reading))
    return buckets


def audio_reading_candidates_for_char(ch: str) -> list[tuple[str, str]]:
    if ch in {"'", '’', '‘'}:
        candidates: list[tuple[str, str]] = []
        for apostrophe in ("'", '’', '‘'):
            candidates.extend(AUDIO_READING_INDEX_BY_FIRST.get(apostrophe, []))
        return candidates
    return AUDIO_READING_INDEX_BY_FIRST.get(ch, [])


def mark_untoned_audio_units(reading: str, default_tone: str = '3') -> str:
    """Add an explicit default tone to Hangul/Jamo units that have no tone."""
    source = normalize_tone_symbols_to_digits(str(reading or ''))
    out: list[str] = []
    i = 0
    tone_chars = TONE_SYMBOLS.union(TONE_DIGITS).union(INTERNAL_TONE_MARK_CHARS)

    while i < len(source):
        unit_end = audio_unit_end_at(source, i)
        if unit_end is None:
            out.append(source[i])
            i += 1
            continue

        out.append(source[i:unit_end])
        i = unit_end
        has_tone = False
        while (
            i < len(source)
            and source[i] in tone_chars
            and can_attach_tone_to_text(source, i - 1)
        ):
            out.append(source[i])
            has_tone = True
            i += 1
        if not has_tone:
            out.append(default_tone)

    return ''.join(out)


def is_explicit_apostrophe_tone_override(key: str, reading: str) -> bool:
    """True for an attached TSV form such as ’ᄅᆤˋ / ’ᄅᆤ2.

    General post-apostrophe text is forced to tone 3 until the next whitespace.
    Only a TSV/audio-reading entry that itself starts with an apostrophe and
    carries an explicit tone is allowed to override that low-tone rule.
    """
    key_text = normalize_tone_symbols_to_digits(str(key or ''))
    reading_text = normalize_tone_symbols_to_digits(str(reading or ''))
    starts_attached = bool(key_text and key_text[0] in {"'", '’', '‘'})
    return bool(
        starts_attached
        and (reading_has_tones(key_text) or reading_has_tones(reading_text))
    )

AUDIO_HANRI_INDEX = build_audio_hanri_index(HANRI_DICT)
MIXED_AUDIO_HANRI_INDEX = build_mixed_audio_hanri_index(AUDIO_HANRI_INDEX)
AUDIO_HANRI_PRIORITY_INDEX = build_audio_hanri_priority_index(HANRI_DICT)
AUDIO_READING_INDEX = build_audio_reading_index(HANRI_DICT)
AUDIO_READING_INDEX_BY_FIRST = build_audio_reading_index_by_first(AUDIO_READING_INDEX)


def is_ignored_audio_punctuation(ch: str) -> bool:
    return (not ch) or ch.isspace() or ch in AUDIO_IGNORED_PUNCTUATION


def is_audio_phrase_boundary(ch: str) -> bool:
    """True for punctuation that resets audio first/last character logic.

    Apostrophes are intentionally not included: 食飽’ᄅᆤ remains one phrase for
    trimming, even though the apostrophe may still affect dictionary/sandhi
    behaviour elsewhere.
    """
    return bool(ch) and ch in AUDIO_PHRASE_BOUNDARY_PUNCTUATION


def audio_folder_path() -> Path:
    """Return the pronunciation audio folder in bundle, repo, or cwd layouts."""
    candidates = [
        bundled_resource_path(AUDIO_FOLDER_NAME),
        repo_public_path(AUDIO_FOLDER_NAME),
        Path.cwd() / AUDIO_FOLDER_NAME,
        Path.cwd() / 'public' / AUDIO_FOLDER_NAME,
    ]
    for folder in candidates:
        if folder.exists():
            return folder
    return candidates[0]


# Pronunciation-equivalent audio lookup rules.
# These rules are deliberately applied to the audio-file lookup layer only:
# the spelling shown in the IME is not changed, but files can be shared when
# the Hokkien pronunciation is identical.
# Examples:
#     갓 -> 가   ㅅ final is silent
#     짖 -> 짇   ㅈ final is pronounced as ㄷ
#     갗 -> 갛   ㅊ final is pronounced as ㅎ
#     릐 -> 리   ㅢ is pronounced like ㅣ
#     괴 -> 궤   ㅚ is pronounced like ㅞ
AUDIO_EQUIVALENT_MEDIALS = {
    'ᅴ': 'ᅵ',
    'ᅬ': 'ᅰ',
}
AUDIO_EQUIVALENT_FINALS = {
    'ᆺ': '',
    'ᆽ': 'ᆮ',
    'ᆾ': 'ᇂ',
}
AUDIO_EQUIVALENT_COMPAT_VOWELS = {
    'ㅢ': 'ㅣ',
    'ㅚ': 'ㅞ',
}
AUDIO_EQUIVALENT_COMPAT_FINALS = {}


def canonicalize_audio_unit(unit: str) -> str:
    """Return the pronunciation-equivalent spelling used for audio lookup.

    This is general and structural: it decomposes Hangul syllables/jamo clusters
    and rewrites only the medial/final positions that are pronounced identically
    in this Hokkien Hangul audio system.  It does not alter the displayed IME
    text and it does not rewrite initial consonants.
    """
    text = str(unit)
    out: list[str] = []
    i = 0

    while i < len(text):
        ch = text[i]

        decomposed = decompose_precomposed_syllable(ch)
        if decomposed is not None:
            initial, medial, final = decomposed
            medial = AUDIO_EQUIVALENT_MEDIALS.get(medial, medial)
            final = AUDIO_EQUIVALENT_FINALS.get(final, final)
            out.append(compose_syllable(initial, medial, final))
            i += 1
            continue

        # Hokkien jamo cluster: initial + medial + optional final(s).
        if is_initial_jamo(ch) and i + 1 < len(text) and is_vowel_jamo(text[i + 1]):
            initial = ch
            medial = AUDIO_EQUIVALENT_MEDIALS.get(text[i + 1], text[i + 1])
            j = i + 2
            finals: list[str] = []
            while j < len(text) and text[j] in T_INDEX and text[j] != '':
                finals.append(AUDIO_EQUIVALENT_FINALS.get(text[j], text[j]))
                j += 1
            out.append(initial + medial + ''.join(finals))
            i = j
            continue

        # Standalone ㅢ is a vowel, not a final consonant, so it can safely be
        # mapped to standalone ㅣ.  Standalone final consonant letters are not
        # rewritten because without a syllable context ㅅ/ㅈ/ㅊ may be initials.
        if ch in AUDIO_EQUIVALENT_COMPAT_VOWELS:
            out.append(AUDIO_EQUIVALENT_COMPAT_VOWELS[ch])
            i += 1
            continue
        if ch in AUDIO_EQUIVALENT_COMPAT_FINALS:
            out.append(AUDIO_EQUIVALENT_COMPAT_FINALS[ch])
            i += 1
            continue

        out.append(ch)
        i += 1

    return ''.join(out)


AUDIO_SHORT_OVERLAP_FINALS = {'ᆨ', 'ᆮ', 'ᆶ', 'ᆸ', 'ᇂ'}


def audio_unit_final_jamo(unit: str) -> str:
    """Return the pronounced final jamo of the last Hangul/Jamo unit.

    This is structural, not example-based: precomposed Hangul and Hokkien
    jamo clusters are decomposed/canonicalised first, so pronunciation-equivalent
    spellings such as 짖 -> 짇 and 갗 -> 갛 inherit the timing class of ㄷ/ㅎ.
    The ㅀ final is deliberately kept as ᆶ so it can receive the shorter
    checked-final overlap rather than the ㄹ-final overlap.
    """
    text = canonicalize_audio_unit(str(unit))
    if not text:
        return ''

    i = 0
    last_final = ''
    while i < len(text):
        ch = text[i]
        decomposed = decompose_precomposed_syllable(ch)
        if decomposed is not None:
            _initial, _medial, final = decomposed
            last_final = final
            i += 1
            continue

        if is_initial_jamo(ch) and i + 1 < len(text) and is_vowel_jamo(text[i + 1]):
            j = i + 2
            final = ''
            while j < len(text) and text[j] in T_INDEX and text[j] != '':
                final = text[j]
                j += 1
            last_final = final
            i = j
            continue

        if ch == 'ㄹ':
            last_final = 'ᆯ'
        elif ch == 'ㄱ':
            last_final = 'ᆨ'
        elif ch == 'ㄷ':
            last_final = 'ᆮ'
        elif ch == 'ㅂ':
            last_final = 'ᆸ'
        elif ch == 'ㅎ':
            last_final = 'ᇂ'
        elif ch == 'ㅀ':
            last_final = 'ᆶ'
        i += 1

    return last_final


def audio_unit_has_l_final(unit: str) -> bool:
    """True when an audio unit is pronounced with final ㄹ."""
    return audio_unit_final_jamo(unit) == 'ᆯ'


def audio_unit_has_short_overlap_final(unit: str) -> bool:
    """True for finals ㄱ/ㄷ/ㅀ/ㅂ/ㅎ, which use only 0.05s overlap."""
    return audio_unit_final_jamo(unit) in AUDIO_SHORT_OVERLAP_FINALS

def audio_unit_initial_medial_final(unit: str) -> tuple[str, str, str] | None:
    """Return the first syllabic unit's (initial, medial, final) for audio rules."""
    text = str(unit)
    if not text:
        return None

    decomposed = decompose_precomposed_syllable(text[0])
    if decomposed is not None:
        return decomposed

    if len(text) >= 2 and is_initial_jamo(text[0]) and is_vowel_jamo(text[1]):
        final = ''
        j = 2
        while j < len(text) and text[j] in T_INDEX and text[j] != '':
            final = text[j]
            j += 1
        return text[0], text[1], final

    return None


def audio_unit_starts_with_initial(unit: str, initial: str) -> bool:
    parsed = audio_unit_initial_medial_final(unit)
    return bool(parsed and parsed[0] == initial)


def replace_audio_unit_initial(unit: str, new_initial: str) -> str:
    """Replace the initial of the first syllabic audio unit.

    This is audio-only.  The spelling shown in the IME and the Lomari preview
    are not changed.
    """
    text = str(unit)
    if not text:
        return text

    decomposed = decompose_precomposed_syllable(text[0])
    if decomposed is not None:
        _initial, medial, final = decomposed
        return compose_syllable(new_initial, medial, final) + text[1:]

    if len(text) >= 2 and is_initial_jamo(text[0]) and is_vowel_jamo(text[1]):
        j = 2
        while j < len(text) and text[j] in T_INDEX and text[j] != '':
            j += 1
        return new_initial + text[1:j] + text[j:]

    return text


def apply_d_final_onset_tensing_to_audio_phrase(
    phrase_units: list[tuple[str, str, bool, bool, bool]]
) -> list[tuple[str, str, bool, bool, bool]]:
    """Use ㄸ-initial audio after a directly connected ㄷ/ㅈ-final syllable.

    Examples:
        raw 짇에       -> audio units 짇 + 떼
        raw 짖에       -> audio units 짖 + 떼
        TSV 짇에4     -> audio units 짇3 + 떼4
        TSV 짖에4     -> audio units 짖3 + 떼4

    TSV readings may package several unmarked syllables plus one final tone as
    a single audio unit, e.g. 짇에4 becomes ('짇에', '4').  Before applying
    onset tensing, split only such a multi-syllable unit when it contains the
    target ㄷ/ㅈ-final + ㅇ-initial boundary.  Earlier split syllables keep
    implicit tone 3; the original tone stays on the final syllable.

    Final ㅈ belongs to the same pronunciation class as final ㄷ for this audio
    rule, matching the existing sandhi/audio equivalence rules.

    Only audio lookup units are rewritten.  The IME spelling and Lomari preview
    are unchanged.  Spaces, apostrophes, and punctuation still block the rule.
    """
    expanded: list[tuple[str, str, bool, bool, bool]] = []

    def is_d_class_final(unit: str) -> bool:
        parsed = audio_unit_initial_medial_final(unit)
        return bool(
            parsed is not None
            and canonicalize_sandhi_final_jamo(parsed[2]) == 'ᆮ'
        )

    for unit, tone, link_to_next, separator_after, eligible in phrase_units:
        parts = split_untoned_hangul_units(unit)

        has_internal_trigger = False
        if len(parts) > 1:
            for idx in range(len(parts) - 1):
                next_parsed = audio_unit_initial_medial_final(parts[idx + 1])
                if (
                    is_d_class_final(parts[idx])
                    and next_parsed is not None
                    and next_parsed[0] == 'ᄋ'
                ):
                    has_internal_trigger = True
                    break

        if not has_internal_trigger:
            expanded.append((unit, tone, link_to_next, separator_after, eligible))
            continue

        last_part_index = len(parts) - 1
        for idx, part in enumerate(parts):
            is_last_part = idx == last_part_index
            expanded.append((
                part,
                tone if is_last_part else '3',
                link_to_next if is_last_part else True,
                separator_after if is_last_part else False,
                eligible if is_last_part else False,
            ))

    result = list(expanded)

    for idx in range(len(result) - 1):
        current_unit, _current_tone, link_to_next, _separator_after, _eligible = result[idx]
        if not link_to_next:
            continue

        next_unit, next_tone, next_link, next_separator, next_eligible = result[idx + 1]
        next_parsed = audio_unit_initial_medial_final(next_unit)

        if (
            is_d_class_final(current_unit)
            and next_parsed is not None
            and next_parsed[0] == 'ᄋ'
        ):
            result[idx + 1] = (
                replace_audio_unit_initial(next_unit, 'ᄄ'),
                next_tone,
                next_link,
                next_separator,
                next_eligible,
            )

    return result


def audio_unit_is_u_syllable(unit: str, initial: str) -> bool:
    """True for a short English-cluster helper syllable like 브/스/트."""
    parsed = audio_unit_initial_medial_final(unit)
    return bool(parsed and parsed[0] == initial and parsed[1] == 'ᅳ' and parsed[2] == '')


def english_cluster_reduction_flags(
    phrase_units: list[tuple[str, str, bool, bool, bool]]
) -> list[bool]:
    """Mark ㅡ-helper syllables that should be shortened for English clusters.

    The user-facing pattern notation treats ㄹ-, ㄸ-, ㅂ-, etc. as any following
    syllable with that initial.  Only directly connected units are considered;
    spaces, apostrophes, and punctuation break the link before this function is
    called through the existing singapore_link_to_next flag.
    """
    flags = [False] * len(phrase_units)

    for idx in range(len(phrase_units) - 1):
        current, _tone, link_to_next, _separator_after, _eligible = phrase_units[idx]
        if not link_to_next:
            continue

        next_unit = phrase_units[idx + 1][0]
        next_parsed = audio_unit_initial_medial_final(next_unit)
        if next_parsed is None:
            continue
        next_initial, _next_medial, _next_final = next_parsed

        # 브ㄹ-, 쁘ㄹ-, 그ㄹ-, 끄ㄹ-, 흐ㄹ-, 스ㄹ-, 트ㄹ-
        if next_initial == 'ᄅ' and any(
            audio_unit_is_u_syllable(current, initial)
            for initial in {'ᄇ', 'ᄈ', 'ᄀ', 'ᄁ', 'ᄒ', 'ᄉ', 'ᄐ'}
        ):
            flags[idx] = True

        # 브ㄸ-, 쁘ㄸ-, 드ㄸ-, 뜨ㄸ-, 그ㄸ-, 끄ㄸ-, 흐ㄸ-
        if next_initial == 'ᄄ' and any(
            audio_unit_is_u_syllable(current, initial)
            for initial in {'ᄇ', 'ᄈ', 'ᄃ', 'ᄄ', 'ᄀ', 'ᄁ', 'ᄒ'}
        ):
            flags[idx] = True

        # 스ㅂ-, 스ㄷ-, 스ㄱ-, 스ㅁ-, 스ㄴ-
        if audio_unit_is_u_syllable(current, 'ᄉ') and next_initial in {'ᄇ', 'ᄃ', 'ᄀ', 'ᄆ', 'ᄂ'}:
            flags[idx] = True

        # 스흐 / 스트: both ㅡ-helper syllables are shortened.
        if audio_unit_is_u_syllable(current, 'ᄉ') and (
            audio_unit_is_u_syllable(next_unit, 'ᄒ')
            or audio_unit_is_u_syllable(next_unit, 'ᄐ')
        ):
            flags[idx] = True
            flags[idx + 1] = True

    return flags



def audio_lookup_units(unit: str) -> list[str]:
    """Return audio lookup spellings, canonical pronunciation first."""
    original = str(unit)
    canonical = canonicalize_audio_unit(original)
    result: list[str] = []
    for item in (
        audio_vowel_jamo_to_precomposed_unit(canonical),
        canonical,
        audio_vowel_jamo_to_precomposed_unit(original),
        original,
    ):
        if item and item not in result:
            result.append(item)
    return result


def build_jamo_pronunciation_readings() -> dict[str, str]:
    """Standalone jamo names/readings used for audio and Lomari preview."""
    readings: dict[str, str] = {}

    def add(reading: str, *letters: str) -> None:
        for letter in letters:
            if letter:
                readings[letter] = reading

    for compat, medial in COMPAT_TO_V.items():
        audio_medial = AUDIO_EQUIVALENT_MEDIALS.get(medial, medial)
        if audio_medial in V_INDEX:
            reading = compose_syllable('ᄋ', audio_medial, '') + '1'
            add(reading, compat, medial)

    for medial in V_INDEX:
        if medial:
            audio_medial = AUDIO_EQUIVALENT_MEDIALS.get(medial, medial)
            if audio_medial in V_INDEX:
                add(compose_syllable('ᄋ', audio_medial, '') + '1', medial)

    for medial in SPECIAL_MEDIALS:
        add(HANGUL_CHOSEONG_FILLER + medial + '1', medial, HANGUL_CHOSEONG_FILLER + medial)

    add('기5역1', 'ㄱ', 'ᄀ', 'ᆨ')
    add('샹5기5역1', 'ㄲ', 'ᄁ', 'ᆩ')
    add('니5운1', 'ㄴ', 'ᄂ', 'ᆫ')
    add('디5욷1', 'ㄷ', 'ᄃ', 'ᆮ')
    add('샹5디5욷1', 'ㄸ', 'ᄄ')
    add('리5일1', 'ㄹ', 'ᄅ', 'ᆯ')
    add('미5음4', 'ㅁ', 'ᄆ', 'ᆷ')
    add('비5얍1', 'ㅂ', 'ᄇ', 'ᆸ')
    add('샹5비5얍1', 'ㅃ', 'ᄈ')
    add('시5오1', 'ㅅ', 'ᄉ', 'ᆺ')
    add('이5응1', 'ㅇ', 'ᄋ', 'ᆼ')
    add('ᄐᅷ3이5응1', 'ㆆ', 'ᅙ')
    add('지5웆1', 'ㅈ', 'ᄌ', 'ᆽ')
    add('샹5지5웆1', 'ㅉ', 'ᄍ')
    add('치1웇', 'ㅊ', 'ᄎ', 'ᆾ')
    add('키1역', 'ㅋ', 'ᄏ', 'ᆿ')
    add('티1욷', 'ㅌ', 'ᄐ', 'ᇀ')
    add('피1얍', 'ㅍ', 'ᄑ', 'ᇁ')
    add('히1웋', 'ㅎ', 'ᄒ', 'ᇂ')
    add('리5일5히5웋', 'ㅀ', 'ᆶ')
    return readings


JAMO_PRONUNCIATION_READINGS = build_jamo_pronunciation_readings()


def jamo_pronunciation_reading(unit: str) -> str:
    """Return the full pronunciation reading for a standalone jamo letter."""
    return JAMO_PRONUNCIATION_READINGS.get(str(unit), '')


def audio_vowel_jamo_to_precomposed_unit(unit: str) -> str:
    """Map standalone vowel jamo to their ㅇ-initial audio syllable."""
    text = str(unit)
    if len(text) != 1:
        return ''

    ch = text[0]
    medial = ''
    if ch in COMPAT_TO_V:
        medial = COMPAT_TO_V[ch]
    elif ch in V_INDEX:
        medial = ch
    else:
        for candidate_medial, compat in V_TO_COMPAT.items():
            if compat == ch:
                medial = candidate_medial
                break

    if not medial or medial not in V_INDEX:
        return ''
    medial = AUDIO_EQUIVALENT_MEDIALS.get(medial, medial)
    return compose_syllable('ᄋ', medial, '')


def is_standalone_consonant_audio_unit(unit: str) -> bool:
    """True for consonant letters that should not request audio files."""
    text = str(unit)
    if len(text) != 1:
        return False
    ch = text[0]
    return (
        ch in COMPAT_TO_L
        or ch in COMPAT_TO_T
        or ch in set(T_TO_COMPAT.values())
        or is_initial_jamo(ch)
        or (ch in T_INDEX and ch != '')
    )


def split_untoned_hangul_units(text: str) -> list[str]:
    """Split a no-tone Hangul/Jamo chunk into likely syllable units.

    Exact tone-marked chunks such as 하이1 stay whole before this fallback is
    used.  This fallback is mainly for untoned text or for decomposing a missing
    whole-unit recording into smaller recorded units.
    """
    units: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if '\uAC00' <= ch <= '\uD7A3':
            units.append(ch)
            i += 1
            continue
        if ch == HANGUL_CHOSEONG_FILLER and i + 1 < len(text) and text[i + 1] in SPECIAL_MEDIALS:
            units.append(text[i:i + 2])
            i += 2
            continue
        if is_initial_jamo(ch):
            j = i + 1
            if j < len(text) and is_vowel_jamo(text[j]):
                j += 1
                # Jongseong finals are in the U+11xx table and T_INDEX.
                while j < len(text) and text[j] in T_INDEX and text[j] != '':
                    j += 1
                units.append(text[i:j])
                i = j
                continue
        if is_hangulish_for_tone(ch):
            units.append(ch)
        i += 1
    return [unit for unit in units if unit]


def audio_unit_end_at(text: str, start: int) -> int | None:
    """Return the end offset of one Hangul/Hokkien-Hangul audio unit.

    This is used before dictionary matching so an explicitly typed visible tone
    mark stays attached to the unit it follows.  It works for ordinary
    precomposed syllables and for Hokkien jamo clusters such as ᄋᅷ / ᄋᆤ / ᄋힻ.
    """
    if start < 0 or start >= len(text):
        return None

    ch = text[start]
    if '\uAC00' <= ch <= '\uD7A3':
        return start + 1

    if ch == HANGUL_CHOSEONG_FILLER and start + 1 < len(text) and text[start + 1] in SPECIAL_MEDIALS:
        return start + 2

    if is_initial_jamo(ch) and start + 1 < len(text) and is_vowel_jamo(text[start + 1]):
        end = start + 2
        while end < len(text) and text[end] in T_INDEX and text[end] != '':
            end += 1
        return end

    if is_hangulish_for_tone(ch):
        return start + 1

    return None


def split_audio_reading_units(reading: str) -> list[tuple[str, str]]:
    """Split a Hangul reading into (unit, tone_digit) audio keys.

    Examples:
        리1호2 -> [('리', '1'), ('호', '2')]
        하이1  -> [('하이', '1')]
        띤솅   -> [('띤', '3'), ('솅', '3')]
    """
    text = normalize_tone_symbols_to_digits(strip_nonstandard_reading_mark(str(reading)))
    units: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush_default() -> None:
        nonlocal buf
        if not buf:
            return
        chunk = ''.join(buf)
        for unit in split_untoned_hangul_units(chunk):
            units.append((unit, '3'))
        buf = []

    for ch in text:
        if ch in TONE_DIGITS:
            if buf:
                units.append((''.join(buf), ch))
                buf = []
            continue
        if ch in INTERNAL_TONE_MARK_CHARS:
            if buf:
                units.append((''.join(buf), INTERNAL_TONE_MARK_TO_DIGIT[ch]))
                buf = []
            continue
        if is_hangulish_for_tone(ch):
            buf.append(ch)
            continue
        flush_default()

    flush_default()
    return units


def audio_sandhi_unit(unit: str, tone: str) -> tuple[str, str]:
    """Return the audio key after connected-speech tone sandhi.

    Recorded-audio playback uses citation audio for the final unit of a
    spacing-delimited run, but non-final units should use their sandhi tone.
    Example: 래4 + 쟣븡... with no space becomes 래3 + 쟣븡... for audio.
    """
    unit = str(unit)
    tone = str(tone or '3')
    if not unit or tone not in TONE_DIGITS:
        return unit, tone or '3'

    # Tone sandhi should follow the pronunciation-equivalent audio form.
    # Example: syllables ending in ㅈ use ㄷ audio, so they must also use the
    # checked-final ㄷ sandhi pattern for audio playback.
    audio_unit = canonicalize_audio_unit(unit)
    sandhi_reading = citation_to_sandhi_reading(audio_unit + tone)
    if not sandhi_reading:
        return audio_unit, tone

    sandhi_units = split_audio_reading_units(sandhi_reading)
    if len(sandhi_units) == 1:
        return sandhi_units[0]
    return unit, tone


def lomari_sandhi_unit(unit: str, tone: str) -> tuple[str, str]:
    """Return sandhi tone for the Lomari preview without audio-file spelling aliases.

    Audio lookup may canonicalise pronunciation-equivalent spellings, e.g. ㅚ uses
    ㅞ audio files.  The romanisation preview must preserve the written Hangul
    spelling, so 뾔 before another syllable should become 뾔3 -> boe, not 쀄3 -> bue.
    """
    unit = str(unit)
    tone = str(tone or '3')
    if not unit or tone not in TONE_DIGITS:
        return unit, tone or '3'

    sandhi_reading = citation_to_sandhi_reading(unit + tone)
    if not sandhi_reading:
        return unit, tone

    sandhi_units = split_audio_reading_units(sandhi_reading)
    if len(sandhi_units) == 1:
        return sandhi_units[0]
    return unit, tone


def visible_text_to_audio_segments(text: str, audio_mode: str = AUDIO_MODE_TAIPEI) -> tuple[list[tuple[str, str, bool, bool, bool]], list[str]]:
    """Convert visible mixed text into audio segments.

    Returns (unit, tone, trim_start, trim_end, english_cluster_reduction) for each pronounceable audio unit.

    audio_mode='singapore' changes audio-file tone selection only: eligible
    tone 1 audio units are changed when the current syllable itself is not
    checked-final and the following syllable is directly connected with no space
    or punctuation in between.  Eligible tone 1 includes original/written tone 1
    and normal open tone 2 after ordinary Taipei sandhi changes it to tone 1.
    Checked-final tone 3 that becomes tone 1 through ordinary checked sandhi is
    not eligible.  The following syllable is treated as citation-final when it is
    followed by space/punctuation/apostrophe or by the end of the phrase/input.
    The IME text, TSV, and romanisation preview are not rewritten.

    Start/end trimming is based on phrase boundaries, not spaces:
        - first unit of the whole IME text, or first unit after , . ! ? : ; - —
          and their common CJK/fullwidth forms, keeps its start;
        - final unit of the whole IME text, or final unit before those same
          punctuations, keeps its end;
        - apostrophes do not reset first/last status.

    Dictionary-matched multi-syllable readings from the TSV are treated as
    already carrying their correct internal sandhi.  Therefore, if the TSV has
    an entry such as 어진덩 whose first part is already stored in sandhi form,
    playback does not sandhi 어/진 a second time.  Only the last unit of that
    matched entry may sandhi if it is directly followed by more Hangul/Hanri
    with no spacing/punctuation.

    Apostrophe rule: the final audio unit immediately before an apostrophe
    stays citation-final, even though it remains in the same phrase for
    clipping.  Earlier words before that unit still sandhi normally when they
    are followed by more Hangul/Hanri without punctuation.
    """
    source = format_text_tones_for_output(str(text), True, keep_literal_digit_markers=True)
    segments: list[tuple[str, str, bool, bool, bool]] = []
    unknown_hanri: list[str] = []
    # Each run part is (reading_text, protect_internal_sandhi, from_tsv, force_tone3).
    # Ordinary TSV words are protected internally because the TSV reading is
    # already the authoritative pronunciation for the word.  Numeric TSV/pattern
    # readings are from_tsv=True but protect_internal_sandhi=False, so compounds
    # like 12月 still sandhi across 잡+띠+月.  Raw typed Hangul is not from TSV.
    # from_tsv lets Singapore mode distinguish a word's citation tone 1 from a
    # word-internal or raw tone 1: citation tone 1 follows ordinary Taipei sandhi
    # first and must not be reprocessed by the Singapore special tone-1 rule.
    run_parts: list[tuple[str, bool, bool, bool, bool]] = []
    post_apostrophe_force_tone3 = False
    tone_chars = TONE_SYMBOLS.union(TONE_DIGITS).union(INTERNAL_TONE_MARK_CHARS)
    # Phrase units accumulate across spaces for trimming/crossfade, but the
    # Singapore tone-1 rule only applies across units that are directly connected
    # inside the same no-separator run.  Each item is:
    #     (unit, effective_tone, singapore_link_to_next, separator_after_unit, singapore_tone1_eligible)
    # where singapore_link_to_next is False after spaces or any punctuation,
    # including apostrophe.  singapore_tone1_eligible is True for raw/or already
    # word-internal tone 1.  Tone 1 created by ordinary Taipei sandhi, such as
    # open tone 2 -> tone 1 or checked tone 3 -> tone 1, is NOT reprocessed.
    # A TSV/Hanri word whose own citation tone is 1 is also excluded, so forms
    # such as 쟣희4 and separate Hanri 真 do not get accidentally reprocessed
    # as Singapore tone 1.
    phrase_units: list[tuple[str, str, bool, bool, bool]] = []

    def sandhi_final_raw_run_before_hyphen() -> None:
        nonlocal run_parts
        if not run_parts:
            return
        part_text, protect_internal_sandhi, from_tsv, force_tone3, protect_final_sandhi = run_parts[-1]
        if protect_internal_sandhi or from_tsv or force_tone3:
            return
        part_digits = normalize_tone_symbols_to_digits(part_text)
        if reading_has_tones(part_digits):
            return
        sandhi_reading = citation_to_sandhi_reading(part_digits)
        if sandhi_reading and sandhi_reading != part_text:
            run_parts[-1] = (
                sandhi_reading,
                protect_internal_sandhi,
                from_tsv,
                force_tone3,
                protect_final_sandhi,
            )

    def flush_run(force_citation: bool = False, explicit_separator_after: bool = False, continuation_after: bool = False) -> None:
        nonlocal run_parts, phrase_units
        if not run_parts:
            return

        flattened: list[tuple[str, str, bool, bool, bool]] = []
        for part_text, protect_internal_sandhi, from_tsv, force_tone3, protect_final_sandhi in run_parts:
            part_units = split_audio_reading_units(part_text)
            # Raw typed visible tone marks are intentional.  Do not rewrite them
            # with automatic audio sandhi.  TSV-matched readings are still handled
            # by the TSV protection rule below, because their tones are the
            # dictionary's authoritative pronunciation, not necessarily literal
            # user-forced tone marks.
            explicit_raw_tone = (
                (not protect_internal_sandhi)
                and (not from_tsv)
                and reading_has_tones(normalize_tone_symbols_to_digits(part_text))
            )
            # Unmarked raw Hangul typed directly in the IME is literal tone 3.
            # It must not be automatically sandhi-ed just because another Hangul
            # syllable follows.  The exception is when the visible Hangul matched
            # hokkien_hanri_dict.tsv, because a TSV reading is the authoritative
            # pronunciation and its final unit may still sandhi before a following
            # readable unit.
            raw_unmarked_hangul = bool(
                (not protect_internal_sandhi)
                and (not from_tsv)
                and (not explicit_raw_tone)
                and part_units
            )
            for part_idx, (unit, tone) in enumerate(part_units):
                if force_tone3:
                    tone = '3'
                # Protect only the internal non-final syllables of a TSV-matched
                # reading.  The final syllable remains free to sandhi if another
                # word is directly attached after it with no spacing/punctuation.
                # For unmatched raw Hangul with no tone mark, protect every unit:
                # unmarked means tone 3 regardless of position.
                protect_this_unit = bool(
                    force_tone3
                    or explicit_raw_tone
                    or raw_unmarked_hangul
                    or (
                        protect_final_sandhi
                        and part_idx == len(part_units) - 1
                    )
                    or (
                        protect_internal_sandhi
                        and part_idx < len(part_units) - 1
                    )
                )
                tsv_internal_unit = bool(protect_internal_sandhi and part_idx < len(part_units) - 1)
                tsv_final_citation_unit = bool(from_tsv and part_idx == len(part_units) - 1)
                flattened.append((unit, tone, protect_this_unit, tsv_internal_unit, tsv_final_citation_unit))

        for idx, (unit, tone, protect_sandhi, tsv_internal_unit, tsv_final_citation_unit) in enumerate(flattened):
            original_unit = unit
            original_tone = str(tone or '3')
            # In connected speech, every non-final unit in a no-space run should
            # use sandhi-tone audio, unless that unit is an internal syllable of
            # a TSV-matched reading whose sandhi is already encoded in the TSV.
            #
            # Apostrophe rule: a run immediately before an apostrophe stays in
            # citation tone for audio.  This is separate from clipping: those
            # syllables still remain in the same trimming phrase, so their audio
            # can still be start/end-clipped normally.
            if (
                (idx < len(flattened) - 1 or continuation_after)
                and not protect_sandhi
                and not force_citation
            ):
                # In Singapore audio mode, normal/open tone 1 has its own
                # context-dependent audio mapping.  Leave open tone 1 here so
                # flush_phrase() can inspect the following directly connected
                # unit; spaces and punctuation block that mapping.  Checked-final
                # tone 1 is NOT eligible for the Singapore special rule, so it
                # must still receive ordinary Taipei checked sandhi here (1 -> 3).
                # Other tones receive ordinary Taipei sandhi first.  If open
                # tone 2 becomes tone 1, that tone 1 remains as-is in Singapore.
                if not (
                    audio_mode == AUDIO_MODE_SINGAPORE
                    and str(tone) == '1'
                    and not audio_unit_has_short_overlap_final(unit)
                    and not tsv_final_citation_unit
                ):
                    unit, tone = audio_sandhi_unit(unit, tone)
            # Singapore tone-1 replacement applies only when the next
            # syllable is directly connected with no intervening space or
            # punctuation.  The last unit of every flushed run therefore cannot
            # look across the separator that caused the flush.  If that flush
            # was caused by an explicit separator, remember it so the previous
            # directly connected tone-1 syllable treats this final syllable as
            # citation-final for the dynamic Singapore decision.
            singapore_link_to_next = idx < len(flattened) - 1
            separator_after_unit = bool(explicit_separator_after and idx == len(flattened) - 1)
            singapore_tone1_eligible = bool(
                original_tone == '1'
                and not tsv_final_citation_unit
                and not (from_tsv and original_unit == '가')
            )
            phrase_units.append((unit, tone, singapore_link_to_next, separator_after_unit, singapore_tone1_eligible))
        run_parts = []

    def flush_phrase() -> None:
        nonlocal phrase_units
        if not phrase_units:
            return

        if audio_mode == AUDIO_MODE_SINGAPORE:
            # Singapore tone-1 replacement is dynamic: resolve from right to
            # left so a changed following tone can affect the tone-1 syllable
            # before it.  Links are still local: spaces, apostrophes, and other
            # punctuation break singapore_link_to_next, so the rule cannot jump
            # across separators.
            singapore_units: list[tuple[str, str, bool, bool, bool]] = [
                (unit, str(tone or '3'), singapore_link_to_next, separator_after_unit, singapore_tone1_eligible)
                for unit, tone, singapore_link_to_next, separator_after_unit, singapore_tone1_eligible in phrase_units
            ]
            for idx in range(len(singapore_units) - 2, -1, -1):
                unit, tone, singapore_link_to_next, separator_after_unit, singapore_tone1_eligible = singapore_units[idx]
                if (
                    singapore_link_to_next
                    and singapore_tone1_eligible
                    and not audio_unit_has_short_overlap_final(unit)
                ):
                    next_unit, next_tone, next_link_to_next, next_separator_after, _next_tone1_eligible = singapore_units[idx + 1]
                    next_is_citation_final = bool(next_separator_after or not next_link_to_next)
                    tone = singapore_tone1_audio_replacement(
                        next_unit,
                        next_tone,
                        next_has_explicit_separator_after=next_is_citation_final,
                    )
                    singapore_units[idx] = (unit, tone, singapore_link_to_next, separator_after_unit, singapore_tone1_eligible)
            phrase_units = singapore_units

        # Audio-only onset tensing:
        # a directly connected ㄷ-final syllable makes a following ㅇ-initial
        # syllable use its ㄸ-initial audio counterpart.
        # Example: 짇에 is looked up as 짇 + 떼.
        phrase_units = apply_d_final_onset_tensing_to_audio_phrase(phrase_units)

        english_reduction = english_cluster_reduction_flags(phrase_units)
        last_index = len(phrase_units) - 1
        for idx, (unit, tone, _singapore_link_to_next, _separator_after_unit, _singapore_tone1_eligible) in enumerate(phrase_units):
            trim_start = idx > 0
            trim_end = idx < last_index
            english_cluster_reduction = bool(idx < len(english_reduction) and english_reduction[idx])
            segments.append((unit, tone, trim_start, trim_end, english_cluster_reduction))
        phrase_units = []

    i = 0
    while i < len(source):
        tail = source[i:]
        ch = source[i]
        matched = False

        if ch == '[':
            end = source.find(']', i + 1)
            if end != -1:
                parsed = split_hanri_hangul_bracket_inner(source[i + 1:end])
                if parsed:
                    _hanri, reading = parsed
                    if (
                        end + 1 < len(source)
                        and source[end + 1] == '-'
                        and not reading_has_tones(normalize_tone_symbols_to_digits(reading))
                    ):
                        reading = citation_to_sandhi_reading(reading) or reading
                    run_parts.append((reading, True, True, post_apostrophe_force_tone3, True))
                    i = end + 1
                    continue

        # Apostrophes must be handled before dictionary matching.  The TSV may
        # contain apostrophe-prefixed attached forms such as ’에 / ’ᄅᆤ.  If we
        # let the normal dictionary matcher consume ’에 first, the run before
        # the apostrophe is never flushed as citation-final, so a preceding
        # syllable such as 쉬2 can be wrongly changed to sandhi 쉬1.
        #
        # Therefore: first flush the run before the apostrophe.  A normal flush
        # keeps only the final unit before the apostrophe citation-final, while
        # allowing earlier words to sandhi normally before following Hangul/Hanri.
        # Then, if a known apostrophe-prefixed TSV reading exists, consume that
        # attached form as the next run.  Straight apostrophe is matched against
        # curly-apostrophe TSV keys for pasted/raw text robustness.
        if ch in {"'", '’', '‘'}:
            flush_run(explicit_separator_after=True)
            normalized_tail = '’' + tail[1:]
            for key, reading in AUDIO_READING_INDEX:
                if key and key[0] in {"'", '’', '‘'} and normalized_tail.startswith('’' + key[1:]):
                    override = is_explicit_apostrophe_tone_override(key, reading)
                    run_parts.append((reading, True, True, not override, False))
                    i += len(key)
                    matched = True
                    break
            post_apostrophe_force_tone3 = True
            if matched:
                continue
            i += 1
            continue

        # If the user typed an explicit visible tone mark after a Hangul unit,
        # keep that tone attached before dictionary matching.  Otherwise a shorter
        # untoned dictionary key such as 짇 can consume the syllable first and
        # leave the following ˆ behind, causing tone 1 to be heard as tone 3.
        unit_end = audio_unit_end_at(source, i)
        if (
            unit_end is not None
            and unit_end < len(source)
            and source[unit_end] in tone_chars
            and can_attach_tone_to_text(source, unit_end - 1)
        ):
            tone_end = unit_end
            while tone_end < len(source) and source[tone_end] in tone_chars:
                tone_end += 1
            run_parts.append((source[i:tone_end], False, False, post_apostrophe_force_tone3, False))
            i = tone_end
            continue

        mixed_hanri_match = mixed_audio_hanri_match(source, i)
        if mixed_hanri_match:
            key, reading = mixed_hanri_match
            run_parts.append((mark_untoned_audio_units(reading), True, True, post_apostrophe_force_tone3, False))
            i += len(key)
            continue

        # Hanri conversion first: existing Chinese characters should pronounce
        # through the TSV reading rather than being treated as unknown text.
        hanri_match = priority_audio_hanri_match(source, i)
        if hanri_match:
            key, reading = hanri_match
            run_parts.append((reading, True, True, post_apostrophe_force_tone3, False))
            i += len(key)
            continue

        # Hangul word/reading match, useful for text that is still pure Hangul.
        for key, reading in AUDIO_READING_INDEX:
            if key and tail.startswith(key):
                match_end = i + len(key)
                explicit_final_tone = reading_has_tones(normalize_tone_symbols_to_digits(key))
                reading_text = reading
                if match_end < len(source) and source[match_end] in tone_chars:
                    tone_end = match_end
                    while tone_end < len(source) and source[tone_end] in tone_chars:
                        tone_end += 1
                    reading_text = str(reading) + source[match_end:tone_end]
                    explicit_final_tone = True
                    i = tone_end
                else:
                    i += len(key)
                run_parts.append((reading_text, True, True, post_apostrophe_force_tone3, explicit_final_tone))
                matched = True
                break
        if matched:
            continue

        if ch in tone_chars and i > 0 and not can_attach_tone_to_text(source, i - 1):
            flush_run()
            i += 1
            continue

        literal_number = literal_number_reading_at(source, i)
        if literal_number is not None:
            reading, digit_end = literal_number
            # Numeric readings are dictionary-owned, but their internal syllables
            # still participate in ordinary connected-speech sandhi before the
            # following classifier/date word.
            run_parts.append((reading, False, True, post_apostrophe_force_tone3, False))
            i = digit_end
            continue

        ch = source[i]
        if ch in TONE_SYMBOLS or ch in TONE_DIGITS:
            # A visible/internal tone mark belongs to the preceding raw Hangul
            # unit.  Keep it attached before split_audio_reading_units() runs;
            # otherwise a typed form such as 자ˉ뻐 would lose the 5-tone and be
            # treated like untoned 자.
            if can_attach_tone_to_text(source, i - 1) and run_parts and not run_parts[-1][1]:
                previous_text, previous_protect, previous_from_tsv, previous_force_tone3, previous_protect_final = run_parts[-1]
                run_parts[-1] = (
                    previous_text + ch,
                    previous_protect,
                    previous_from_tsv,
                    previous_force_tone3 or post_apostrophe_force_tone3,
                    previous_protect_final,
                )
            else:
                flush_run()
        elif is_hangulish_for_tone(ch):
            # Raw Hokkien jamo clusters must stay as one audio unit.
            # Example: ᄀᅷ should look up ᄀᅷ3.wav, not separate ᄀ3 + ᅷ3.
            # The same applies to clusters with finals such as ᄀᅷᆯ.
            unit_end = audio_unit_end_at(source, i)
            if unit_end is not None and unit_end > i:
                unit_text = source[i:unit_end]
                pronunciation = jamo_pronunciation_reading(unit_text)
                if pronunciation:
                    run_parts.append((pronunciation, True, True, post_apostrophe_force_tone3, True))
                else:
                    run_parts.append((unit_text, False, False, post_apostrophe_force_tone3, False))
                i = unit_end - 1
            else:
                pronunciation = jamo_pronunciation_reading(ch)
                if pronunciation:
                    run_parts.append((pronunciation, True, True, post_apostrophe_force_tone3, True))
                else:
                    run_parts.append((ch, False, False, post_apostrophe_force_tone3, False))
        elif is_hanri_char(ch):
            flush_run()
            unknown_hanri.append(ch)
        elif is_latin_word_start(ch):
            latin_end = latin_word_end(source, i)
            flush_run(explicit_separator_after=True, continuation_after=True)
            unknown_hanri.append(f'{source[i:latin_end]} (English has no recorded audio)')
            i = latin_end - 1
        elif ch == '-':
            sandhi_final_raw_run_before_hyphen()
            flush_run(explicit_separator_after=True, continuation_after=True)
        elif is_audio_phrase_boundary(ch):
            flush_run(explicit_separator_after=True)
            flush_phrase()
            if ch.isspace():
                post_apostrophe_force_tone3 = False
        elif is_ignored_audio_punctuation(ch):
            # Apostrophes break the sandhi run and force the preceding run to
            # stay in citation tone, but they do not create a new trimming
            # phrase. Spaces simply break the sandhi run.  For Singapore audio
            # sandhi, all such explicit separators also make the previous audio
            # unit citation-final for the syllable before it.
            flush_run(force_citation=(ch in {"'", '’', '‘'}), explicit_separator_after=True)
            if ch.isspace():
                post_apostrophe_force_tone3 = False
        else:
            # Other symbols are separators for sandhi, not audio errors and not
            # first/last reset punctuation.
            flush_run(explicit_separator_after=True)
        i += 1

    flush_run()
    flush_phrase()
    return segments, unknown_hanri

def visible_text_to_audio_units(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Convert visible mixed Hangul/Hanri text into recorded audio units."""
    segments, unknown_hanri = visible_text_to_audio_segments(text)
    return [(unit, tone) for unit, tone, *_trim_flags in segments], unknown_hanri


_AUDIO_FILENAME_CONVERTER = None
_AUDIO_FILENAME_CONVERTER_LOAD_FAILED = False


def load_audio_filename_converter():
    """Load the Lomari converter for ASCII-safe audio filenames."""
    global _AUDIO_FILENAME_CONVERTER, _AUDIO_FILENAME_CONVERTER_LOAD_FAILED
    if _AUDIO_FILENAME_CONVERTER is not None:
        return _AUDIO_FILENAME_CONVERTER
    if _AUDIO_FILENAME_CONVERTER_LOAD_FAILED:
        return None

    path = TONE_MARKER_MODULE_PATH
    try:
        if not path.exists():
            _AUDIO_FILENAME_CONVERTER_LOAD_FAILED = True
            return None
        spec = importlib.util.spec_from_file_location('hokkien_audio_filename_converter', path)
        if spec is None or spec.loader is None:
            _AUDIO_FILENAME_CONVERTER_LOAD_FAILED = True
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if not hasattr(module, 'auto_lomari_from_hangul'):
            _AUDIO_FILENAME_CONVERTER_LOAD_FAILED = True
            return None
        _AUDIO_FILENAME_CONVERTER = module
        return module
    except Exception:
        _AUDIO_FILENAME_CONVERTER_LOAD_FAILED = True
        return None


def audio_lomari_key_from_unit(unit: str) -> str:
    """Return the ASCII Lomari-key spelling used for audio filenames.

    Visible Lomari writes nasalisation with combining tilde-below, e.g. a̰.
    Audio files stay ASCII/cloud-safe and follow the keyboard spelling, e.g. al.
    """
    text = str(unit or '')
    if not text:
        return ''

    if len(text) >= 2 and text[0] == HANGUL_CHOSEONG_FILLER and text[1] in SPECIAL_MEDIALS:
        return LOMARI_V_TO_RIME.get(text[1], '')

    decomposed = decompose_precomposed_syllable(text[0]) if text else None
    if decomposed is not None:
        initial, medial, final = decomposed
        return cluster_to_base_lomari_for_ime(initial, medial, final)

    if len(text) >= 2 and ('\u1100' <= text[0] <= '\u1112' or text[0] == HANGUL_CHOSEONG_FILLER) and (
        '\u1161' <= text[1] <= '\u1175' or text[1] in SPECIAL_MEDIALS
    ):
        initial = text[0]
        medial = text[1]
        final = ''
        if len(text) >= 3 and '\u11A8' <= text[2] <= '\u11FF':
            final = text[2]
        return cluster_to_base_lomari_for_ime(initial, medial, final)

    if len(text) == 1 and text in COMPAT_TO_V:
        return LOMARI_V_TO_RIME.get(COMPAT_TO_V[text], '')
    if len(text) == 1 and text in COMPAT_TO_L:
        return LOMARI_L_TO_INITIAL.get(COMPAT_TO_L[text], '')
    return ''


def audio_lomari_filename_stem(unit: str, tone: str) -> str:
    """Return the ASCII Lomari-key stem used by renamed audio files."""
    key_stem = audio_lomari_key_from_unit(unit)
    if key_stem:
        return re.sub(r'[^A-Za-z0-9._-]+', '_', key_stem).strip('._-')

    converter = load_audio_filename_converter()
    lomari = ''
    if converter is not None:
        try:
            lomari = converter.auto_lomari_from_hangul(f'{unit}{tone}')
        except Exception:
            lomari = ''
    if not lomari:
        try:
            lomari = hangul_unit_to_lomari(unit)
        except Exception:
            lomari = ''
    if not lomari:
        return ''
    plain = ''.join(
        ch for ch in unicodedata.normalize('NFKD', str(lomari))
        if not unicodedata.combining(ch)
    )
    return re.sub(r'[^A-Za-z0-9._-]+', '_', plain).strip('._-')


def audio_filename_candidates(unit: str, tone: str) -> list[str]:
    """Likely filenames for one recorded syllable/tone."""
    symbol = display_reading_tones(tone)
    stems: list[str] = []
    lomari_stem = audio_lomari_filename_stem(unit, tone)
    if lomari_stem:
        stems.extend([
            f'{lomari_stem}{tone}',
            f'{lomari_stem}_{tone}',
            f'{lomari_stem}_t{tone}',
            f'{lomari_stem}-{tone}',
        ])
    stems.extend([
        f'{unit}{tone}',
        f'{unit}_{tone}',
        f'{unit}_t{tone}',
        f'{unit}-{tone}',
    ])
    if symbol:
        stems.extend([
            f'{unit}{symbol}',
            f'{unit}_{symbol}',
            f'{unit}-{symbol}',
        ])
    if tone == '3':
        stems.extend([unit, f'{unit}_3', f'{unit}_t3', f'{unit}-3'])

    result: list[str] = []
    seen: set[str] = set()
    for stem in stems:
        for ext in AUDIO_FILE_EXTENSIONS:
            name = stem + ext
            if name not in seen:
                result.append(name)
                seen.add(name)
    return result


def find_audio_file(folder: Path, unit: str, tone: str) -> Path | None:
    lookup_tone = audio_lookup_tone_for_unit(unit, tone)
    for lookup_unit in audio_lookup_units(unit):
        for name in audio_filename_candidates(lookup_unit, lookup_tone):
            path = folder / name
            if path.exists() and path.is_file():
                return path
    return None


def audio_lookup_tone_for_unit(unit: str, tone: str) -> str:
    """Standalone vowel jamo use tone-1 syllable recordings."""
    text = str(unit)
    if (
        len(text) == 1
        and decompose_precomposed_syllable(text) is None
        and audio_vowel_jamo_to_precomposed_unit(text)
        and audio_vowel_jamo_to_precomposed_unit(text) != '으'
    ):
        return '1'
    return str(tone or '3')


def audio_missing_label_for_unit(unit: str, tone: str) -> str:
    lookup_tone = audio_lookup_tone_for_unit(unit, tone)
    lookup_unit = audio_vowel_jamo_to_precomposed_unit(unit) or str(unit)
    return f'{lookup_unit}{lookup_tone}'


def resolve_audio_files_for_unit(folder: Path, unit: str, tone: str) -> tuple[list[Path], list[str]]:
    """Return audio files for a unit, with fallback decomposition if needed."""
    parts = split_untoned_hangul_units(unit)
    if len(parts) > 1:
        files: list[Path] = []
        missing: list[str] = []
        for idx, part in enumerate(parts):
            part_tone = tone if idx == len(parts) - 1 else '3'
            path = find_audio_file(folder, part, part_tone)
            if path is None:
                missing.append(audio_missing_label_for_unit(part, part_tone))
            else:
                files.append(path)
        if not missing and files:
            return files, []

    direct = find_audio_file(folder, unit, tone)
    if direct is not None:
        return [direct], []

    return [], [audio_missing_label_for_unit(unit, tone)]


def is_silent_audio_unit(unit: str, tone: str) -> bool:
    """True for written units that intentionally have no Hokkien audio."""
    if str(tone or '3') not in TONE_DIGITS:
        return False
    text = str(unit)
    if jamo_pronunciation_reading(text):
        return False
    return (
        (text == '으' and str(tone or '3') != '1')
        or (audio_vowel_jamo_to_precomposed_unit(text) == '으' and str(tone or '3') != '1')
        or is_standalone_consonant_audio_unit(text)
    )


def crossfade_pcm16(prev_bytes: bytes, next_bytes: bytes, channels: int) -> bytes:
    """Crossfade two equal-length 16-bit PCM chunks."""
    if not prev_bytes or not next_bytes or len(prev_bytes) != len(next_bytes):
        return next_bytes

    prev = array('h')
    nxt = array('h')
    prev.frombytes(prev_bytes)
    nxt.frombytes(next_bytes)

    # WAV PCM is little-endian.  array('h') follows native endianness.
    if sys.byteorder != 'little':
        prev.byteswap()
        nxt.byteswap()

    total_frames = len(prev) // max(1, channels)
    out = array('h')
    out.extend(prev)
    if total_frames <= 1:
        result = nxt
    else:
        for frame in range(total_frames):
            alpha = frame / (total_frames - 1)
            inv = 1.0 - alpha
            for channel in range(max(1, channels)):
                idx = frame * channels + channel
                sample = int(prev[idx] * inv + nxt[idx] * alpha)
                out[idx] = max(-32768, min(32767, sample))
        result = out

    if sys.byteorder != 'little':
        result.byteswap()
    return result.tobytes()


def fade_out_pcm16(data: bytes, fade_frames: int, channels: int, sample_width: int) -> bytes:
    """Apply a short fade-out to 16-bit PCM data."""
    if sample_width != 2 or channels <= 0 or fade_frames <= 0 or not data:
        return data

    samples = array('h')
    samples.frombytes(data)
    if sys.byteorder != 'little':
        samples.byteswap()

    total_frames = len(samples) // max(1, channels)
    fade_frames = min(fade_frames, total_frames)
    if fade_frames <= 1:
        if sys.byteorder != 'little':
            samples.byteswap()
        return samples.tobytes()

    start_frame = total_frames - fade_frames
    for frame in range(start_frame, total_frames):
        factor = (total_frames - frame - 1) / (fade_frames - 1)
        for channel in range(channels):
            idx = frame * channels + channel
            samples[idx] = int(samples[idx] * factor)

    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


def speed_up_pcm_frames(
    data: bytes,
    sample_rate: int,
    channels: int,
    sample_width: int,
    speed_factor: float,
) -> bytes:
    """Speed up PCM audio without raising pitch.

    Earlier versions sped up connected syllables by dropping individual frames,
    which made the voice sound higher.  This version shortens the recording by
    removing tiny time chunks and crossfading the joins, so the playback rate
    stays normal and the pitch is preserved much better.
    """
    frame_size = sample_width * channels
    if speed_factor <= 1.0 or frame_size <= 0 or sample_rate <= 0 or len(data) <= frame_size:
        return data

    total_frames = len(data) // frame_size
    if total_frames <= sample_rate // 20:
        return data

    # Per cycle, keep 100 ms and remove enough audio to reach the requested
    # speed.  For 1.2x this removes about 20 ms per 100 ms kept.
    keep_frames = max(1, int(sample_rate * 0.100))
    remove_frames = max(1, int(keep_frames * (speed_factor - 1.0)))
    fade_frames = max(1, int(sample_rate * 0.010))

    out = bytearray()
    pos = 0
    while pos < total_frames:
        keep_end = min(pos + keep_frames, total_frames)
        out.extend(data[pos * frame_size:keep_end * frame_size])
        pos = keep_end

        if pos >= total_frames:
            break

        skip_end = min(pos + remove_frames, total_frames)

        # Crossfade from the end of what we kept into the start after the
        # removed chunk.  This smooths the cut without changing pitch.
        can_crossfade = (
            sample_width == 2
            and len(out) >= fade_frames * frame_size
            and skip_end + fade_frames < total_frames
        )
        if can_crossfade:
            fade_bytes = fade_frames * frame_size
            previous = bytes(out[-fade_bytes:])
            del out[-fade_bytes:]
            following = data[skip_end * frame_size:(skip_end + fade_frames) * frame_size]
            out.extend(crossfade_pcm16(previous, following, channels))
            pos = skip_end + fade_frames
        else:
            pos = skip_end

    return bytes(out)



def overlap_pcm16_audio_units(
    previous_data: bytes,
    next_data: bytes,
    overlap_frames: int,
    channels: int,
    sample_width: int,
) -> bytes:
    """Return previous+next with a short overlap/crossfade join.

    The overlap shortens the boundary by AUDIO_UNIT_OVERLAP_SECONDS.  It is
    only applied for 16-bit PCM WAV data; other formats fall back to normal
    concatenation.  The function is deliberately local to audio assembly, so it
    never changes the recorded source files.
    """
    if (
        sample_width != 2
        or channels <= 0
        or overlap_frames <= 0
        or not previous_data
        or not next_data
    ):
        return previous_data + next_data

    frame_size = sample_width * channels
    max_prev_frames = len(previous_data) // frame_size
    max_next_frames = len(next_data) // frame_size
    overlap_frames = min(overlap_frames, max_prev_frames, max_next_frames)
    if overlap_frames <= 0:
        return previous_data + next_data

    overlap_bytes = overlap_frames * frame_size
    prev_head = previous_data[:-overlap_bytes]
    prev_tail = previous_data[-overlap_bytes:]
    next_head = next_data[:overlap_bytes]
    next_tail = next_data[overlap_bytes:]
    return prev_head + crossfade_pcm16(prev_tail, next_head, channels) + next_tail


def concatenate_wav_segments(segments: list[tuple], output_path: Path) -> bool:
    """Concatenate WAV files if they share audio parameters.

    Each segment is either:
        (path, trim_start)
        (path, trim_start, speed_up)                  # old format
        (path, trim_start, trim_end, speed_up)
        (path, trim_start, trim_end, speed_up, l_final, short_overlap_final)
        (path, trim_start, trim_end, speed_up, l_final, short_overlap_final, english_cluster_helper)  # current format

    trim_start skips AUDIO_CONNECTED_TRIM_SECONDS from the beginning.  English
    cluster helpers use their own smaller lead-in trim so the recorded silence
    is skipped without deleting the consonant.
    trim_end removes AUDIO_END_TRIM_SECONDS from the end.
    speed_up may be True/False or a numeric speed factor.  True uses the
    default multi-syllable factor; numeric factors let ㄹ-final segments use
    their faster shortening.  l_final/short_overlap_final/english_cluster_helper
    control whether adjacent overlap uses the normal 0.10s, ㄹ-final 0.15s,
    checked-final 0.05s, or the shorter English-cluster crossfade.
    """
    if not segments:
        return False

    params = None
    comparable_params = None
    frames: list[tuple[bytes, bool, bool, bool, bool]] = []
    try:
        for segment in segments:
            if len(segment) == 2:
                path, trim_start = segment
                trim_end = False
                speed_up = False
                l_final = False
                short_overlap_final = False
                english_cluster_helper = False
            elif len(segment) == 3:
                path, trim_start, speed_up = segment
                trim_end = False
                l_final = False
                short_overlap_final = False
                english_cluster_helper = False
            elif len(segment) == 4:
                path, trim_start, trim_end, speed_up = segment
                l_final = False
                short_overlap_final = False
                english_cluster_helper = False
            elif len(segment) == 5:
                path, trim_start, trim_end, speed_up, l_final = segment
                short_overlap_final = False
                english_cluster_helper = False
            elif len(segment) == 6:
                path, trim_start, trim_end, speed_up, l_final, short_overlap_final = segment
                english_cluster_helper = False
            else:
                path, trim_start, trim_end, speed_up, l_final, short_overlap_final, english_cluster_helper = segment

            if isinstance(speed_up, bool):
                speed_factor = AUDIO_MULTI_SYLLABLE_SPEED_FACTOR if speed_up else 1.0
            else:
                try:
                    speed_factor = float(speed_up)
                except Exception:
                    speed_factor = 1.0

            with wave.open(str(path), 'rb') as wf:
                current_params = wf.getparams()
                comparable = current_params[:3]
                if params is None:
                    params = current_params
                    comparable_params = comparable
                elif comparable != comparable_params:
                    return False

                total_frames = wf.getnframes()
                if english_cluster_helper:
                    start_trim_frames = int(wf.getframerate() * AUDIO_ENGLISH_CLUSTER_START_TRIM_SECONDS)
                else:
                    start_trim_frames = int(wf.getframerate() * AUDIO_CONNECTED_TRIM_SECONDS) if trim_start else 0
                end_trim_frames = int(wf.getframerate() * AUDIO_END_TRIM_SECONDS) if trim_end else 0

                # Avoid trimming an extremely short recording down to empty.
                max_total_trim = max(0, total_frames - 1)
                if start_trim_frames + end_trim_frames > max_total_trim:
                    overflow = start_trim_frames + end_trim_frames - max_total_trim
                    # Preserve the requested start trim as much as possible; reduce
                    # the shorter end trim first if the file is too short.
                    if end_trim_frames >= overflow:
                        end_trim_frames -= overflow
                    else:
                        start_trim_frames = max(0, start_trim_frames - (overflow - end_trim_frames))
                        end_trim_frames = 0

                if start_trim_frames > 0:
                    wf.setpos(start_trim_frames)
                frames_to_read = max(0, total_frames - start_trim_frames - end_trim_frames)
                data = wf.readframes(frames_to_read)

                if speed_factor > 1.0:
                    data = speed_up_pcm_frames(
                        data,
                        wf.getframerate(),
                        wf.getnchannels(),
                        wf.getsampwidth(),
                        speed_factor,
                    )

                if english_cluster_helper:
                    # English-cluster ㅡ-helper syllables need the consonant
                    # onset but not a full extra ㅡ vowel.  Keep a short lead-in
                    # at normal pitch/speed and fade the clipped tail.
                    frame_size = max(1, wf.getsampwidth() * wf.getnchannels())
                    total_data_frames = len(data) // frame_size
                    max_keep_frames = max(1, int(wf.getframerate() * AUDIO_ENGLISH_CLUSTER_MAX_SECONDS))
                    keep_frames = min(total_data_frames, max_keep_frames)
                    data = data[:keep_frames * frame_size]
                    fade_frames = max(1, int(wf.getframerate() * AUDIO_ENGLISH_CLUSTER_FADE_SECONDS))
                    data = fade_out_pcm16(data, fade_frames, wf.getnchannels(), wf.getsampwidth())

                # Overlap only within the same phrase.  Phrase-initial units
                # have trim_start=False, so they do not overlap with the
                # preceding phrase across comma/period/etc.  Spaces and
                # apostrophes do not reset the phrase, so they still allow
                # connected overlap.
                frames.append((data, bool(trim_start), bool(l_final), bool(short_overlap_final), bool(english_cluster_helper)))

        if params is None:
            return False

        # Leading silence prevents the first syllable from being clipped by
        # Windows/audio-device startup latency.  This buffer is silence only; it
        # does not change the recorded syllable timing rules.
        sample_rate = int(params.framerate)
        channels = int(params.nchannels)
        sample_width = int(params.sampwidth)
        lead_frames = max(0, int(sample_rate * AUDIO_INITIAL_BUFFER_SECONDS))
        lead_silence = b'\x00' * lead_frames * channels * sample_width

        with wave.open(str(output_path), 'wb') as out:
            out.setparams(params)
            if lead_silence:
                out.writeframes(lead_silence)

            combined = b''
            previous_l_final = False
            previous_short_overlap_final = False
            previous_english_cluster_helper = False
            normal_overlap_frames = max(0, int(sample_rate * AUDIO_UNIT_OVERLAP_SECONDS))
            l_final_overlap_frames = max(0, int(sample_rate * AUDIO_L_FINAL_UNIT_OVERLAP_SECONDS))
            short_final_overlap_frames = max(0, int(sample_rate * AUDIO_CHECKED_FINAL_UNIT_OVERLAP_SECONDS))
            english_cluster_previous_overlap_frames = max(0, int(sample_rate * AUDIO_ENGLISH_CLUSTER_PREVIOUS_OVERLAP_SECONDS))
            english_cluster_next_overlap_frames = max(0, int(sample_rate * AUDIO_ENGLISH_CLUSTER_NEXT_OVERLAP_SECONDS))
            for data, can_overlap_previous, current_l_final, current_short_overlap_final, current_english_cluster_helper in frames:
                if not combined:
                    combined = data
                elif can_overlap_previous:
                    # Checked endings are clipped tightly into the following unit.
                    # ㄹ-final uses the longer 0.15s overlap before any following
                    # unit, e.g. 셀+띧 / 틸+키 / 댤+댤.  This shortens
                    # the perceived gap without cutting the ㄹ recording itself.
                    if current_english_cluster_helper:
                        # Boundary before an affected ㅡ-helper syllable.
                        overlap_frames = english_cluster_previous_overlap_frames
                    elif previous_english_cluster_helper:
                        # Boundary after an affected ㅡ-helper syllable.
                        overlap_frames = english_cluster_next_overlap_frames
                    elif previous_short_overlap_final:
                        overlap_frames = short_final_overlap_frames
                    elif previous_l_final:
                        overlap_frames = l_final_overlap_frames
                    else:
                        overlap_frames = normal_overlap_frames
                    if overlap_frames > 0:
                        combined = overlap_pcm16_audio_units(
                            combined,
                            data,
                            overlap_frames,
                            channels,
                            sample_width,
                        )
                    else:
                        combined += data
                else:
                    combined += data
                previous_l_final = bool(current_l_final)
                previous_short_overlap_final = bool(current_short_overlap_final)
                previous_english_cluster_helper = bool(current_english_cluster_helper)

            if combined:
                out.writeframes(combined)
        return True
    except Exception:
        return False

def concatenate_wav_files(paths: list[Path], output_path: Path) -> bool:
    """Backward-compatible WAV concatenation helper."""
    return concatenate_wav_segments([(path, False, False) for path in paths], output_path)


def wav_duration_ms(path: Path) -> int:
    """Return WAV duration in milliseconds for async playback cleanup."""
    try:
        with wave.open(str(path), 'rb') as wf:
            rate = wf.getframerate()
            if rate <= 0:
                return 1000
            return max(1, int(wf.getnframes() * 1000 / rate))
    except Exception:
        return 1000



def is_vowel_jamo(ch: str) -> bool:
    return ch in V_INDEX or ch in SPECIAL_MEDIALS


def is_initial_jamo(ch: str) -> bool:
    return ch in L_INDEX or ch in EXTRA_INITIALS


def atomic_hangul_cluster_end_at(text: str, start: int) -> int | None:
    """Return the end offset for a cursor-atomic jamo syllable cluster."""
    if start < 0 or start >= len(text):
        return None

    ch = text[start]
    if not (is_initial_jamo(ch) or ch == HANGUL_CHOSEONG_FILLER):
        return None
    if start + 1 >= len(text) or not is_vowel_jamo(text[start + 1]):
        return None

    end = start + 2
    while end < len(text) and text[end] in T_INDEX and text[end] != '':
        end += 1
    return end


def atomic_hangul_cluster_bounds_at(text: str, pos: int) -> tuple[int, int] | None:
    """Return the jamo cluster whose interior contains cursor position pos."""
    pos = max(0, min(pos, len(text)))
    for start in range(max(0, pos - 4), min(pos + 1, len(text))):
        end = atomic_hangul_cluster_end_at(text, start)
        if end is not None and start < pos < end:
            return start, end
    return None


def atomic_hangul_cluster_bounds_ending_at(text: str, pos: int) -> tuple[int, int] | None:
    """Return the jamo cluster that ends exactly at cursor position pos."""
    pos = max(0, min(pos, len(text)))
    for start in range(max(0, pos - 4), pos):
        end = atomic_hangul_cluster_end_at(text, start)
        if end == pos:
            return start, end
    return None


def snap_atomic_hangul_cluster_cursor(text: str, pos: int) -> int:
    """Move a cursor position out of the middle of a jamo syllable cluster."""
    bounds = atomic_hangul_cluster_bounds_at(text, pos)
    if bounds is not None:
        return bounds[1]
    return pos


def is_atomic_special_medial_pair_at(text: str, start: int) -> bool:
    """True for cursor-atomic initial/filler + Hokkien special-medial pairs."""
    return atomic_hangul_cluster_end_at(text, start) == start + 2 and text[start + 1] in SPECIAL_MEDIALS


def snap_atomic_special_medial_cursor(text: str, pos: int) -> int:
    """Move a cursor position out of the middle of an atomic special-medial pair."""
    return snap_atomic_hangul_cluster_cursor(text, pos)


def can_be_final_from_compat(ch: str) -> bool:
    return ch in COMPAT_TO_T


# -----------------------------
# Lomari (romanisation) input mode
# -----------------------------
# Lomari mode is case-sensitive for shifted vowel input:
#   lowercase vowels/rimes create ㅇ-initial Tangliengim syllables;
#   Shift+U/I create 으/의;
#   Lomari mode produces complete syllables; bare roman initials stay literal
#   until a vowel/rime completes them.  Syllabic ng still types 응; mm types 음.
#   Shift+G creates ㆆ, and Shift+N creates ㅇ;
#   w/y are reserved for intuitive glide aliases such as we/ya/yor/yo/yu;
#   uppercase consonants fall back to lowercase.
# There is no x null-initial marker and no obsolete uor/wor compound-vowel input.
# Aspirates can be typed by Lomari digraphs kh/ph/th/ch, or by z/v/x/c shortcuts.
LOMARI_INITIAL_TO_L = {
    'kh': 'ᄏ', 'th': 'ᄐ', 'ph': 'ᄑ', 'ch': 'ᄎ', 'js': 'ᄍ',
    'k': 'ᄀ', 'g': 'ᄁ', 'n': 'ᄂ', 't': 'ᄃ', 'r': 'ᄄ', 'l': 'ᄅ',
    'm': 'ᄆ', 'p': 'ᄇ', 'b': 'ᄈ', 's': 'ᄉ', 'j': 'ᄌ', 'h': 'ᄒ',
}
LOMARI_SHORTCUT_INITIALS = {
    'z': 'ᄏ',
    'x': 'ᄐ',
    'c': 'ᄎ',
    'v': 'ᄑ',
}
LOMARI_GUIDE_NON_ROMAN_KEYS = set('zxcv')

LOMARI_L_TO_INITIAL = {v: k for k, v in LOMARI_INITIAL_TO_L.items()}

LOMARI_V_TO_RIME = {
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
    'ᅳ': 'U',
    'ᅴ': 'I',
    'ᅵ': 'i',
    'ힻ': 'er',
    'ᅷ': 'au',
    'ᆤ': 'iau',
}

LOMARI_FINAL_TO_CODA = {
    '': '',
    'ᆨ': 'k',
    'ᆫ': 'n',
    'ᆮ': 't',
    'ᆯ': 'l',
    'ᆷ': 'm',
    'ᆸ': 'p',
    'ᆼ': 'ng',
    'ᇂ': 'h',
    'ᆶ': 'h',
}

LOMARI_VOWEL_LETTERS = set('aeioudf')
LOMARI_INPUT_TONE_SYMBOLS = set('ˆˋ`ˊˉꞈˎˏˍ') | INTERNAL_TONE_MARK_CHARS
LOMARI_BOUNDARY_MARK = '\uE000'
LOMARI_SHIFTED_SINGLE_VOWELS = {
    'I': compose_syllable('ᄋ', 'ᅴ', ''),
    'U': compose_syllable('ᄋ', 'ᅳ', ''),
    'M': compose_syllable('ᄋ', 'ᅳ', 'ᆷ'),
}
LOMARI_SHIFTED_MULTI_VOWELS = {}
LOMARI_SHIFTED_VOWEL_CHARS = set(LOMARI_SHIFTED_SINGLE_VOWELS)
LOMARI_SHIFTED_LITERAL_UPPERCASE = set('QWDFY')
LOMARI_KEY_STYLE_STANDARD = 'standard'
LOMARI_KEY_STYLE_POJ = 'poj'
LOMARI_KEY_STYLE_TAILO = 'tailo'
LOMARI_KEY_STYLE_ALIASES = {
    LOMARI_KEY_STYLE_POJ: [
        ('chh', 'ch'),
        ('ch', 'j'),
        ('js', 'js'),
        ('j', 'r'),
        ('ioo', 'ior'),
        ('ir', 'U'),
        ('oo', 'or'),
        ('onnh', 'orlh'),
        ('onn', 'orl'),
        ('nnh', 'lh'),
        ('om', 'orm'),
        ('op', 'orp'),
        ('ok', 'ork'),
        ('nn', 'l'),
    ],
    LOMARI_KEY_STYLE_TAILO: [
        ('tsh', 'ch'),
        ('ts', 'j'),
        ('js', 'js'),
        ('j', 'r'),
        ('uai', 'oai'),
        ('ua', 'oa'),
        ('ioo', 'ior'),
        ('ir', 'U'),
        ('oo', 'or'),
        ('onnh', 'orlh'),
        ('onn', 'orl'),
        ('nnh', 'lh'),
        ('om', 'orm'),
        ('op', 'orp'),
        ('ok', 'ork'),
        ('nn', 'l'),
    ],
}
LOMARI_AMBIGUOUS_RIME_ALTERNATES = {
    LOMARI_KEY_STYLE_POJ: [('oe', 'ue')],
    LOMARI_KEY_STYLE_TAILO: [('ue', 'oe')],
}


def normalize_lomari_key_style(value: str) -> str:
    value = str(value or LOMARI_KEY_STYLE_STANDARD)
    if value in {LOMARI_KEY_STYLE_POJ, LOMARI_KEY_STYLE_TAILO}:
        return value
    return LOMARI_KEY_STYLE_STANDARD


def apply_lomari_key_style_aliases(raw: str, style: str) -> str:
    """Rewrite POJ/Tai-lo-style key spellings into standard Lomari keys."""
    style = normalize_lomari_key_style(style)
    aliases = LOMARI_KEY_STYLE_ALIASES.get(style, [])
    if not aliases:
        return raw

    out: list[str] = []
    i = 0
    while i < len(raw):
        for source, target in aliases:
            if raw.startswith(source, i):
                out.append(target)
                i += len(source)
                break
        else:
            out.append(raw[i])
            i += 1
    return ''.join(out)


def lomari_key_style_alternate_raws(raw: str, style: str) -> list[str]:
    """Return standard-Lomari raw alternatives for mode-native ambiguous rimes."""
    style = normalize_lomari_key_style(style)
    alternates = LOMARI_AMBIGUOUS_RIME_ALTERNATES.get(style, [])
    source = normalize_lomari_raw_for_matching(raw)
    result: list[str] = []
    for typed_rime, alternate_rime in alternates:
        start = 0
        while True:
            index = source.find(typed_rime, start)
            if index == -1:
                break
            alternate = source[:index] + alternate_rime + source[index + len(typed_rime):]
            alternate = apply_lomari_key_style_aliases(alternate, style)
            if alternate and alternate not in result:
                result.append(alternate)
            start = index + 1

    standard_source = apply_lomari_key_style_aliases(source, style)
    for index, ch in enumerate(standard_source):
        if ch != 'i':
            continue
        previous_ch = standard_source[index - 1].lower() if index > 0 else ''
        next_ch = standard_source[index + 1].lower() if index + 1 < len(standard_source) else ''
        if previous_ch in {'a', 'e', 'o', 'u'}:
            continue
        if next_ch in {'a', 'e', 'o', 'u', 'r'}:
            continue
        alternate = standard_source[:index] + 'I' + standard_source[index + 1:]
        if alternate and alternate not in result and alternate != standard_source:
            result.append(alternate)
    return result


def lomari_double_final_vowel(rime: str) -> str:
    for i in range(len(rime) - 1, -1, -1):
        if rime[i] in LOMARI_VOWEL_LETTERS:
            return rime[:i + 1] + rime[i] + rime[i + 1:]
    return rime


def lomari_glide_if_null_initial(initial: str, medial: str, rime: str) -> str:
    if initial != 'ᄋ':
        return rime
    if medial in {'ᅵ', 'ᅮ', 'ᅴ'}:
        return rime
    if rime.startswith('i'):
        return 'y' + rime[1:]
    if rime.startswith('u'):
        return 'w' + rime[1:]
    return rime


def cluster_to_base_lomari_for_ime(initial: str, medial: str, final: str) -> str:
    ini = LOMARI_L_TO_INITIAL.get(initial, '')

    if medial == 'ᅳ' and final == 'ᆫ':
        return ini + 'n'

    if medial == 'ᅥ':
        if final == 'ᆯ':
            rime = 'orl'
        elif final == 'ᆶ':
            rime = 'orlh'
        elif final == '':
            rime = 'or'
        elif final == 'ᇂ':
            rime = 'orh'
        elif final == 'ᆼ':
            rime = 'ong'
        else:
            rime = 'or' + LOMARI_FINAL_TO_CODA.get(final, '')
        return ini + lomari_glide_if_null_initial(initial, medial, rime)

    if medial == 'ᅧ':
        if final == 'ᆯ':
            rime = 'iorl'
        elif final == 'ᆶ':
            rime = 'iorlh'
        elif final == '':
            rime = 'ior'
        elif final == 'ᇂ':
            rime = 'iorh'
        elif final == 'ᆼ':
            rime = 'iong'
        else:
            rime = 'ior' + LOMARI_FINAL_TO_CODA.get(final, '')
        return ini + lomari_glide_if_null_initial(initial, medial, rime)

    if final == 'ᆯ':
        vow = LOMARI_V_TO_RIME.get(medial, '')
        rime = vow + 'l'
        return ini + lomari_glide_if_null_initial(initial, medial, rime)

    if final == 'ᆶ':
        vow = LOMARI_V_TO_RIME.get(medial, '')
        rime = vow + 'l'
        return ini + lomari_glide_if_null_initial(initial, medial, rime) + 'h'

    vow = LOMARI_V_TO_RIME.get(medial, '')
    fin = LOMARI_FINAL_TO_CODA.get(final, '')
    return ini + lomari_glide_if_null_initial(initial, medial, vow + fin)


def build_ng_initial_syllable_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    medials = [
        'ᅡ', 'ᅢ', 'ᅣ', 'ᅥ', 'ᅦ', 'ᅧ', 'ᅨ', 'ᅩ', 'ᅪ', 'ᅫ', 'ᅬ',
        'ᅭ', 'ᅮ', 'ᅰ', 'ᅱ', 'ᅲ', 'ᅳ', 'ᅴ', 'ᅵ', 'ힻ', 'ᅷ', 'ᆤ',
    ]
    finals = ['', 'ᆨ', 'ᆫ', 'ᆮ', 'ᆯ', 'ᆷ', 'ᆸ', 'ᆼ', 'ᇂ', 'ᆶ']
    for medial in medials:
        for final in finals:
            if final and medial == 'ힻ':
                continue
            rime = cluster_to_base_lomari_for_ime('ᅙ', medial, final)
            if rime:
                mapping.setdefault('ng' + rime, compose_syllable('ᅙ', medial, final))
    mapping['ngwe'] = compose_syllable('ᅙ', 'ힻ', '')
    return mapping


def build_lomari_syllable_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    initials = [
        'ᄋ', 'ᅙ', 'ᄀ', 'ᄁ', 'ᄂ', 'ᄃ', 'ᄄ', 'ᄅ', 'ᄆ', 'ᄇ', 'ᄈ', 'ᄉ',
        'ᄌ', 'ᄍ', 'ᄎ', 'ᄏ', 'ᄐ', 'ᄑ', 'ᄒ',
    ]
    medials = [
        'ᅡ', 'ᅢ', 'ᅣ', 'ᅥ', 'ᅦ', 'ᅧ', 'ᅨ', 'ᅩ', 'ᅪ', 'ᅫ', 'ᅬ',
        'ᅭ', 'ᅮ', 'ᅰ', 'ᅱ', 'ᅲ', 'ᅳ', 'ᅴ', 'ᅵ', 'ힻ', 'ᅷ', 'ᆤ',
    ]
    finals = ['', 'ᆨ', 'ᆫ', 'ᆮ', 'ᆯ', 'ᆷ', 'ᆸ', 'ᆼ', 'ᇂ', 'ᆶ']

    for initial in initials:
        if initial == 'ᅙ':
            continue
        for medial in medials:
            for final in finals:
                if final and medial == 'ힻ':
                    continue
                key = cluster_to_base_lomari_for_ime(initial, medial, final)
                if key:
                    mapping.setdefault(key, compose_syllable(initial, medial, final))

    for roman_initial, initial_jamo in LOMARI_SHORTCUT_INITIALS.items():
        canonical_initial = LOMARI_L_TO_INITIAL.get(initial_jamo, '')
        if not canonical_initial:
            continue
        for medial in medials:
            for final in finals:
                if final and medial == 'ힻ':
                    continue
                canonical_key = cluster_to_base_lomari_for_ime(initial_jamo, medial, final)
                if canonical_key and canonical_key.startswith(canonical_initial):
                    alias_key = roman_initial + canonical_key[len(canonical_initial):]
                    mapping.setdefault(alias_key, compose_syllable(initial_jamo, medial, final))

    for initial in initials:
        ini = LOMARI_L_TO_INITIAL.get(initial, '')
        if not ini:
            continue
        mapping[ini + 'n'] = compose_syllable(initial, 'ᅳ', 'ᆫ')
        mapping[ini + 'ng'] = compose_syllable(initial, 'ᅳ', 'ᆼ')

    null_vowels = {
        'a': 'ᅡ', 'ai': 'ᅢ', 'ia': 'ᅣ', 'ya': 'ᅣ', 'e': 'ᅦ',
        'ior': 'ᅧ', 'yor': 'ᅧ', 'ie': 'ᅨ', 'o': 'ᅩ', 'oa': 'ᅪ', 'oai': 'ᅫ',
        'oe': 'ᅬ', 'io': 'ᅭ', 'yo': 'ᅭ', 'u': 'ᅮ', 'ue': 'ᅰ', 'we': 'ᅰ',
        'ui': 'ᅱ', 'iu': 'ᅲ', 'yu': 'ᅲ', 'i': 'ᅵ',
        'er': 'ힻ', 'au': 'ᅷ', 'iau': 'ᆤ',
    }
    for key, medial in null_vowels.items():
        mapping[key] = compose_syllable('ᄋ', medial, '')

    mapping.update(build_ng_initial_syllable_map())

    for medial in medials:
        for final in finals:
            if not final or final in {'ᆯ', 'ᆶ'} or (final and medial == 'ힻ'):
                continue
            key = cluster_to_base_lomari_for_ime('ᄋ', medial, final)
            if key:
                syllable = compose_syllable('ᄋ', medial, final)
                mapping.setdefault(key, syllable)
                if key.startswith('y'):
                    mapping.setdefault('i' + key[1:], syllable)

    alias_syllables = {
        'ya': compose_syllable('ᄋ', 'ᅣ', ''),
        'yor': compose_syllable('ᄋ', 'ᅧ', ''),
        'yo': compose_syllable('ᄋ', 'ᅭ', ''),
        'yu': compose_syllable('ᄋ', 'ᅲ', ''),
        'we': compose_syllable('ᄋ', 'ᅰ', ''),
    }
    for roman_initial, initial_jamo in LOMARI_INITIAL_TO_L.items():
        if roman_initial == 'ng':
            continue
        compat_initial = L_TO_COMPAT.get(initial_jamo, initial_jamo)
        for alias, syllable in alias_syllables.items():
            mapping.setdefault(roman_initial + alias, compat_initial + syllable)

    for roman_initial, initial_jamo in LOMARI_SHORTCUT_INITIALS.items():
        canonical_initial = LOMARI_L_TO_INITIAL.get(initial_jamo, '')
        for suffix in ('n', 'ng'):
            canonical_key = canonical_initial + suffix
            if canonical_key in mapping:
                mapping.setdefault(roman_initial + suffix, mapping[canonical_key])
        compat_initial = L_TO_COMPAT.get(initial_jamo, initial_jamo)
        for alias, syllable in alias_syllables.items():
            mapping.setdefault(roman_initial + alias, compat_initial + syllable)

    # Bare n/m should stay literal under the Lomari-first reform.  They are
    # produced by systematic null-initial ㅡ+final generation above, so remove
    # them after the full syllable map is built.  Keep ng/mm as explicit
    # syllabic nasal exceptions.
    mapping.pop('n', None)
    mapping.pop('m', None)
    mapping['ng'] = compose_syllable('ᄋ', 'ᅳ', 'ᆼ')
    mapping['mm'] = compose_syllable('ᄋ', 'ᅳ', 'ᆷ')

    glide_initial_rimes = {
        'ia': 'ᅣ',
        'iau': 'ᆤ',
        'ior': 'ᅧ',
        'ie': 'ᅨ',
        'io': 'ᅭ',
        'iu': 'ᅲ',
        'ue': 'ᅰ',
        'ui': 'ᅱ',
    }
    for roman_initial, initial_jamo in {
        **LOMARI_INITIAL_TO_L,
        **LOMARI_SHORTCUT_INITIALS,
    }.items():
        for rime, medial in glide_initial_rimes.items():
            mapping[roman_initial + rime] = compose_syllable(initial_jamo, medial, '')

    return mapping


LOMARI_SYLLABLE_MAP = build_lomari_syllable_map()
LOMARI_CASE_SENSITIVE_MAP = {
    key: value
    for key, value in LOMARI_SYLLABLE_MAP.items()
    if any(ch.isupper() for ch in key)
}
LOMARI_CASE_SENSITIVE_MAP.update({
    'kUn': compose_syllable('ᄀ', 'ᅳ', 'ᆫ'),
    'gUn': compose_syllable('ᄁ', 'ᅳ', 'ᆫ'),
    'khUn': compose_syllable('ᄏ', 'ᅳ', 'ᆫ'),
    'zUn': compose_syllable('ᄏ', 'ᅳ', 'ᆫ'),
    'hUn': compose_syllable('ᄒ', 'ᅳ', 'ᆫ'),
})
LOMARI_CASE_SENSITIVE_KEYS = sorted(LOMARI_CASE_SENSITIVE_MAP, key=len, reverse=True)
LOMARI_SYLLABLE_KEYS = sorted(LOMARI_SYLLABLE_MAP, key=len, reverse=True)
LOMARI_PREFIXES = {
    key[:i]
    for key in [*LOMARI_SYLLABLE_KEYS, *LOMARI_CASE_SENSITIVE_KEYS]
    for i in range(1, len(key))
}


def normalize_lomari_raw_for_matching(raw: str) -> str:
    """Normalise tone symbols while preserving case for Lomari parsing."""
    return normalize_tone_symbols_to_digits(raw)


def format_lomari_hangul_tones(text: str) -> str:
    """Show tone marks after Lomari-converted Hangul while preserving tone 3."""
    out: list[str] = []
    for ch in normalize_tone_symbols_to_digits(text):
        if ch in TONE_DIGITS and can_attach_tone_to_output_chars(out):
            if ch == '3':
                out.append(INTERNAL_TONE_MARKS[ch])
            else:
                out.append(display_reading_tones(ch))
        else:
            out.append(ch)
    return ''.join(out)


def lomari_value_rank(value: str) -> tuple[int, int, int, int, int]:
    if not value:
        return (0, 0, 0, 0, 0)
    if len(value) == 1 and '가' <= value <= '힣':
        decomposed = decompose_precomposed_syllable(value)
        final_count = 1 if decomposed is not None and decomposed[2] else 0
        return (0, final_count, 1, 0, 0)
    if len(value) >= 2 and is_initial_jamo(value[0]) and is_vowel_jamo(value[1]):
        final_count = 1 if any((ch in T_INDEX and ch != '') for ch in value[2:]) else 0
        return (0, final_count, 0, 1, 0)
    if (
        len(value) == 2
        and '\u3130' <= value[0] <= '\u318F'
        and '\uAC00' <= value[1] <= '\uD7A3'
    ):
        return (0, 0, 1, 0, 1)
    if all('㄰' <= ch <= '㆏' for ch in value):
        return (len(value), 0, 0, 0, 0)
    return (1, 0, 0, 0, 0)


def lomari_segment_contains_shifted_vowel(segment: str) -> bool:
    return any(ch in LOMARI_SHIFTED_VOWEL_CHARS for ch in segment)


def maybe_autocorrect_lomari_e_to_ye(value: str, enabled: bool) -> str:
    if not enabled or len(value) != 1 or not ('가' <= value <= '힣'):
        return value
    decomposed = decompose_precomposed_syllable(value)
    if decomposed is None:
        return value
    initial, medial, final = decomposed
    if should_autocorrect_e_to_ye_before_final(initial, medial, final):
        return compose_syllable(initial, 'ᅨ', final)
    return value


def lomari_parsed_syllable_parts(value: str) -> tuple[str, str, str] | None:
    if len(value) == 1 and '가' <= value <= '힣':
        return decompose_precomposed_syllable(value)
    if len(value) >= 2 and is_initial_jamo(value[0]) and is_vowel_jamo(value[1]):
        finals = ''.join(ch for ch in value[2:] if ch in T_INDEX and ch != '')
        return value[0], value[1], finals
    return None


def lomari_raw_starts_with_vowel(raw_tail: str) -> bool:
    if not raw_tail:
        return False
    tail = raw_tail.lower()
    return any(tail.startswith(vowel) for vowel in (
        'iau', 'ior', 'ie', 'io', 'iu', 'ia',
        'au', 'ai', 'oa', 'oe', 'ue', 'ui',
        'a', 'e', 'i', 'o', 'u',
    ))


def lomari_raw_starts_with_yw_initial_rime(raw_tail: str) -> bool:
    if not raw_tail:
        return False
    tail = raw_tail.lower()
    return any(tail.startswith(rime) for rime in (
        'iau', 'ior', 'ia', 'ie', 'io', 'iu', 'ue', 'ui',
    ))


def should_skip_lomari_u_final_before_vowel(_key: str, value: str, raw_tail: str) -> bool:
    if not lomari_raw_starts_with_vowel(raw_tail):
        return False
    parsed = lomari_parsed_syllable_parts(value)
    if parsed is None:
        return False
    initial, medial, final = parsed
    if medial != 'ᅳ' or not final:
        return False
    if final in {'ᆷ', 'ᆼ'}:
        return False
    if final == 'ᆫ' and compose_syllable(initial, medial, final) in {
        compose_syllable('ᄀ', 'ᅳ', 'ᆫ'),
        compose_syllable('ᄁ', 'ᅳ', 'ᆫ'),
        compose_syllable('ᄏ', 'ᅳ', 'ᆫ'),
        compose_syllable('ᄒ', 'ᅳ', 'ᆫ'),
    }:
        return False
    return True


def split_lomari_final_before_vowel(key: str, value: str, raw_tail: str) -> tuple[str, int] | None:
    """Let a typed final consonant become the next onset before a vowel.

    This mirrors the Hangul keyboard's ㄱ/ㅂ/etc. segmentation behavior:
    paipai should settle as 배배, not 뱁애.  Nasal finals stay conservative
    because ng/m carry explicit Hokkien syllable-final meaning in Lomari.
    """
    if len(key) <= 1 or not lomari_raw_starts_with_vowel(raw_tail):
        return None
    parsed = lomari_parsed_syllable_parts(value)
    if parsed is None:
        return None
    initial, medial, final = parsed
    if not final:
        return None

    key_lower = key.lower()
    if final in T_SPLIT:
        keep_final, move_final = T_SPLIT[final]
        coda = LOMARI_FINAL_TO_CODA.get(move_final, '')
        if coda and key_lower.endswith(coda):
            return compose_syllable(initial, medial, keep_final), len(coda)
        return None

    if final in {'ᆷ', 'ᆼ'}:
        coda = LOMARI_FINAL_TO_CODA.get(final, '')
        if (
            coda
            and len(key_lower) > len(coda)
            and key_lower.endswith(coda)
            and lomari_raw_starts_with_yw_initial_rime(raw_tail)
        ):
            return compose_syllable(initial, medial, ''), len(coda)
        return None
    if (
        final == 'ᆫ'
        and medial == 'ᅳ'
        and compose_syllable(initial, medial, final) in {
            compose_syllable('ᄀ', 'ᅳ', 'ᆫ'),
            compose_syllable('ᄁ', 'ᅳ', 'ᆫ'),
            compose_syllable('ᄏ', 'ᅳ', 'ᆫ'),
            compose_syllable('ᄒ', 'ᅳ', 'ᆫ'),
        }
    ):
        return None
    if final not in T_TO_L:
        return None

    coda = LOMARI_FINAL_TO_CODA.get(final, '')
    if coda and key_lower.endswith(coda):
        return compose_syllable(initial, medial, ''), len(coda)
    return None


def convert_lomari_raw_to_hangul(
    raw: str,
    e_to_ye_autocorrect: bool = True,
    lomari_key_style: str = LOMARI_KEY_STYLE_STANDARD,
    split_finals_before_vowels: bool = True,
) -> str:
    """Convert one active Lomari run with case-sensitive shifted vowel rules."""
    src = normalize_lomari_raw_for_matching(raw)
    if LOMARI_BOUNDARY_MARK in src:
        converted = ''.join(
            convert_lomari_raw_to_hangul(
                part,
                e_to_ye_autocorrect=e_to_ye_autocorrect,
                lomari_key_style=lomari_key_style,
                split_finals_before_vowels=split_finals_before_vowels,
            )
            for part in src.split(LOMARI_BOUNDARY_MARK)
            if part
        )
        return converted + ('-' if src.endswith(LOMARI_BOUNDARY_MARK) else '')
    src = apply_lomari_key_style_aliases(src, lomari_key_style)
    memo: dict[int, tuple[tuple[int, int, int, int, int, int, int], str]] = {}

    def best_from(i: int) -> tuple[tuple[int, int, int, int, int, int, int], str]:
        if i >= len(src):
            return (0, 0, 0, 0, 0, 0, 0), ''
        if i in memo:
            return memo[i]

        ch = src[i]
        if ch in TONE_DIGITS:
            next_score, next_text = best_from(i + 1)
            result = next_score, ch + next_text
            memo[i] = result
            return result

        best_score: tuple[int, int, int, int, int, int, int] | None = None
        best_text = ''

        for key, value in sorted(LOMARI_SHIFTED_MULTI_VOWELS.items(), key=lambda item: -len(item[0])):
            if not src.startswith(key, i):
                continue
            tail_score, tail_text = best_from(i + len(key))
            score = (tail_score[0], tail_score[1] - 1, tail_score[2], tail_score[3], tail_score[4], tail_score[5], len(key) + tail_score[6])
            text = value + tail_text
            if best_score is None or score > best_score:
                best_score = score
                best_text = text
        if best_score is not None:
            result = best_score, best_text
            memo[i] = result
            return result

        for key in LOMARI_CASE_SENSITIVE_KEYS:
            if not src.startswith(key, i):
                continue
            value = maybe_autocorrect_lomari_e_to_ye(LOMARI_CASE_SENSITIVE_MAP[key], e_to_ye_autocorrect)
            j = i + len(key)
            split_result = split_lomari_final_before_vowel(key, value, src[j:]) if split_finals_before_vowels else None
            if split_result is not None:
                split_value, backtrack = split_result
                value = split_value
                j -= backtrack
            elif should_skip_lomari_u_final_before_vowel(key, value, src[j:]):
                continue
            tone = ''
            if j < len(src) and src[j] in TONE_DIGITS:
                tone = src[j]
                j += 1
            tail_score, tail_text = best_from(j)
            standalone_count, final_count, full_count, cluster_count, split_count = lomari_value_rank(value)
            score = (
                -standalone_count + tail_score[0],
                -1 + tail_score[1],
                -split_count + tail_score[2],
                tail_score[3],
                full_count + tail_score[4],
                cluster_count + tail_score[5],
                len(key) + tail_score[6],
            )
            text = value + tone + tail_text
            if best_score is None or score > best_score:
                best_score = score
                best_text = text

        if best_score is not None:
            result = best_score, best_text
            memo[i] = result
            return result

        if ch in LOMARI_SHIFTED_SINGLE_VOWELS:
            tail_score, tail_text = best_from(i + 1)
            score = (tail_score[0], tail_score[1] - 1, tail_score[2], tail_score[3], tail_score[4], tail_score[5], 1 + tail_score[6])
            text = LOMARI_SHIFTED_SINGLE_VOWELS[ch] + tail_text
            if best_score is None or score > best_score:
                best_score = score
                best_text = text
            result = best_score, best_text
            memo[i] = result
            return result

        if ch in LOMARI_SHIFTED_LITERAL_UPPERCASE:
            tail_score, tail_text = best_from(i + 1)
            result = (tail_score[0] - 1, tail_score[1], tail_score[2], tail_score[3], tail_score[4], tail_score[5], 1 + tail_score[6]), ch + tail_text
            memo[i] = result
            return result

        lower_src = src[:i] + src[i:].lower()
        for key in LOMARI_SYLLABLE_KEYS:
            if not lower_src.startswith(key, i):
                continue
            raw_segment = src[i:i + len(key)]
            if lomari_segment_contains_shifted_vowel(raw_segment):
                continue
            value = maybe_autocorrect_lomari_e_to_ye(LOMARI_SYLLABLE_MAP[key], e_to_ye_autocorrect)
            j = i + len(key)
            split_result = split_lomari_final_before_vowel(raw_segment, value, src[j:]) if split_finals_before_vowels else None
            if split_result is not None:
                split_value, backtrack = split_result
                value = split_value
                j -= backtrack
            elif should_skip_lomari_u_final_before_vowel(raw_segment, value, src[j:]):
                continue
            tone = ''
            if j < len(src) and src[j] in TONE_DIGITS:
                tone = src[j]
                j += 1
            tail_score, tail_text = best_from(j)
            standalone_count, final_count, full_count, cluster_count, split_count = lomari_value_rank(value)
            score = (
                -standalone_count + tail_score[0],
                -1 + tail_score[1],
                -split_count + tail_score[2],
                tail_score[3],
                full_count + tail_score[4],
                cluster_count + tail_score[5],
                len(key) + tail_score[6],
            )
            text = value + tone + tail_text
            if best_score is None or score > best_score:
                best_score = score
                best_text = text

        if best_score is None:
            tail_score, tail_text = best_from(i + 1)
            best_score = (tail_score[0] - 1, tail_score[1] - 1, tail_score[2], tail_score[3], tail_score[4], tail_score[5], tail_score[6])
            best_text = src[i].lower() + tail_text

        result = best_score, best_text
        memo[i] = result
        return result

    return format_lomari_hangul_tones(best_from(0)[1])


def lomari_loose_candidate_alternate_texts(
    raw: str,
    e_to_ye_autocorrect: bool = True,
    lomari_key_style: str = LOMARI_KEY_STYLE_STANDARD,
) -> list[str]:
    """Return candidate-only alternate readings for ambiguous Lomari parsing.

    Live Lomari typing favours visible syllable breaks before a following
    vowel, e.g. kinarit -> 기나띧.  Candidate lookup is allowed to be looser
    and also check the unsplit parse, e.g. 긴아띧, so dictionary entries like
    今仔日 remain reachable without forcing the user to type -詞.
    """
    normal = convert_lomari_raw_to_hangul(
        raw,
        e_to_ye_autocorrect=e_to_ye_autocorrect,
        lomari_key_style=lomari_key_style,
        split_finals_before_vowels=True,
    )
    unsplit = convert_lomari_raw_to_hangul(
        raw,
        e_to_ye_autocorrect=e_to_ye_autocorrect,
        lomari_key_style=lomari_key_style,
        split_finals_before_vowels=False,
    )
    result: list[str] = []
    for item in (unsplit,):
        if item and item != normal and item not in result:
            result.append(item)
    return result


# -----------------------------
# Read-only Hangul -> Lomari preview
# -----------------------------
# This preview deliberately does NOT use the Lomari keyboard input map.
# It follows the Hangul -> Lomari conversion logic from the tone-marker program.
PREVIEW_CHOSEONG_TO_LOMARI = {
    'ᄋ': '',
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
    'ᅙ': 'ng',
}

PREVIEW_JUNGSEONG_TO_LOMARI = {
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
    'ힻ': 'er',
    'ᅷ': 'au',
    'ᆤ': 'iau',
}

PREVIEW_JONGSEONG_TO_LOMARI = {
    '': '',
    'ᆨ': 'k',
    'ᆫ': 'n',
    'ᆮ': 't',
    'ᆯ': 'l',
    'ᆷ': 'm',
    'ᆸ': 'p',
    'ᆼ': 'ng',
    'ᆺ': '',    # final ㅅ is silent in this system
    'ᆽ': 't',   # final ㅈ -> -t, same as ㄷ
    'ᆾ': 'h',   # final ㅊ -> -h, same as ㅎ
    'ᇂ': 'h',
}

PREVIEW_TONE_PRIORITY_LOMARI = ['a', 'e', 'o', 'u', 'i', 'n', 'm']
PREVIEW_TONE_COMBINING_MARK_LOMARI = {
    '1': '\u0302',
    '2': '\u0300',
    '3': '',
    '4': '\u0301',
    '5': '\u0304',
}
PREVIEW_NASAL_TILDE_BELOW = '\u0330'
PREVIEW_VOWELS = set('aeiou')
PREVIEW_LOMARI_PUNCTUATION = set(",.!?:;‘’'‧~()“”")


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


def preview_lomari_mark_target_index(body: str) -> int | None:
    body_lower = body.lower()
    for letter in PREVIEW_TONE_PRIORITY_LOMARI:
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


def preview_add_combining_mark_to_lomari_target(body: str, mark: str) -> str:
    if not mark:
        return body
    idx = preview_lomari_mark_target_index(body)
    if idx is None:
        return body
    end = idx + 1
    while end < len(body) and unicodedata.combining(body[end]):
        if body[end] == mark:
            return body
        end += 1
    return body[:end] + mark + body[end:]


def preview_nasalize_lomari_rime(rime: str) -> str:
    return preview_add_combining_mark_to_lomari_target(rime, PREVIEW_NASAL_TILDE_BELOW)


def preview_apply_tone(token: str) -> str:
    """Apply Lomari tone digits exactly like the tone-marker program."""
    m = re.match(r'^([^A-Za-z\u0300-\u036f]*)([A-Za-z\u0300-\u036f]+)([12345])([^A-Za-z\u0300-\u036f]*)$', token)
    if not m:
        return token

    lead, body, tone, tail = m.groups()
    return lead + preview_add_combining_mark_to_lomari_target(
        body,
        PREVIEW_TONE_COMBINING_MARK_LOMARI.get(tone, ''),
    ) + tail


def preview_convert_tone_string(s: str) -> str:
    """Convert tone digits in Lomari preview into vowel/nasal diacritics."""
    out_words: list[str] = []
    for word in re.split(r'(\s+)', s):
        if not word:
            continue
        if word.isspace():
            out_words.append(word)
            continue
        parts = re.split(r"([\-'—,\.!?:;’~])", word)
        out_parts = []
        for tok in parts:
            if tok in ("-", "'", "—", ",", ".", "!", "?", ":", ";", "’", "~"):
                out_parts.append(tok)
            else:
                out_parts.append(preview_apply_tone(tok))
        out_words.append(''.join(out_parts))
    return ''.join(out_words)

def preview_double_final_vowel(rime: str) -> str:
    """Mark nasalisation on the same target letter used for tone marks."""
    return preview_nasalize_lomari_rime(rime)


def preview_glide_if_null_initial(initial: str, medial: str, rime: str) -> str:
    """Use y/w for null-initial compound vowels, matching the tone marker."""
    if initial != 'ᄋ':
        return rime
    if medial in ('ᅵ', 'ᅮ', 'ᅴ'):
        return rime
    if rime.startswith('i'):
        return 'y' + rime[1:]
    if rime.startswith('u'):
        return 'w' + rime[1:]
    return rime


def preview_special_rime_oe_yeo(medial: str, final: str) -> str | None:
    """Special ㅓ/ㅕ + final behaviour from the tone-marker program."""
    if medial == 'ᅥ':
        if final == 'ᆯ':
            return preview_nasalize_lomari_rime('or')
        if final == 'ᆶ':
            return preview_nasalize_lomari_rime('or') + 'h'
        if final == '':
            return 'or'
        if final == 'ᇂ':
            return 'orh'
        if final == 'ᆼ':
            return 'o' + PREVIEW_JONGSEONG_TO_LOMARI.get(final, '')
        return 'or' + PREVIEW_JONGSEONG_TO_LOMARI.get(final, '')

    if medial == 'ᅧ':
        if final == 'ᆯ':
            return preview_nasalize_lomari_rime('ior')
        if final == 'ᆶ':
            return preview_nasalize_lomari_rime('ior') + 'h'
        if final == '':
            return 'ior'
        if final == 'ᇂ':
            return 'iorh'
        if final == 'ᆼ':
            return 'io' + PREVIEW_JONGSEONG_TO_LOMARI.get(final, '')
        return 'ior' + PREVIEW_JONGSEONG_TO_LOMARI.get(final, '')

    return None


def preview_cluster_to_base_lomari(initial: str, medial: str, final: str = '') -> str:
    """Romanise one Hangul initial/medial/final cluster for preview output."""
    ini = PREVIEW_CHOSEONG_TO_LOMARI.get(initial, '')

    if medial == 'ᅳ' and final == 'ᆫ':
        return ini + 'n'

    rime = preview_special_rime_oe_yeo(medial, final)
    if rime is not None:
        return ini + preview_glide_if_null_initial(initial, medial, rime)

    # Romanisation preview must keep written ㅚ as Lomari oe.
    # Audio lookup may share ㅚ recordings with ㅞ, but that pronunciation
    # equivalence must not leak into the displayed/copyable Lomari line.
    if medial == 'ᅬ':
        vow = 'oe'
        l_cluster_finals_for_oe = {
            'ᆶ': 'h',  # ㅀ
            'ᆰ': 'k',
            'ᇍ': 'n',
            'ᇎ': 't',
            'ᆱ': 'm',
            'ᆲ': 'p',
            'ᆴ': 't',
        }
        if final == 'ᆯ':
            rime = preview_double_final_vowel(vow)
        elif final in l_cluster_finals_for_oe:
            rime = preview_double_final_vowel(vow) + l_cluster_finals_for_oe[final]
        else:
            rime = vow + PREVIEW_JONGSEONG_TO_LOMARI.get(final, '')
        rime = preview_glide_if_null_initial(initial, medial, rime)
        return ini + rime

    if final == 'ᆯ':
        vow = PREVIEW_JUNGSEONG_TO_LOMARI.get(medial, '')
        rime = preview_double_final_vowel(vow)
        rime = preview_glide_if_null_initial(initial, medial, rime)
        return ini + rime

    # L-final clusters: same ㄹ double-vowel behaviour, then append cluster coda.
    l_cluster_finals = {
        'ᆶ': 'h',  # ㅀ
        'ᆰ': 'k',
        'ᇍ': 'n',
        'ᇎ': 't',
        'ᆱ': 'm',
        'ᆲ': 'p',
        'ᆴ': 't',
    }
    if final in l_cluster_finals:
        vow = PREVIEW_JUNGSEONG_TO_LOMARI.get(medial, '')
        rime = preview_double_final_vowel(vow)
        rime = preview_glide_if_null_initial(initial, medial, rime)
        return ini + rime + l_cluster_finals[final]

    vow = PREVIEW_JUNGSEONG_TO_LOMARI.get(medial, '')
    fin = PREVIEW_JONGSEONG_TO_LOMARI.get(final, '')
    rime = preview_glide_if_null_initial(initial, medial, vow + fin)
    return ini + rime


def hangul_unit_to_lomari(unit: str) -> str:
    """Romanise one Hangul/Hokkien-Hangul unit for the Lomari preview."""
    text = str(unit)
    if not text:
        return ''

    if len(text) >= 2 and text[0] == HANGUL_CHOSEONG_FILLER and text[1] in SPECIAL_MEDIALS:
        return PREVIEW_JUNGSEONG_TO_LOMARI.get(text[1], text[1])

    if len(text) == 1:
        decomposed = decompose_precomposed_syllable(text)
        if decomposed is not None:
            initial, medial, final = decomposed
            return preview_cluster_to_base_lomari(initial, medial, final)

    if len(text) >= 2 and is_initial_jamo(text[0]) and is_vowel_jamo(text[1]):
        initial = text[0]
        medial = text[1]
        final_chars = [ch for ch in text[2:] if ch in T_INDEX and ch != '']
        if len(final_chars) == 1:
            return preview_cluster_to_base_lomari(initial, medial, final_chars[0])
        if not final_chars:
            return preview_cluster_to_base_lomari(initial, medial, '')

    if len(text) == 1:
        ch = text[0]
        if ch in COMPAT_TO_L:
            return PREVIEW_CHOSEONG_TO_LOMARI.get(COMPAT_TO_L[ch], ch)
        if ch in COMPAT_TO_V:
            return PREVIEW_JUNGSEONG_TO_LOMARI.get(COMPAT_TO_V[ch], ch)
        if ch in V_TO_COMPAT.values():
            for medial, compat in V_TO_COMPAT.items():
                if compat == ch:
                    return PREVIEW_JUNGSEONG_TO_LOMARI.get(medial, ch)
        if ch == 'ㅀ':
            return 'ⁿh'
        if ch in T_TO_COMPAT:
            return T_TO_COMPAT.get(ch, ch)

    # Multi-codepoint Hokkien syllables such as 하이 are kept readable by
    # falling back to their smaller Hangul units.
    parts = split_untoned_hangul_units(text)
    if parts and parts != [text]:
        return ''.join(hangul_unit_to_lomari(part) for part in parts)
    return text


def expand_visible_text_for_lomari(text: str) -> str:
    """Replace visible Hanri/Hangul dictionary forms with TSV readings.

    This lets the romanisation line remain useful after the user has converted
    text to Hanri, while raw Hangul without a TSV match still romanises as typed.
    """
    source = format_text_tones_for_output(str(text), True, keep_literal_digit_markers=True)
    out: list[str] = []
    i = 0
    tone_chars = TONE_SYMBOLS.union(TONE_DIGITS).union(INTERNAL_TONE_MARK_CHARS)
    while i < len(source):
        tail = source[i:]

        # Keep explicit visible tone marks attached to the Hangul unit before
        # dictionary matching, so manually typed tones are not swallowed by a
        # shorter untoned TSV key.
        unit_end = audio_unit_end_at(source, i)
        if (
            unit_end is not None
            and unit_end < len(source)
            and source[unit_end] in tone_chars
            and can_attach_tone_to_text(source, unit_end - 1)
        ):
            tone_end = unit_end
            while tone_end < len(source) and source[tone_end] in tone_chars:
                tone_end += 1
            out.append(source[i:tone_end])
            i = tone_end
            continue

        matched = False
        for key, reading in AUDIO_HANRI_INDEX:
            if key and contains_apostrophe_boundary(key):
                continue
            if key and tail.startswith(key):
                out.append(reading)
                i += len(key)
                matched = True
                break
        if matched:
            continue

        for key, reading in AUDIO_READING_INDEX:
            if key and tail.startswith(key):
                out.append(reading)
                i += len(key)
                matched = True
                break
        if matched:
            continue

        out.append(source[i])
        i += 1
    return ''.join(out)


def visible_text_to_lomari_sandhi_source(text: str) -> str:
    """Return the hidden tone/sandhi reading used by the Lomari preview.

    This mirrors the recorded-audio reading logic, but preserves spaces and
    punctuation so the copyable romanisation line reflects what will actually
    be pronounced rather than simply romanising the raw visible text.
    """
    source = format_text_tones_for_output(str(text), True, keep_literal_digit_markers=True)
    out: list[str] = []
    # Each run part is (reading_text, protect_internal_sandhi, from_tsv, force_tone3).
    # This mirrors visible_text_to_audio_segments().  Numeric TSV/pattern readings
    # are from_tsv=True but protect_internal_sandhi=False, so compounds like
    # 12月 preview with sandhi across 잡+띠+月.
    run_parts: list[tuple[str, bool, bool, bool, bool]] = []
    post_apostrophe_force_tone3 = False
    tone_chars = TONE_SYMBOLS.union(TONE_DIGITS).union(INTERNAL_TONE_MARK_CHARS)

    def sandhi_final_raw_run_before_hyphen() -> None:
        nonlocal run_parts
        if not run_parts:
            return
        part_text, protect_internal_sandhi, from_tsv, force_tone3, protect_final_sandhi = run_parts[-1]
        if protect_internal_sandhi or from_tsv or force_tone3:
            return
        part_digits = normalize_tone_symbols_to_digits(part_text)
        if reading_has_tones(part_digits):
            return
        sandhi_reading = citation_to_sandhi_reading(part_digits)
        if sandhi_reading and sandhi_reading != part_text:
            run_parts[-1] = (
                sandhi_reading,
                protect_internal_sandhi,
                from_tsv,
                force_tone3,
                protect_final_sandhi,
            )

    def flush_run(force_citation: bool = False, continuation_after: bool = False) -> None:
        nonlocal run_parts
        if not run_parts:
            return

        flattened: list[tuple[str, str, bool]] = []
        for part_text, protect_internal_sandhi, from_tsv, force_tone3, protect_final_sandhi in run_parts:
            part_units = split_audio_reading_units(part_text)
            explicit_raw_tone = (
                (not protect_internal_sandhi)
                and (not from_tsv)
                and reading_has_tones(normalize_tone_symbols_to_digits(part_text))
            )
            raw_unmarked_hangul = bool(
                (not protect_internal_sandhi)
                and (not from_tsv)
                and (not explicit_raw_tone)
                and part_units
            )

            for part_idx, (unit, tone) in enumerate(part_units):
                if force_tone3:
                    tone = '3'
                protect_this_unit = bool(
                    force_tone3
                    or 
                    explicit_raw_tone
                    or raw_unmarked_hangul
                    or (
                        protect_final_sandhi
                        and part_idx == len(part_units) - 1
                    )
                    or (
                        protect_internal_sandhi
                        and part_idx < len(part_units) - 1
                    )
                )
                flattened.append((unit, tone, protect_this_unit))

        for idx, (unit, tone, protect_sandhi) in enumerate(flattened):
            if (
                (idx < len(flattened) - 1 or continuation_after)
                and not protect_sandhi
                and not force_citation
            ):
                unit, tone = lomari_sandhi_unit(unit, tone)
            out.append(unit)
            if tone:
                out.append(tone)
        run_parts = []

    i = 0
    while i < len(source):
        tail = source[i:]
        ch = source[i]
        matched = False

        if ch == '[':
            end = source.find(']', i + 1)
            if end != -1:
                parsed = split_hanri_hangul_bracket_inner(source[i + 1:end])
                if parsed:
                    _hanri, reading = parsed
                    if (
                        end + 1 < len(source)
                        and source[end + 1] == '-'
                        and not reading_has_tones(normalize_tone_symbols_to_digits(reading))
                    ):
                        reading = citation_to_sandhi_reading(reading) or reading
                    run_parts.append((reading, True, True, post_apostrophe_force_tone3, True))
                    i = end + 1
                    continue

        # Apostrophe is a connector, not a phrase reset.  It forces the
        # immediately preceding unit to stay citation-final, but earlier units
        # in the same run may still sandhi.  Preserve the apostrophe visibly in
        # the Lomari line.
        if ch in {"'", '’', '‘'}:
            flush_run()
            out.append(ch)
            normalized_tail = '’' + tail[1:]
            for key, reading in audio_reading_candidates_for_char(ch):
                if key and key[0] in {"'", '’', '‘'} and normalized_tail.startswith('’' + key[1:]):
                    override = is_explicit_apostrophe_tone_override(key, reading)
                    run_parts.append((reading, True, True, not override, False))
                    i += len(key)
                    matched = True
                    break
            post_apostrophe_force_tone3 = True
            if matched:
                continue
            i += 1
            continue

        # Explicit visible tone marks belong to the unit before them and should
        # not be swallowed by a shorter untoned TSV key.
        unit_end = audio_unit_end_at(source, i)
        if (
            unit_end is not None
            and unit_end < len(source)
            and source[unit_end] in tone_chars
            and can_attach_tone_to_text(source, unit_end - 1)
        ):
            tone_end = unit_end
            while tone_end < len(source) and source[tone_end] in tone_chars:
                tone_end += 1
            run_parts.append((source[i:tone_end], False, False, post_apostrophe_force_tone3, False))
            i = tone_end
            continue

        if ch in tone_chars and i > 0 and not can_attach_tone_to_text(source, i - 1):
            flush_run()
            out.append(LITERAL_DIGIT_MARK + normalize_tone_symbols_to_digits(ch))
            i += 1
            continue

        mixed_hanri_match = mixed_audio_hanri_match(source, i)
        if mixed_hanri_match:
            key, reading = mixed_hanri_match
            run_parts.append((mark_untoned_audio_units(reading), True, True, post_apostrophe_force_tone3, False))
            i += len(key)
            continue

        hanri_match = priority_audio_hanri_match(source, i)
        if hanri_match:
            key, reading = hanri_match
            run_parts.append((reading, True, True, post_apostrophe_force_tone3, False))
            i += len(key)
            continue

        for key, reading in audio_reading_candidates_for_char(ch):
            if key and source.startswith(key, i):
                match_end = i + len(key)
                explicit_final_tone = reading_has_tones(normalize_tone_symbols_to_digits(key))
                reading_text = reading
                if match_end < len(source) and source[match_end] in tone_chars:
                    tone_end = match_end
                    while tone_end < len(source) and source[tone_end] in tone_chars:
                        tone_end += 1
                    reading_text = str(reading) + source[match_end:tone_end]
                    explicit_final_tone = True
                    i = tone_end
                else:
                    i += len(key)
                run_parts.append((reading_text, True, True, post_apostrophe_force_tone3, explicit_final_tone))
                matched = True
                break
        if matched:
            continue

        literal_number = literal_number_reading_at(source, i)
        if literal_number is not None:
            reading, digit_end = literal_number
            # Numeric readings are dictionary-owned but should still sandhi
            # internally and before the following classifier/date word.
            run_parts.append((reading, False, True, post_apostrophe_force_tone3, False))
            i = digit_end
            continue

        if ch in tone_chars:
            if can_attach_tone_to_text(source, i - 1) and run_parts and not run_parts[-1][1]:
                previous_text, previous_protect, previous_from_tsv, previous_force_tone3, previous_protect_final = run_parts[-1]
                run_parts[-1] = (
                    previous_text + ch,
                    previous_protect,
                    previous_from_tsv,
                    previous_force_tone3 or post_apostrophe_force_tone3,
                    previous_protect_final,
                )
            else:
                flush_run()
                out.append(LITERAL_DIGIT_MARK + normalize_tone_symbols_to_digits(ch))
        elif is_hangulish_for_tone(ch):
            # Raw Hokkien jamo clusters must stay as one romanisation unit.
            # Example: ᄐᅷ should preview as thau, not ᄐ3-ᅷ3.
            unit_end = audio_unit_end_at(source, i)
            if unit_end is not None and unit_end > i:
                unit_text = source[i:unit_end]
                pronunciation = jamo_pronunciation_reading(unit_text)
                if pronunciation:
                    run_parts.append((pronunciation, True, True, post_apostrophe_force_tone3, True))
                elif len(unit_text) == 1 and decompose_precomposed_syllable(unit_text) is None:
                    flush_run()
                    out.append(unit_text)
                else:
                    run_parts.append((unit_text, False, False, post_apostrophe_force_tone3, False))
                i = unit_end - 1
            else:
                pronunciation = jamo_pronunciation_reading(ch)
                if pronunciation:
                    run_parts.append((pronunciation, True, True, post_apostrophe_force_tone3, True))
                else:
                    flush_run()
                    out.append(ch)
        elif is_hanri_char(ch):
            flush_run()
            out.append(ch)
        elif is_latin_word_start(ch):
            latin_end = latin_word_end(source, i)
            flush_run(continuation_after=True)
            out.append(source[i:latin_end])
            i = latin_end - 1
        elif ch == '-':
            sandhi_final_raw_run_before_hyphen()
            flush_run(continuation_after=True)
            out.append(ch)
        elif is_audio_phrase_boundary(ch):
            flush_run()
            out.append(ch)
            if ch.isspace():
                post_apostrophe_force_tone3 = False
        elif is_ignored_audio_punctuation(ch):
            flush_run(force_citation=(ch in {"'", '’', '‘'}))
            out.append(ch)
            if ch.isspace():
                post_apostrophe_force_tone3 = False
        else:
            flush_run()
            out.append(ch)
        i += 1

    flush_run()
    return ''.join(out)


def visible_text_to_lomari(text: str) -> str:
    """Return a copyable Lomari preview for the current IME text."""
    # Use the same hidden TSV/sandhi reading that drives recorded-audio playback,
    # rather than romanising only the raw visible text in the typing box.
    reading_text = normalize_tone_symbols_to_digits(visible_text_to_lomari_sandhi_source(text))
    out: list[str] = []
    i = 0
    prev_was_syllable = False
    tone_chars = TONE_SYMBOLS.union(TONE_DIGITS).union(INTERNAL_TONE_MARK_CHARS)

    def append_sep_if_needed() -> None:
        nonlocal prev_was_syllable
        if prev_was_syllable:
            out.append('-')

    while i < len(reading_text):
        unit_end = audio_unit_end_at(reading_text, i)
        if unit_end is not None:
            append_sep_if_needed()
            unit = reading_text[i:unit_end]
            i = unit_end
            tone = ''
            while (
                i < len(reading_text)
                and reading_text[i] in tone_chars
                and can_attach_tone_to_text(reading_text, i - 1)
            ):
                marker = normalize_tone_symbols_to_digits(reading_text[i])
                if marker in TONE_DIGITS:
                    tone = marker
                i += 1
            lomari = hangul_unit_to_lomari(unit)
            if lomari:
                out.append(lomari)
                if tone:
                    out.append(tone)
                prev_was_syllable = True
            else:
                prev_was_syllable = False
            continue

        ch = reading_text[i]
        if ch in tone_chars:
            out.append(LITERAL_DIGIT_MARK + normalize_tone_symbols_to_digits(ch))
            i += 1
            prev_was_syllable = False
            continue

        if ch.isspace():
            out.append(ch)
            i += 1
            prev_was_syllable = False
            continue

        if ch in PREVIEW_LOMARI_PUNCTUATION:
            out.append(ch)
            i += 1
            prev_was_syllable = False
            continue

        if is_latin_word_start(ch):
            latin_end = latin_word_end(reading_text, i)
            append_sep_if_needed()
            out.append(reading_text[i:latin_end])
            i = latin_end
            prev_was_syllable = True
            continue

        if ch == '-':
            out.append('-')
            i += 1
            prev_was_syllable = False
            continue

        if ch in '–—':
            out.append('—')
            i += 1
            prev_was_syllable = False
            continue

        out.append(ch)
        i += 1
        prev_was_syllable = False

    return preview_convert_tone_string(''.join(out)).replace(LITERAL_DIGIT_MARK, '')


@dataclass
class Composer:
    output: str = ''
    cursor_pos: int = 0
    initial: str = ''
    medial: str = ''
    final: str = ''
    e_to_ye_autocorrected: bool = False
    e_to_ye_autocorrect_enabled: object = None

    def __post_init__(self) -> None:
        self.clamp_cursor()

    def should_use_e_to_ye_autocorrect(self) -> bool:
        if callable(self.e_to_ye_autocorrect_enabled):
            try:
                return bool(self.e_to_ye_autocorrect_enabled())
            except Exception:
                return True
        return True

    def clamp_cursor(self) -> None:
        self.cursor_pos = max(0, min(self.cursor_pos, len(self.output)))
        self.cursor_pos = max(0, min(snap_atomic_special_medial_cursor(self.output, self.cursor_pos), len(self.output)))

    def has_buffer(self) -> bool:
        return bool(self.initial or self.medial or self.final)

    def buffer_text(self) -> str:
        if self.initial and self.medial:
            return compose_syllable(self.initial, self.medial, self.final)

        # When a Hangul letter is typed alone, display/commit compatibility jamo
        # such as ㄱ / ㅏ, not leading/medial jamo such as ᄀ / ᅡ.
        if self.initial:
            return L_TO_COMPAT.get(self.initial, self.initial)
        if self.medial:
            return V_TO_COMPAT.get(self.medial, self.medial)
        if self.final:
            return T_TO_COMPAT.get(self.final, self.final)
        return ''

    def text(self) -> str:
        self.clamp_cursor()
        return self.output[:self.cursor_pos] + self.buffer_text() + self.output[self.cursor_pos:]

    def display_cursor_pos(self) -> int:
        self.clamp_cursor()
        return self.cursor_pos + len(self.buffer_text())

    def commit(self) -> None:
        if self.has_buffer():
            self.clamp_cursor()
            text = self.buffer_text()
            self.output = self.output[:self.cursor_pos] + text + self.output[self.cursor_pos:]
            self.cursor_pos += len(text)
            self.initial = self.medial = self.final = ''
            self.e_to_ye_autocorrected = False

    def insert_literal(self, s: str) -> None:
        self.commit()
        self.clamp_cursor()
        self.output = self.output[:self.cursor_pos] + s + self.output[self.cursor_pos:]
        self.cursor_pos += len(s)

    def move_left(self) -> None:
        self.commit()
        self.clamp_cursor()
        if self.cursor_pos > 0:
            self.cursor_pos -= 1
            bounds = atomic_hangul_cluster_bounds_at(self.output, self.cursor_pos)
            if bounds is not None:
                self.cursor_pos = bounds[0]

    def move_right(self) -> None:
        self.commit()
        self.clamp_cursor()
        if self.cursor_pos < len(self.output):
            end = atomic_hangul_cluster_end_at(self.output, self.cursor_pos)
            if end is not None:
                self.cursor_pos = end
            elif (bounds := atomic_hangul_cluster_bounds_at(self.output, self.cursor_pos)) is not None:
                self.cursor_pos = bounds[1]
            else:
                self.cursor_pos += 1

    def move_to(self, pos: int) -> None:
        """Move the internal cursor to an absolute character offset."""
        self.commit()
        self.cursor_pos = snap_atomic_special_medial_cursor(self.output, pos)
        self.clamp_cursor()

    def add_initial(self, initial: str, source_compat: str | None = None) -> None:
        if not self.has_buffer():
            self.initial = initial
            self.e_to_ye_autocorrected = False
            return

        # Old-Hangul convenience: ㅡ + ㅇ becomes standalone ㆆ.
        # Internally this is stored as choseong ᅙ so Shift+G / ㆆ can also
        # combine with following vowels, e.g. G+k or m+d+k -> ᅙᅡ.
        if (not self.initial) and self.medial == 'ᅳ' and not self.final and source_compat == 'ㅇ':
            self.medial = ''
            self.initial = 'ᅙ'
            self.e_to_ye_autocorrected = False
            return

        if self.initial and not self.medial:
            # Standalone ㄹ + ㅅ/ㅎ should become the compatibility cluster
            # ㅀ, matching the same Hokkien-allowed batchim cluster used
            # inside full syllables.
            previous_compat = L_TO_COMPAT.get(self.initial, '')
            if (
                previous_compat in COMPAT_TO_T
                and source_compat
                and source_compat in COMPAT_TO_T
            ):
                candidate = T_COMBINE.get((COMPAT_TO_T[previous_compat], COMPAT_TO_T[source_compat]))
                if candidate:
                    self.initial = ''
                    self.final = candidate
                    self.e_to_ye_autocorrected = False
                    return

            # Two initials in a row: commit the first and start a new one.
            self.commit()
            self.initial = initial
            self.e_to_ye_autocorrected = False
            return

        if self.initial and self.medial and not self.final and source_compat and can_be_final_from_compat(source_compat):
            self.final = COMPAT_TO_T[source_compat]
            if (
                self.should_use_e_to_ye_autocorrect()
                and should_autocorrect_e_to_ye_before_final(self.initial, self.medial, self.final)
            ):
                self.medial = 'ᅨ'
                self.e_to_ye_autocorrected = True
            else:
                self.e_to_ye_autocorrected = False
            return

        if self.initial and self.medial and self.final and source_compat and can_be_final_from_compat(source_compat):
            candidate = T_COMBINE.get((self.final, COMPAT_TO_T[source_compat]))
            if candidate:
                self.final = candidate
                self.e_to_ye_autocorrected = False
                return

        self.commit()
        self.initial = initial
        self.e_to_ye_autocorrected = False

    def add_vowel(self, medial: str) -> None:
        if not self.has_buffer():
            # A vowel typed alone should remain a standalone compatibility jamo
            # in display/commit. It only forms a syllable after an initial.
            self.medial = medial
            self.e_to_ye_autocorrected = False
            return

        if (not self.initial) and self.medial and not self.final:
            # A standalone vowel followed by another vowel stays standalone.
            # Do not create an automatic ㅇ-initial syllable.
            # Examples:
            #   kk -> ㅏㅏ, not ㅏ아
            #   jj -> ㅓㅓ, not ㅓ어
            # Valid standalone compound vowels can still combine, e.g. ㅗ+ㅏ -> ㅘ.
            candidate = V_COMBINE.get((self.medial, medial))
            if candidate:
                self.medial = candidate
                self.e_to_ye_autocorrected = False
                return
            self.commit()
            self.medial = medial
            self.e_to_ye_autocorrected = False
            return

        if self.initial and not self.medial:
            self.medial = medial
            self.e_to_ye_autocorrected = False
            return

        if self.initial and self.medial and not self.final:
            candidate = V_COMBINE.get((self.medial, medial))
            if candidate:
                self.medial = candidate
                self.e_to_ye_autocorrected = False
                return

            # Hokkien IME behaviour: if a complete syllable is followed by
            # another vowel that does not form a valid compound medial, keep the
            # new vowel as a standalone compatibility jamo.  Do not automatically
            # create an ㅇ-initial syllable.
            # Examples:
            #   rjn  -> 거ㅜ, not 거우
            #   dK+n -> ᄋᅷㅜ, not ᄋᅷ우
            self.commit()
            if medial in SPECIAL_MEDIALS:
                self.insert_literal(HANGUL_CHOSEONG_FILLER + medial)
                self.e_to_ye_autocorrected = False
                return
            self.medial = medial
            self.e_to_ye_autocorrected = False
            return

        if self.initial and self.medial and self.final:
            # If ㅔ was only autocorrected to ㅖ because ㄱ/ㅇ looked final,
            # undo that correction when the consonant becomes the next onset.
            if self.e_to_ye_autocorrected and self.medial == 'ᅨ' and self.final in {'ᆨ', 'ᆼ'}:
                self.medial = 'ᅦ'
                self.e_to_ye_autocorrected = False
            # Korean IME behavior: final consonant moves to the next syllable before a vowel.
            if self.final in T_SPLIT:
                keep_final, move_final = T_SPLIT[self.final]
                self.final = keep_final
                self.commit()
                self.initial = T_TO_L.get(move_final, '')
                self.medial = medial
                self.final = ''
                self.e_to_ye_autocorrected = False
            else:
                move_initial = T_TO_L.get(self.final, '')
                if not move_initial:
                    self.commit()
                    self.initial = 'ᄋ'
                    self.medial = medial
                    self.e_to_ye_autocorrected = False
                else:
                    self.final = ''
                    self.commit()
                    self.initial = move_initial
                    self.medial = medial
                    self.final = ''
                    self.e_to_ye_autocorrected = False
            return

        self.commit()
        self.initial = 'ᄋ'
        self.medial = medial
        self.e_to_ye_autocorrected = False

    def backspace(self) -> None:
        if self.final:
            if self.e_to_ye_autocorrected:
                self.final = ''
                self.medial = 'ᅦ'
                self.e_to_ye_autocorrected = False
                return None
            if self.final in T_SPLIT:
                self.final = T_SPLIT[self.final][0]
            else:
                self.final = ''
            self.e_to_ye_autocorrected = False
            return
        if self.medial:
            # If medial is compound, undo only the second part when possible.
            reverse_v = {v: k for k, v in V_COMBINE.items()}
            if self.medial in reverse_v:
                self.medial = reverse_v[self.medial][0]
            elif self.medial in {'ᅷ', 'ᆤ'}:
                self.medial = ''
            elif self.medial in SPECIAL_MEDIAL_BACKSPACE_BASE:
                old_special = self.medial
                self.medial = SPECIAL_MEDIAL_BACKSPACE_BASE[self.medial]
                return {
                    'kind': 'special_medial_peel',
                    'initial': self.initial,
                    'special_medial': old_special,
                    'base_medial': self.medial,
                }
            else:
                self.medial = ''
            self.e_to_ye_autocorrected = False
            return None
        if self.initial:
            self.initial = ''
            self.e_to_ye_autocorrected = False
            return
        self.clamp_cursor()
        if self.output and self.cursor_pos > 0:
            # Once a decomposed jamo syllable has been committed and the
            # cursor is outside it, delete it like one precomposed character.
            cluster_bounds = atomic_hangul_cluster_bounds_ending_at(self.output, self.cursor_pos)
            if cluster_bounds is not None:
                start, end = cluster_bounds
                self.output = self.output[:start] + self.output[end:]
                self.cursor_pos = start
                return None

            # Standalone special vowels use a choseong filler for display.
            # Treat the filler+vowel pair as one visible unit on Backspace.
            if (
                self.cursor_pos >= 2
                and self.output[self.cursor_pos - 2] == '\u115F'
                and self.output[self.cursor_pos - 1] in {'ᅷ', 'ᆤ'}
            ):
                self.output = self.output[:self.cursor_pos - 2] + self.output[self.cursor_pos:]
                self.cursor_pos -= 2
                return None

            if (
                self.cursor_pos >= 2
                and self.output[self.cursor_pos - 2] == HANGUL_CHOSEONG_FILLER
                and self.output[self.cursor_pos - 1] == 'ힻ'
            ):
                self.output = self.output[:self.cursor_pos - 2] + self.output[self.cursor_pos:]
                self.cursor_pos -= 2
                self.medial = 'ᅳ'
                return None

            # Treat ᅷ/ᆤ like full Hangul vowels: Backspace removes the vowel
            # part and leaves the initial visible, e.g. ᄋᅷ -> ㅇ.
            if (
                self.cursor_pos >= 2
                and self.output[self.cursor_pos - 1] in {'ᅷ', 'ᆤ'}
                and is_initial_jamo(self.output[self.cursor_pos - 2])
            ):
                initial = self.output[self.cursor_pos - 2]
                self.output = self.output[:self.cursor_pos - 2] + self.output[self.cursor_pos:]
                self.cursor_pos -= 2
                self.initial = initial
                self.medial = ''
                self.final = ''
                return None

            # Other committed Hokkien non-precomposed vowels can still peel back
            # to their closest ordinary syllable first.
            if (
                self.cursor_pos >= 2
                and self.output[self.cursor_pos - 1] in SPECIAL_MEDIAL_BACKSPACE_BASE
                and is_initial_jamo(self.output[self.cursor_pos - 2])
            ):
                initial = self.output[self.cursor_pos - 2]
                special_medial = self.output[self.cursor_pos - 1]
                medial = SPECIAL_MEDIAL_BACKSPACE_BASE[special_medial]
                # Keep the peeled ordinary syllable as the active composing
                # buffer rather than committing it into output.
                # Example: ᄋힻ Backspace -> active 어.
                self.output = self.output[:self.cursor_pos - 2] + self.output[self.cursor_pos:]
                self.cursor_pos -= 2
                self.initial = initial
                self.medial = medial
                self.final = ''
                return {
                    'kind': 'special_medial_peel',
                    'initial': initial,
                    'special_medial': special_medial,
                    'base_medial': medial,
                }

            # Alt+digit stores an invisible marker before the visible numeral.
            # Backspace should remove the whole visible numeral token at once,
            # not leave the zero-width marker behind.
            if (
                self.output[self.cursor_pos - 1] in ARABIC_NUMERAL_DIGITS
                and self.cursor_pos >= 2
                and self.output[self.cursor_pos - 2] == LITERAL_DIGIT_MARK
            ):
                self.output = self.output[:self.cursor_pos - 2] + self.output[self.cursor_pos:]
                self.cursor_pos -= 2
                return
            self.output = self.output[:self.cursor_pos - 1] + self.output[self.cursor_pos:]
            self.cursor_pos -= 1




BUILTIN_ICON_PNG_DATA = {
    'copy': 'iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAAjElEQVR4nO2UsQ2AIBREn4YliLoCGziBe8BKsg8TsIImjKGFFoo0fim98oqX+5f8a7SLE+CBjvcKyZvxarTALIQBbLmhgB4gedMIoTe1NSBXqdz40OkK2FJCaac94B8JEXaqXdyAoXqHP/AHCqSAQGE1xMB8z76q+smPf9UuLpz/LNBSSmg5pug1DLA7muQbX6wVh6oAAAAASUVORK5CYII=',
    'cross': 'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAA7UlEQVR4nK2U0QnCMBCGP7uDQjbwQbuCtLqAD85Q6kCFzCA4gFjBFaoPbhDRFRR88GKrJG1EDwLJ5fLdn7sQ+LeprMpVVg2+iB+orMrtOhLnEiiAMgQmMSVQyNknCFgBB2AE7FVWqRZIH9hK7AlYv0BGx1dgKrAhsHPBBFICY4EkRsfnpqJOWBsEoBeQNQVubRAnSGC2mCPgKG47nxodXz7POEEOZfiUWItczhbzJnaC5Go7UXOUMQQ2vncWUuwEuH/4UqNj41Xka3HIO4u6IHa/CxaFQEJgVtGCurATX4sbsBl1A+ZvAb9+I3+zB9R9htmO3q44AAAAAElFTkSuQmCC',
    'audio': 'iVBORw0KGgoAAAANSUhEUgAAABYAAAAWCAYAAADEtGw7AAACpElEQVR4nNXVP4hdRRQG8N+770XQuKgkZBkbdxFEIk5lIoqNCP4JarSwjHYZQdBKbRRWWJsFFdPoKPgfuwSyikFtDNikEsfOIqZQRkWNsqBgsu9Z7Nz4srtPO8EDlzvnzpnvfHPmfHP5ry2kMgipjNp4OaTybUhlufndNvHDaX8wCxRdzXE9pPIyrsVTeA831RzHDXyC2GK/CKl0NccxbJd5GvQV3ID78F0D6m1Sc5xgHu+EVJ7rE4ZUBl0bjNqzYwr0NSzgrgawcxOHUUhlV83xE9yOW0IquTHuZpXiTezG/VOf9+Aj7G/+FVjFas1xpa07ieM1xxcHIZW9OIAR1nAbRjXHh1pZBm2L8w14X1/HkMoijuJozfH5kErAx3igwzFch11ImJ8G3VxXdCGVgyGVPTXHb3AHDoVUbq45VpzAEx121BwP1xyfbEk+6GvYM5uyPtGtOBlSub7meBav47FG5jj2d1gPqcy1g7sSl7WAie2tqzk+jbex3GJPYLHNf4W5rrE4X3M8h7G/22imNRLvYqHF/oBLcUnNcQ3DvskvtBoGjcVMayQO4UyLnccf+DOkMof1DsOa41oL/hW/NxazwMchlRU8jGda7N043eZvxNoI55oYfsOd+AUv4fyUbHvrE36OlZrjTyGVq3AYj9QcJyGVgzjV4UF8jZ+R8X1I5VhjMnGx7AcY1xxXG+giPsVbNcdTrY8P4Mgs5b1hQ2m98ia2Km+njdb6sOb4Qlt3kfK6KVY9o/WQyqu4Bvc2/2obPb6vKXGEuZrj2ZDKbryP0zXHR0Mqwy2MN91uR7C31f5yfGbq2mzve7BiQ9ZL/blsuTZbbcchlWHN8XF82ba80Epy4TAbiR/bwS31yf5RB5v+IM+GVM6EVJaa/69/kP+f/QXI41NJ9fwIUQAAAABJRU5ErkJggg==',
    'stop': 'iVBORw0KGgoAAAANSUhEUgAAABYAAAAWCAYAAADEtGw7AAAAO0lEQVR4nGNgGAVDFjDikpBMv/SfWEOez9TDMIeJUkNxqcdqMDXAqMGjBo8aTKrB2PI+PkCq+lFAHQAAg7gMGolb1nEAAAAASUVORK5CYII=',
}


class ModernPillButton(tk.Canvas):
    """Small modern rounded button drawn with Tk Canvas.

    ttk buttons cannot reliably draw rounded corners on Windows.  This widget
    draws a cleaner Google-style capsule outline and can show either text or an
    embedded icon while keeping references safely inside Tk.
    """
    def __init__(
        self,
        parent,
        text: str = '',
        command=None,
        *,
        image=None,
        selected: bool = False,
        width: int | None = None,
        height: int = 28,
        min_width: int = 44,
        font=('Segoe UI', 9, 'bold'),
        bg_surface: str | None = None,
        fg: str = '#1967d2',
        selected_fg: str = '#174ea6',
        fill: str = '#ffffff',
        selected_fill: str = '#e8f0fe',
        hover_fill: str = '#f8fbff',
        border: str = '#d2e3fc',
        selected_border: str = '#d2e3fc',
        padx: int = 18,
        cursor: str = 'hand2',
    ):
        self._text = str(text)
        self._command = command
        self._image = image
        self._selected = bool(selected)
        self._hover = False
        self._pressed = False
        self._font = font
        self._height = int(height)
        self._min_width = int(min_width)
        self._fixed_width = width
        self._padx = int(padx)
        self._fg = fg
        self._selected_fg = selected_fg
        self._fill = fill
        self._selected_fill = selected_fill
        self._hover_fill = hover_fill
        self._border = border
        self._selected_border = selected_border
        self._bg_surface = bg_surface or self._parent_bg(parent)
        super().__init__(
            parent,
            width=self._natural_width(),
            height=self._height,
            bg=self._bg_surface,
            highlightthickness=0,
            bd=0,
            relief='flat',
            cursor=cursor,
        )
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<ButtonRelease-1>', self._on_release)
        self._draw()

    def _parent_bg(self, parent) -> str:
        for key in ('bg', 'background'):
            try:
                value = parent.cget(key)
                if value:
                    return value
            except Exception:
                pass
        return '#f8fafd'

    def _image_size(self) -> tuple[int, int]:
        try:
            if self._image is not None:
                return int(self._image.width()), int(self._image.height())
        except Exception:
            pass
        return (0, 0)

    def _text_width(self) -> int:
        if not self._text:
            return 0
        try:
            import tkinter.font as tkfont
            font = tkfont.Font(font=self._font)
            return int(font.measure(self._text))
        except Exception:
            return len(self._text) * 8

    def _natural_width(self) -> int:
        if self._fixed_width is not None:
            return int(self._fixed_width)
        image_width, _image_height = self._image_size()
        text_width = self._text_width()
        gap = 6 if image_width and text_width else 0
        content_width = image_width + gap + text_width
        return max(self._min_width, int(content_width + self._padx * 2))

    def _round_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, *, fill: str, outline: str) -> None:
        """Draw a smooth pill border that looks consistent in normal/selected states."""
        radius = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
        # Tk canvas arcs can look jagged on white buttons in Windows scaling.
        # A smoothed polygon gives the normal state the same clean capsule
        # silhouette as the highlighted/selected state.
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        self.create_polygon(
            points,
            smooth=True,
            splinesteps=16,
            fill=fill,
            outline=outline,
            width=1,
        )

    def _draw(self) -> None:
        self.delete('all')
        width = self._natural_width()
        if int(self.cget('width')) != width:
            super().configure(width=width)
        height = self._height
        fill = self._selected_fill if self._selected else (self._hover_fill if self._hover else self._fill)
        outline = self._selected_border if self._selected else self._border
        fg = self._selected_fg if self._selected else self._fg
        if self._pressed:
            fill = '#d2e3fc'
            outline = self._selected_border

        radius = max(8, height // 2 - 2)
        self._round_rect(1, 1, width - 2, height - 2, radius, fill=fill, outline=outline)

        image_width, image_height = self._image_size()
        text_width = self._text_width()
        gap = 6 if image_width and text_width else 0
        total_width = image_width + gap + text_width
        left = (width - total_width) // 2
        center_y = height // 2

        if self._image is not None and image_width:
            self.create_image(left + image_width // 2, center_y, image=self._image)
            left += image_width + gap
        if self._text:
            self.create_text(left + text_width // 2, center_y, text=self._text, font=self._font, fill=fg)

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event=None) -> None:
        self._pressed = True
        self._draw()

    def _on_release(self, event=None) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if not was_pressed:
            return
        if event is not None:
            try:
                if not (0 <= event.x <= int(self.cget('width')) and 0 <= event.y <= int(self.cget('height'))):
                    return
            except Exception:
                pass
        if self._command is not None:
            self._command()

    def set_selected(self, value: bool) -> None:
        value = bool(value)
        if self._selected != value:
            self._selected = value
            self._draw()

    def set_text(self, text: str) -> None:
        text = str(text)
        if self._text != text:
            self._text = text
            self._draw()

    def set_image(self, image) -> None:
        if self._image is not image:
            self._image = image
            self._draw()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        redraw = False
        passthrough = {}
        for key, value in kwargs.items():
            if key == 'text':
                self._text = str(value)
                redraw = True
            elif key == 'image':
                self._image = value
                redraw = True
            elif key == 'command':
                self._command = value
            elif key == 'selected':
                self._selected = bool(value)
                redraw = True
            elif key == 'font':
                self._font = value
                redraw = True
            elif key == 'min_width':
                self._min_width = int(value)
                redraw = True
            elif key == 'width':
                self._fixed_width = None if value is None else int(value)
                redraw = True
            elif key == 'padx':
                self._padx = int(value)
                redraw = True
            elif key == 'bg_surface':
                self._bg_surface = str(value)
                passthrough['bg'] = self._bg_surface
                redraw = True
            else:
                passthrough[key] = value
        if passthrough:
            super().configure(**passthrough)
        if redraw:
            self._draw()

    config = configure

class FlatBorderButton(tk.Canvas):
    """Plain rectangular text button with the same light border as pill buttons."""
    def __init__(
        self,
        parent,
        text: str = '',
        command=None,
        *,
        width: int | None = None,
        height: int = 26,
        min_width: int = 130,
        font=('Segoe UI', 9),
        bg_surface: str | None = None,
        fg: str = '#202124',
        fill: str = '#ffffff',
        hover_fill: str = '#f8fbff',
        press_fill: str = '#e8f0fe',
        border: str = '#d2e3fc',
        border_width: int = 1,
        padx: int = 10,
        cursor: str = 'hand2',
    ):
        self._text = str(text)
        self._command = command
        self._fixed_width = width
        self._height = int(height)
        self._min_width = int(min_width)
        self._font = font
        self._padx = int(padx)
        self._fg = fg
        self._fill = fill
        self._hover_fill = hover_fill
        self._press_fill = press_fill
        self._border = border
        self._border_width = int(border_width)
        self._hover = False
        self._pressed = False
        self._bg_surface = bg_surface or self._parent_bg(parent)
        super().__init__(
            parent,
            width=self._natural_width(),
            height=self._height,
            bg=self._bg_surface,
            highlightthickness=0,
            bd=0,
            relief='flat',
            cursor=cursor,
        )
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<ButtonRelease-1>', self._on_release)
        self._draw()

    def _parent_bg(self, parent) -> str:
        for key in ('bg', 'background'):
            try:
                value = parent.cget(key)
                if value:
                    return value
            except Exception:
                pass
        return '#f8fafd'

    def _text_width(self) -> int:
        if not self._text:
            return 0
        try:
            import tkinter.font as tkfont
            font = tkfont.Font(font=self._font)
            return int(font.measure(self._text))
        except Exception:
            return len(self._text) * 8

    def _natural_width(self) -> int:
        if self._fixed_width is not None:
            return int(self._fixed_width)
        return max(self._min_width, int(self._text_width() + self._padx * 2))

    def _draw(self) -> None:
        self.delete('all')
        width = self._natural_width()
        if int(self.cget('width')) != width:
            super().configure(width=width)
        fill = self._press_fill if self._pressed else (self._hover_fill if self._hover else self._fill)
        bw = max(1, self._border_width)
        self.create_rectangle(
            bw, bw,
            width - bw - 1,
            self._height - bw - 1,
            fill=fill,
            outline=self._border,
            width=bw,
        )
        self.create_text(
            width // 2,
            self._height // 2,
            text=self._text,
            font=self._font,
            fill=self._fg,
        )

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event=None) -> None:
        self._pressed = True
        self._draw()

    def _on_release(self, event=None) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if not was_pressed:
            return
        if event is not None:
            try:
                if not (0 <= event.x <= int(self.cget('width')) and 0 <= event.y <= int(self.cget('height'))):
                    return
            except Exception:
                pass
        if self._command is not None:
            self._command()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        redraw = False
        passthrough = {}
        for key, value in kwargs.items():
            if key == 'text':
                self._text = str(value)
                redraw = True
            elif key == 'command':
                self._command = value
            elif key == 'font':
                self._font = value
                redraw = True
            elif key == 'min_width':
                self._min_width = int(value)
                redraw = True
            elif key == 'width':
                self._fixed_width = None if value is None else int(value)
                redraw = True
            elif key == 'padx':
                self._padx = int(value)
                redraw = True
            elif key == 'bg_surface':
                self._bg_surface = str(value)
                passthrough['bg'] = self._bg_surface
                redraw = True
            elif key in {'fg', 'foreground'}:
                self._fg = str(value)
                redraw = True
            elif key == 'border':
                self._border = str(value)
                redraw = True
            elif key == 'border_width':
                self._border_width = int(value)
                redraw = True
            else:
                passthrough[key] = value
        if passthrough:
            super().configure(**passthrough)
        if redraw:
            self._draw()

    config = configure


class ToolTip:
    """Small hover tooltip for canvas and Tk buttons."""
    def __init__(self, widget, text: str = '', delay_ms: int = 450):
        self.widget = widget
        self.text = str(text)
        self.delay_ms = int(delay_ms)
        self.after_id = None
        self.tip_window = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress-1>', self._hide, add='+')

    def set_text(self, text: str) -> None:
        self.text = str(text)
        if self.tip_window is not None:
            try:
                label = self.tip_window.winfo_children()[0]
                label.configure(text=self.text)
            except Exception:
                pass

    def _schedule(self, _event=None) -> None:
        self._cancel()
        if not self.text:
            return
        try:
            self.after_id = self.widget.after(self.delay_ms, self._show)
        except tk.TclError:
            self.after_id = None

    def _cancel(self) -> None:
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None

    def _show(self) -> None:
        self.after_id = None
        if self.tip_window is not None or not self.text:
            return
        try:
            x = self.widget.winfo_pointerx() + 12
            y = self.widget.winfo_pointery() + 16
            self.tip_window = tk.Toplevel(self.widget)
            self.tip_window.withdraw()
            self.tip_window.overrideredirect(True)
            self.tip_window.configure(bg='#3c4043')
            label = tk.Label(
                self.tip_window,
                text=self.text,
                bg='#3c4043',
                fg='#ffffff',
                padx=8,
                pady=4,
                bd=0,
                font=('Segoe UI', 9),
            )
            label.pack()
            self.tip_window.geometry(f'+{x}+{y}')
            self.tip_window.deiconify()
        except tk.TclError:
            self.tip_window = None

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.tip_window is not None:
            try:
                self.tip_window.destroy()
            except tk.TclError:
                pass
            self.tip_window = None


class StatusMessageProxy:
    def __init__(self, app):
        self.app = app

    def configure(self, **kwargs) -> None:
        text = kwargs.get('text')
        if text is not None:
            self.app.show_status_message(str(text))

    config = configure


class HokkienIMEPad:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.ui_language = tk.StringVar(value='en')
        self.root.title(APP_TITLE_EN)
        self.root.geometry('660x360')
        self.root.minsize(600, 360)

        self.composer = Composer()
        self.undo_stack = []
        self.redo_stack = []
        self.hanri_instance_readings = []
        self.hanri_instance_text_snapshot = ''
        # Stores recent raw keypresses plus the composer state before each key.
        # This lets Hokkien shortcuts rewrite instantly after the full sequence is typed,
        # without delaying normal Korean input such as fkd → 랑.
        self.key_history = []
        self.ime_on = tk.BooleanVar(value=True)
        self.hanri_on = tk.BooleanVar(value=True)
        # When Hanri is toggled off, converted Hanri spans are remembered so
        # toggling back on can restore the exact original Hanri choices only if
        # the user has not edited the Hangulised text.
        self.hanri_toggle_snapshot = None
        # Input mode: Hangul uses the Korean 2-beolsik layout; Lomari uses
        # QWERTY romanisation and converts it live into Hangul.
        self.input_mode = tk.StringVar(value='hangul')
        self.lomari_raw = ''
        self.lomari_start_snapshot = None
        self.bopomofo_boundary_marker_pos = None
        # Controls whether pure Hangul output keeps tone marks.
        # Hanri candidates themselves never receive tone marks.
        self.output_tones_on = tk.BooleanVar(value=True)
        self.e_to_ye_autocorrect_on = tk.BooleanVar(value=True)
        self.composer.e_to_ye_autocorrect_enabled = self.e_to_ye_autocorrect_on.get
        self.lomari_key_style = tk.StringVar(value=LOMARI_KEY_STYLE_STANDARD)
        self.candidate_popup = None
        self.candidate_listbox = None
        self.candidate = None
        self.candidate_index = 0
        self.candidate_visibility_after_id = None
        # When the user explicitly chooses the pure-Hangul candidate, do not
        # immediately reopen the same Hanri menu just because they press Space.
        self.suppressed_hanri_contexts = set()
        self.always_on_top = tk.BooleanVar(value=False)
        self.html_style = tk.StringVar(value='plain')
        self.tone_marker_module = None
        self.tone_marker_module_mtime = None
        self.roman_preview_after_id = None
        self.roman_preview_pending_content = ''
        self.roman_preview_rendered_content = None
        self.roman_preview_rendered_text = None
        self.text_cursor_steady_after_id = None
        self.settings_button = None
        self.audio_playing = False
        self.audio_thread = None
        self.audio_stop_requested = False
        self.audio_button = None
        self.audio_after_id = None
        self.audio_playback_id = 0
        self.audio_mode = tk.StringVar(value=AUDIO_MODE_TAIPEI)
        self.keyboard_help_open = False
        self.keyboard_help_shifted = False
        self.keyboard_help_ctrled = False
        self.keyboard_guide_pressed_keys = set()
        self.keyboard_guide_keycaps = {}
        self.keyboard_help_panel = None
        self.keyboard_help_popup_content = None
        self.keyboard_help_embedded_panel = None
        self.keyboard_help_embedded_content = None
        self.keyboard_help_embedded = False
        self.keyboard_help_content = None
        self.keyboard_help_button = None
        self.language_button = None
        self.header_title_label = None
        self.hanri_button = None
        self.ime_button = None
        self.keyboard_label = None
        self.hangul_button = None
        self.lomari_button = None
        self.bopomofo_button = None
        self.navigation_hint_label = None
        self.hokkien_tab_label = None
        self.copyright_label = None
        self.status_restore_after_id = None
        self.keyboard_help_header_label = None
        self.clear_tooltip = None
        self.copy_tooltip = None
        self.copy_html_tooltip = None
        self.sandhi_label = None
        self.taipei_button = None
        self.singapore_button = None
        self.tone_marks_label = None
        self.tone_tooltips = {}
        self.modern_pill_controls = []
        self.icon_images = self.load_builtin_icons()
        self.audio_tooltip = None
        # Last text copied through the IME.  This gives Ctrl+C -> Ctrl+V a
        # reliable in-app fallback even when the platform clipboard owner is
        # transferred to PowerShell/clip so the text survives after exit.
        self.last_clipboard_plain_text = ''

        self.ui_font = ('Segoe UI', 9)
        # Use separate Noto Sans fonts by script:
        #   Hangul / Hokkien-Hangul -> Noto Sans KR
        #   Hanri / Chinese characters -> Noto Sans TC
        self.hangul_font_family = self.pick_font([
            'Noto Sans KR',
            'Noto Sans CJK KR',
            'Noto Sans',
            'Malgun Gothic',
            'Segoe UI',
        ], fallback='Noto Sans KR')
        self.hanri_font_family = 'Noto Sans TC'
        self.extension_b_hanri_font_family = 'Noto Sans TC'
        self.sc_hanri_font_family = self.pick_font([
            'Noto Sans SC',
            'Noto Sans CJK SC',
            'Noto Sans TC',
            'Noto Sans CJK TC',
            'Noto Sans',
            'Microsoft YaHei',
            'Microsoft JhengHei',
            'Segoe UI',
        ], fallback='Noto Sans SC')
        self.lomari_font_family = self.pick_font([
            'Google Sans',
            'Product Sans',
            'Noto Sans',
            'Segoe UI',
            'Arial',
        ], fallback='Segoe UI')
        self.text_font = (self.hangul_font_family, 17)
        self.hanri_font = (self.hanri_font_family, 17)
        self.extension_b_hanri_font = (self.extension_b_hanri_font_family, 17)
        self.sc_hanri_font = (self.sc_hanri_font_family, 17)
        self.candidate_font = (self.hangul_font_family, 13)
        self.candidate_hanri_font = (self.hanri_font_family, 13)
        self.candidate_extension_b_hanri_font = (self.extension_b_hanri_font_family, 13)
        self.candidate_sc_hanri_font = (self.sc_hanri_font_family, 13)
        # Keep tone marks in Calibri even when Hangul/Hanri use Noto Sans.
        self.tone_font = ('Calibri', 19)
        self.candidate_tone_font = ('Calibri', 15)
        self.mono_font = ('Consolas', 9)

        self._build_ui()
        self._bind_keys()
        self.render()
        self.root.after_idle(self.apply_startup_topmost)

    def reset_lomari_buffer(self) -> None:
        self.lomari_raw = ''
        self.lomari_start_snapshot = None

    def reset_bopomofo_boundary(self, remove_marker: bool = True) -> None:
        pos = self.bopomofo_boundary_marker_pos
        self.bopomofo_boundary_marker_pos = None
        if not remove_marker or pos is None:
            return
        try:
            self.composer.commit()
            if 0 <= pos < len(self.composer.output) and self.composer.output[pos] == '-':
                self.composer.output = self.composer.output[:pos] + self.composer.output[pos + 1:]
                if self.composer.cursor_pos > pos:
                    self.composer.cursor_pos -= 1
                self.composer.clamp_cursor()
        except Exception:
            pass

    def apply_startup_topmost(self) -> None:
        """Bring the IME forward once on launch without keeping it pinned."""
        try:
            self.root.attributes('-topmost', True)
            self.root.lift()
            self.text.focus_set()
            self.root.after(250, self.restore_startup_topmost_setting)
        except tk.TclError:
            pass

    def restore_startup_topmost_setting(self) -> None:
        try:
            self.toggle_topmost()
        except tk.TclError:
            pass

    def on_input_mode_changed(self) -> None:
        self.close_candidate_popup()
        self.key_history = []
        self.reset_lomari_buffer()
        self.reset_bopomofo_boundary()
        self.composer.commit()
        self.render()
        self.update_keyboard_help_button_visibility()
        if self.keyboard_help_open:
            self.refresh_keyboard_help_panel()
        self.text.focus_set()


    def pick_font(self, preferred: list[str], fallback: str = 'Noto Sans') -> str:
        """Return the first installed font from preferred, otherwise fallback."""
        try:
            import tkinter.font as tkfont
            available = set(tkfont.families(self.root))
        except Exception:
            available = set()

        for family in preferred:
            if family in available:
                return family
        return fallback

    def load_builtin_icons(self) -> dict[str, tk.PhotoImage]:
        """Load the small built-in button icons from embedded PNG data.

        They are embedded so the IME does not depend on image files being in the
        correct folder.  If a user's Tk cannot decode PNG data, the buttons fall
        back to their text labels instead of breaking the IME.
        """
        icons: dict[str, tk.PhotoImage] = {}
        for name, data in BUILTIN_ICON_PNG_DATA.items():
            try:
                icons[name] = tk.PhotoImage(data=data, format='png')
            except tk.TclError:
                try:
                    icons[name] = tk.PhotoImage(data=data)
                except tk.TclError:
                    pass
        return icons

    def make_modern_button(self, parent, text: str, command=None, **kwargs):
        return ModernPillButton(
            parent,
            text=text,
            command=command,
            bg_surface=getattr(self, 'surface_bg', '#f8fafd'),
            **kwargs,
        )

    def add_tooltip(self, widget, text: str) -> ToolTip:
        return ToolTip(widget, text)

    def tr(self, key: str, **kwargs) -> str:
        lang = self.ui_language.get() if hasattr(self, 'ui_language') else 'en'
        text = UI_TEXT.get(lang, UI_TEXT['en']).get(key, UI_TEXT['en'].get(key, key))
        if kwargs:
            return text.format(**kwargs)
        return text

    def ui_font_tuple(self, size: int = 9, weight: str | None = None) -> tuple:
        family = self.hanri_font_family if self.ui_language.get() == 'zh' else 'Segoe UI'
        return (family, size, weight) if weight else (family, size)

    def toggle_ui_language(self) -> str:
        self.ui_language.set('zh' if self.ui_language.get() == 'en' else 'en')
        self.apply_ui_language()
        self.text.focus_set()
        return 'break'

    def keyboard_help_button_label(self) -> str:
        return self.tr('keyboard_guide_open' if self.keyboard_help_open else 'keyboard_guide_closed')

    def copyright_status_text(self) -> str:
        return '© Zhen Dong Woo 2026'

    def restore_copyright_status(self) -> None:
        self.status_restore_after_id = None
        if self.copyright_label is None:
            return
        try:
            self.copyright_label.configure(text=self.copyright_status_text(), fg=getattr(self, 'muted_text', '#5f6368'))
        except Exception:
            pass

    def show_status_message(self, text: str, duration_ms: int = 4500) -> None:
        if not text or text == self.tr('ready') or text.startswith(('IME ON', 'IME OFF')):
            self.restore_copyright_status()
            return
        if self.copyright_label is None:
            return
        if self.status_restore_after_id is not None:
            try:
                self.root.after_cancel(self.status_restore_after_id)
            except Exception:
                pass
            self.status_restore_after_id = None
        try:
            self.copyright_label.configure(text=text, fg=getattr(self, 'muted_text', '#5f6368'))
            self.status_restore_after_id = self.root.after(duration_ms, self.restore_copyright_status)
        except Exception:
            pass

    def apply_ui_language(self) -> None:
        self.root.title(self.tr('app_title'))
        ui_font = self.ui_font_tuple()
        ui_bold_font = self.ui_font_tuple(9, 'bold')
        ui_title_font = self.ui_font_tuple(13, 'bold')
        ui_tab_font = self.ui_font_tuple(10, 'bold')
        language_button_font = (self.hanri_font_family, 9, 'bold') if self.ui_language.get() == 'en' else ui_bold_font
        try:
            style = ttk.Style(self.root)
            style.configure('App.TLabel', font=ui_font)
            style.configure('Muted.TLabel', font=ui_font)
            style.configure('Section.TLabel', font=ui_bold_font)
            style.configure('TButton', font=ui_font)
        except Exception:
            pass
        updates = [
            (self.header_title_label, 'app_title'),
            (self.language_button, 'language_toggle'),
            (self.settings_button, 'settings'),
            (self.hanri_button, 'hanri'),
            (self.ime_button, 'ime'),
            (self.keyboard_label, 'keyboard'),
            (self.hangul_button, 'hangul'),
            (self.lomari_button, 'lomari'),
            (self.bopomofo_button, 'bopomofo'),
            (self.navigation_hint_label, 'navigation_hint'),
            (self.hokkien_tab_label, 'hokkien_tab'),
            (self.keyboard_help_header_label, 'keyboard_guide_title'),
            (self.sandhi_label, 'sandhi'),
            (self.taipei_button, 'taipei'),
            (self.singapore_button, 'singapore'),
            (self.tone_marks_label, 'tone_marks'),
        ]
        for widget, key in updates:
            if widget is not None:
                try:
                    widget.configure(text=self.tr(key))
                except Exception:
                    pass

        font_updates = [
            (self.header_title_label, ui_title_font),
            (self.language_button, language_button_font),
            (self.settings_button, ui_bold_font),
            (self.hanri_button, ui_bold_font),
            (self.ime_button, ui_bold_font),
            (self.keyboard_label, ui_font),
            (self.hangul_button, ui_bold_font),
            (self.lomari_button, ui_bold_font),
            (self.bopomofo_button, ui_bold_font),
            (self.navigation_hint_label, ui_font),
            (self.hokkien_tab_label, ui_tab_font),
            (self.copyright_label, ui_font),
            (self.keyboard_help_button, ui_font),
            (self.keyboard_help_header_label, ui_tab_font),
            (self.sandhi_label, ui_font),
            (self.taipei_button, ui_bold_font),
            (self.singapore_button, ui_bold_font),
            (self.tone_marks_label, ui_bold_font),
        ]
        for widget, font in font_updates:
            if widget is not None:
                try:
                    widget.configure(font=font)
                except Exception:
                    pass

        self.apply_language_button_sizing()

        if self.keyboard_help_button is not None:
            try:
                self.keyboard_help_button.configure(text=self.keyboard_help_button_label())
            except Exception:
                pass

        tooltip_updates = [
            (self.clear_tooltip, 'clear_text'),
            (self.copy_tooltip, 'copy_text'),
            (self.copy_html_tooltip, 'copy_html'),
            (self.audio_tooltip, 'stop' if self.audio_playing else 'listen'),
        ]
        for tooltip, key in tooltip_updates:
            if tooltip is not None:
                try:
                    tooltip.set_text(self.tr(key))
                except Exception:
                    pass

        for digit, tooltip in getattr(self, 'tone_tooltips', {}).items():
            if tooltip is not None:
                try:
                    tooltip.set_text(self.tr(f'tone_{digit}'))
                except Exception:
                    pass

        if self.keyboard_help_panel is not None:
            try:
                self.keyboard_help_panel.title(self.tr('keyboard_guide_title'))
            except Exception:
                pass
        if self.keyboard_help_open:
            self.refresh_keyboard_help_panel()

    def apply_language_button_sizing(self) -> None:
        """Let compact Chinese labels use compact button widths."""
        lang = self.ui_language.get()
        if lang == 'zh':
            sizes = [
                (self.language_button, 72),
                (self.settings_button, 52),
                (self.hanri_button, 52),
                (self.ime_button, 56),
                (self.taipei_button, 54),
                (self.singapore_button, 66),
                (self.hangul_button, 56),
                (self.lomari_button, 116),
                (self.bopomofo_button, 66),
                (self.keyboard_help_button, 108),
            ]
        else:
            sizes = [
                (self.language_button, 72),
                (self.settings_button, 82),
                (self.hanri_button, 64),
                (self.ime_button, 54),
                (self.taipei_button, 64),
                (self.singapore_button, 92),
                (self.hangul_button, 70),
                (self.lomari_button, 132),
                (self.bopomofo_button, 112),
                (self.keyboard_help_button, 132),
            ]
        for widget, min_width in sizes:
            if widget is None:
                continue
            try:
                widget.configure(min_width=min_width)
            except Exception:
                pass

    def make_modern_bool_toggle(self, parent, text: str, variable, command=None, **kwargs):
        def on_click():
            variable.set(not bool(variable.get()))
            if command is not None:
                command()
            self.refresh_modern_control_states()

        button = self.make_modern_button(
            parent,
            text,
            on_click,
            selected=bool(variable.get()),
            **kwargs,
        )
        self.modern_pill_controls.append((button, variable, None))
        return button

    def make_modern_radio_toggle(self, parent, text: str, variable, value: str, command=None, **kwargs):
        def on_click():
            if variable.get() != value:
                variable.set(value)
                if command is not None:
                    command()
            else:
                self.refresh_modern_control_states()

        button = self.make_modern_button(
            parent,
            text,
            on_click,
            selected=(variable.get() == value),
            **kwargs,
        )
        self.modern_pill_controls.append((button, variable, value))
        return button

    def refresh_modern_control_states(self) -> None:
        for button, variable, value in getattr(self, 'modern_pill_controls', []):
            try:
                selected = bool(variable.get()) if value is None else (variable.get() == value)
                button.set_selected(selected)
            except Exception:
                pass

    def load_tone_marker_module(self):
        """Load the external tone-marker converter module on first use."""
        path = TONE_MARKER_MODULE_PATH
        if not path.exists():
            raise FileNotFoundError(f'Tone-marker converter not found: {path}')
        try:
            module_mtime = path.stat().st_mtime_ns
        except OSError:
            module_mtime = None

        if (
            self.tone_marker_module is not None
            and self.tone_marker_module_mtime == module_mtime
        ):
            return self.tone_marker_module

        spec = importlib.util.spec_from_file_location('hokkien_tone_marker_converter', path)
        if spec is None or spec.loader is None:
            raise ImportError(f'Could not load tone-marker converter: {path}')

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if not hasattr(module, 'convert_hangul_to_html'):
            raise ImportError('Tone-marker converter has no convert_hangul_to_html() function.')

        self.tone_marker_module = module
        self.tone_marker_module_mtime = module_mtime
        return module

    def show_settings_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        try:
            menu.configure(font=self.ui_font_tuple())
        except Exception:
            pass
        menu.add_checkbutton(
            label=self.tr('keep_top'),
            variable=self.always_on_top,
            command=self.toggle_topmost,
        )
        menu.add_checkbutton(
            label=self.tr('settings_e_to_ye_autocorrect'),
            variable=self.e_to_ye_autocorrect_on,
            command=self.on_e_to_ye_autocorrect_setting_changed,
        )
        lomari_style_menu = tk.Menu(menu, tearoff=False)
        try:
            lomari_style_menu.configure(font=self.ui_font_tuple())
        except Exception:
            pass
        for label_key, value in (
            ('settings_lomari_key_style_standard', LOMARI_KEY_STYLE_STANDARD),
            ('settings_lomari_key_style_poj', LOMARI_KEY_STYLE_POJ),
            ('settings_lomari_key_style_tailo', LOMARI_KEY_STYLE_TAILO),
        ):
            lomari_style_menu.add_radiobutton(
                label=self.tr(label_key),
                variable=self.lomari_key_style,
                value=value,
                command=self.on_lomari_key_style_changed,
            )
        menu.add_cascade(label=self.tr('settings_lomari_key_style'), menu=lomari_style_menu)
        menu.add_separator()
        menu.add_radiobutton(
            label=self.tr('settings_plain'),
            variable=self.html_style,
            value='plain',
        )
        menu.add_radiobutton(
            label=self.tr('settings_lomari_ruby_below'),
            variable=self.html_style,
            value='lomari_ruby_below',
        )
        menu.add_radiobutton(
            label=self.tr('settings_lomari_next_line'),
            variable=self.html_style,
            value='lomari_next_line',
        )
        menu.add_radiobutton(
            label=self.tr('settings_song'),
            variable=self.html_style,
            value='song',
        )
        novel_menu = tk.Menu(menu, tearoff=False)
        try:
            novel_menu.configure(font=self.ui_font_tuple())
        except Exception:
            pass
        novel_menu.add_radiobutton(
            label=self.tr('settings_novel'),
            variable=self.html_style,
            value='novel',
        )
        novel_menu.add_radiobutton(
            label=self.tr('settings_novel_first'),
            variable=self.html_style,
            value='novel_first',
        )
        novel_menu_index = menu.index('end') + 1
        menu.add_cascade(label=self.tr('settings_novel'), menu=novel_menu)
        menu.add_radiobutton(
            label=self.tr('settings_title'),
            variable=self.html_style,
            value='title',
        )
        left_submenu_state = {'posted': False}

        def keep_novel_submenu_left(_event=None) -> None:
            try:
                active_index = menu.index('active')
            except Exception:
                active_index = None
            if active_index == novel_menu_index:
                try:
                    novel_menu.update_idletasks()
                    x = menu.winfo_rootx() - max(1, novel_menu.winfo_reqwidth())
                    y = menu.winfo_rooty() + menu.yposition(novel_menu_index)
                    novel_menu.unpost()
                    novel_menu.post(x, y)
                    left_submenu_state['posted'] = True
                except Exception:
                    pass
            elif left_submenu_state.get('posted'):
                try:
                    novel_menu.unpost()
                except Exception:
                    pass
                left_submenu_state['posted'] = False

        menu.bind('<<MenuSelect>>', keep_novel_submenu_left, add='+')
        menu.bind('<Unmap>', lambda _event: novel_menu.unpost(), add='+')

        button = self.settings_button
        try:
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _build_ui(self) -> None:
        # A cleaner, card-like layout closer to modern translation/input tools.
        # Tkinter cannot truly round Text widget corners without a canvas wrapper,
        # but the white cards, subtle borders, and accent focus line avoid the
        # older Windows-XP-style sunken boxes.
        surface_bg = '#f8fafd'
        card_bg = '#ffffff'
        border_color = '#dadce0'
        accent_color = '#1a73e8'
        muted_text = '#5f6368'
        self.surface_bg = surface_bg
        self.card_bg = card_bg
        self.border_color = border_color
        self.accent_color = accent_color
        self.muted_text = muted_text

        try:
            self.root.configure(bg=surface_bg)
        except tk.TclError:
            pass

        self.shell = ttk.Frame(self.root, style='App.TFrame')
        self.shell.pack(fill='both', expand=True)

        outer = ttk.Frame(self.shell, padding=6, style='App.TFrame')
        outer.pack(side='left', fill='both', expand=True)
        self.build_keyboard_help_panel()

        # --- Header / compact global toggles ---
        top = ttk.Frame(outer, style='App.TFrame')
        top.pack(fill='x')
        self.header_title_label = ttk.Label(top, text=self.tr('app_title'), font=('Segoe UI', 13, 'bold'), style='App.TLabel')
        self.header_title_label.pack(side='left')

        header_toggles = ttk.Frame(top, style='App.TFrame')
        header_toggles.pack(side='right')
        self.language_button = self.make_modern_button(
            header_toggles,
            text=self.tr('language_toggle'),
            command=self.toggle_ui_language,
            min_width=72,
        )
        self.language_button.pack(side='left', padx=(0, 6))
        self.settings_button = self.make_modern_button(
            header_toggles,
            text=self.tr('settings'),
            command=self.show_settings_menu,
            min_width=82,
        )
        self.settings_button.pack(side='left', padx=(0, 6))
        self.hanri_button = self.make_modern_bool_toggle(
            header_toggles,
            text=self.tr('hanri'),
            variable=self.hanri_on,
            command=self.apply_hanri_and_render,
        )
        self.hanri_button.pack(side='left', padx=(0, 6))
        self.ime_button = self.make_modern_bool_toggle(
            header_toggles,
            text=self.tr('ime'),
            variable=self.ime_on,
            command=self.render,
        )
        self.ime_button.pack(side='left')

        # --- Main typing card with attached tab ---
        typing_header = tk.Frame(outer, bg=surface_bg, bd=0)
        typing_header.pack(fill='x', pady=(2, 0))

        # Make the section title feel like a selected tab growing out of the
        # typing pad, similar to modern translation/input interfaces.
        hokkien_tab = tk.Frame(
            typing_header,
            bg=card_bg,
            highlightbackground=border_color,
            highlightcolor=border_color,
            highlightthickness=1,
            bd=0,
        )
        hokkien_tab.pack(side='left', anchor='s')
        self.hokkien_tab_label = tk.Label(
            hokkien_tab,
            text=self.tr('hokkien_tab'),
            font=('Segoe UI', 10, 'bold'),
            bg=card_bg,
            fg=accent_color,
            padx=12,
            pady=4,
        )
        self.hokkien_tab_label.pack(side='top', fill='x')
        tk.Frame(hokkien_tab, bg=accent_color, height=2, bd=0).pack(side='bottom', fill='x')

        self.copyright_label = tk.Label(
            typing_header,
            text='© Zhen Dong Woo 2026',
            font=self.ui_font_tuple(9),
            bg=surface_bg,
            fg=muted_text,
        )
        self.copyright_label.pack(side='right', anchor='s', padx=(8, 0), pady=(0, 4))

        header_rule = tk.Frame(typing_header, bg=border_color, height=1, bd=0)
        header_rule.pack(side='left', fill='x', expand=True, anchor='s', pady=(0, 0))

        typing_card = tk.Frame(
            outer,
            bg=card_bg,
            highlightbackground=border_color,
            highlightcolor=border_color,
            highlightthickness=1,
            bd=0,
        )
        typing_card.pack(fill='both', expand=True, pady=(0, 5))

        input_row = tk.Frame(typing_card, bg=card_bg, bd=0)
        input_row.pack(fill='both', expand=True)
        input_row.grid_columnconfigure(0, weight=1)
        input_row.grid_columnconfigure(1, minsize=38)
        input_row.grid_rowconfigure(0, weight=1)

        self.text = tk.Text(
            input_row,
            height=4,
            wrap='word',
            font=self.text_font,
            undo=False,
            padx=8,
            pady=6,
            bd=0,
            relief='flat',
            highlightthickness=0,
            bg=card_bg,
            fg='#202124',
            insertbackground=TEXT_CURSOR_COLOR,
            insertwidth=TEXT_CURSOR_WIDTH,
            insertontime=TEXT_CURSOR_BLINK_ON_MS,
            insertofftime=TEXT_CURSOR_BLINK_OFF_MS,
            selectbackground='#d2e3fc',
            selectforeground='#202124',
        )
        self.text.grid(row=0, column=0, sticky='nsew')

        clear_gutter = tk.Frame(input_row, bg=card_bg, bd=0, width=38)
        clear_gutter.grid(row=0, column=1, sticky='ns')
        clear_gutter.grid_propagate(False)

        # Clear button gets a reserved gutter so typed text wraps before reaching it.
        self.clear_button = tk.Button(
            clear_gutter,
            text='\u00d7',
            command=self.clear,
            bd=0,
            relief='flat',
            bg=card_bg,
            fg=muted_text,
            activebackground='#f1f3f4',
            activeforeground=muted_text,
            cursor='hand2',
            font=('Segoe UI', 17),
            padx=4,
            pady=0,
        )
        self.clear_button.place(relx=0.5, y=2, anchor='n', width=30, height=30)
        self.clear_tooltip = self.add_tooltip(self.clear_button, self.tr('clear_text'))

        # Google-Translate-like inline Lomari preview: no separate label/card.
        # It stays inside the same typing card, visually as a minimal bottom line.
        tk.Frame(typing_card, bg='#eef0f3', height=1, bd=0).pack(fill='x', side='top')
        roman_preview_font = (self.lomari_font_family, 11)
        try:
            roman_preview_line_height = tkfont.Font(root=self.root, font=roman_preview_font).metrics('linespace')
        except tk.TclError:
            roman_preview_line_height = 18
        self.roman_preview_line_height = roman_preview_line_height
        self.roman_preview_frame = tk.Frame(
            typing_card,
            bg=card_bg,
            bd=0,
            height=(roman_preview_line_height * ROMAN_PREVIEW_MIN_LINES) + 8,
        )
        self.roman_preview_frame.pack(fill='x')
        self.roman_preview_frame.pack_propagate(False)
        self.roman_preview = tk.Text(
            self.roman_preview_frame,
            height=ROMAN_PREVIEW_MIN_LINES,
            wrap='word',
            font=roman_preview_font,
            bd=0,
            relief='flat',
            highlightthickness=0,
            padx=8,
            pady=2,
            cursor='xterm',
            takefocus=False,
            exportselection=True,
            bg=card_bg,
            fg=muted_text,
            insertbackground='#202124',
            insertwidth=0,
            insertofftime=0,
            selectbackground='#d2e3fc',
            selectforeground='#202124',
        )
        self.roman_preview.pack(fill='both', expand=True)
        self.roman_preview.bind('<Control-a>', self.select_all_roman_preview)
        self.roman_preview.bind('<Control-A>', self.select_all_roman_preview)
        self.roman_preview.bind('<KeyPress>', self.on_roman_preview_keypress)

        # --- Main actions + audio controls ---
        action_row = ttk.Frame(outer, style='App.TFrame')
        action_row.pack(fill='x', pady=(0, 4))
        copy_icon = self.icon_images.get('copy')
        audio_icon = self.icon_images.get('audio')
        self.copy_button = self.make_modern_button(
            action_row,
            text='' if copy_icon else 'Copy All F6',
            image=copy_icon,
            command=self.copy_text,
            min_width=42 if copy_icon else 96,
            width=42 if copy_icon else None,
            padx=8,
            fill=surface_bg if copy_icon else '#ffffff',
            border=surface_bg if copy_icon else '#d2e3fc',
            hover_fill='#e8f0fe' if copy_icon else '#f8fbff',
        )
        self.copy_button.pack(side='left')
        self.copy_tooltip = self.add_tooltip(self.copy_button, self.tr('copy_text'))
        self.copy_html_button = self.make_modern_button(
            action_row,
            text='HTML',
            image=copy_icon,
            command=self.copy_as_html,
            min_width=74 if copy_icon else 96,
            padx=8,
            fill=surface_bg if copy_icon else '#ffffff',
            border=surface_bg if copy_icon else '#d2e3fc',
            hover_fill='#e8f0fe' if copy_icon else '#f8fbff',
        )
        self.copy_html_button.pack(side='left', padx=(6, 0))
        self.copy_html_tooltip = self.add_tooltip(self.copy_html_button, self.tr('copy_html'))

        audio_inline = ttk.Frame(action_row, style='App.TFrame')
        audio_inline.pack(side='right', anchor='e')
        self.audio_button = self.make_modern_button(
            audio_inline,
            text='' if audio_icon else 'Play',
            image=audio_icon,
            command=self.play_recorded_audio,
            min_width=42,
            width=42,
            padx=8,
            fill=surface_bg if audio_icon else '#ffffff',
            border=surface_bg if audio_icon else '#d2e3fc',
            hover_fill='#e8f0fe' if audio_icon else '#f8fbff',
        )
        self.audio_button.pack(side='left', padx=(0, 10))
        self.audio_tooltip = self.add_tooltip(self.audio_button, self.tr('listen'))
        self.sandhi_label = ttk.Label(audio_inline, text=self.tr('sandhi'), style='App.TLabel')
        self.sandhi_label.pack(side='left')
        self.taipei_button = self.make_modern_radio_toggle(
            audio_inline,
            text=self.tr('taipei'),
            variable=self.audio_mode,
            value=AUDIO_MODE_TAIPEI,
            command=self.render,
        )
        self.taipei_button.pack(side='left', padx=(4, 0))
        self.singapore_button = self.make_modern_radio_toggle(
            audio_inline,
            text=self.tr('singapore'),
            variable=self.audio_mode,
            value=AUDIO_MODE_SINGAPORE,
            command=self.render,
            min_width=92,
        )
        self.singapore_button.pack(side='left', padx=(4, 0))

        # --- Keyboard mode ---
        keyboard_row = ttk.Frame(outer, style='App.TFrame')
        keyboard_row.pack(fill='x', pady=(0, 3))
        keyboard_controls = ttk.Frame(keyboard_row, style='App.TFrame')
        keyboard_controls.pack(side='left', anchor='w')
        self.keyboard_label = ttk.Label(keyboard_controls, text=self.tr('keyboard'), style='Muted.TLabel')
        self.keyboard_label.pack(side='left')
        self.hangul_button = self.make_modern_radio_toggle(
            keyboard_controls,
            text=self.tr('hangul'),
            variable=self.input_mode,
            value='hangul',
            command=self.on_input_mode_changed,
        )
        self.hangul_button.pack(side='left', padx=(6, 0))
        self.lomari_button = self.make_modern_radio_toggle(
            keyboard_controls,
            text=self.tr('lomari'),
            variable=self.input_mode,
            value='lomari',
            command=self.on_input_mode_changed,
        )
        self.lomari_button.pack(side='left', padx=(6, 0))
        self.bopomofo_button = self.make_modern_radio_toggle(
            keyboard_controls,
            text=self.tr('bopomofo'),
            variable=self.input_mode,
            value='bopomofo',
            command=self.on_input_mode_changed,
            min_width=112,
        )
        self.bopomofo_button.pack(side='left', padx=(6, 0))

        keyboard_right = ttk.Frame(keyboard_row, style='App.TFrame')
        keyboard_right.pack(side='right', anchor='e')
        self.keyboard_help_button = FlatBorderButton(
            keyboard_right,
            text=self.tr('keyboard_guide_closed'),
            command=self.toggle_keyboard_help,
            bg_surface=surface_bg,
            fg='#202124',
            fill=card_bg,
            hover_fill='#f8fbff',
            press_fill='#e8f0fe',
            border='#d2e3fc',
            border_width=1,
            min_width=132,
            height=26,
            font=('Segoe UI', 9),
            padx=10,
        )
        self.keyboard_help_button.pack(side='left')

        self.keyboard_help_embedded_panel = tk.Frame(
            outer,
            height=300,
            bg=surface_bg,
            highlightbackground=border_color,
            highlightcolor=border_color,
            highlightthickness=1,
            bd=0,
        )
        self.keyboard_help_embedded_panel.pack_propagate(False)
        self.keyboard_help_embedded_content = tk.Frame(self.keyboard_help_embedded_panel, bg=card_bg)
        self.keyboard_help_embedded_content.pack(fill='both', expand=True, padx=8, pady=8)

        self.status = StatusMessageProxy(self)
        self.apply_ui_language()
        self.update_keyboard_help_button_visibility()


    def build_keyboard_help_panel(self) -> None:
        """Create the hidden keyboard guide popup window."""
        if getattr(self, 'keyboard_help_panel', None) is not None:
            return

        win = tk.Toplevel(self.root)
        win.withdraw()
        # Borderless/custom popup avoids the Windows open/close animation and
        # lets the guide sit flush against the main IME window.
        try:
            win.overrideredirect(True)
        except tk.TclError:
            pass
        win.title(self.tr('keyboard_guide_title'))
        win.resizable(False, False)
        win.configure(bg=getattr(self, 'surface_bg', '#f8fafd'))
        win.protocol('WM_DELETE_WINDOW', self.close_keyboard_help_panel)
        try:
            win.transient(self.root)
            win.attributes('-topmost', bool(self.always_on_top.get()))
        except tk.TclError:
            pass

        panel = tk.Frame(
            win,
            width=320,
            height=300,
            bg=getattr(self, 'surface_bg', '#f8fafd'),
            highlightbackground=getattr(self, 'border_color', '#dadce0'),
            highlightcolor=getattr(self, 'border_color', '#dadce0'),
            highlightthickness=1,
            bd=0,
        )
        panel.pack(fill='both', expand=True)
        panel.pack_propagate(False)
        self.keyboard_help_panel = win

        self.keyboard_help_popup_content = tk.Frame(panel, bg=getattr(self, 'card_bg', '#ffffff'))
        self.keyboard_help_popup_content.pack(fill='both', expand=True, padx=8, pady=8)
        if self.keyboard_help_content is None:
            self.keyboard_help_content = self.keyboard_help_popup_content

    def keyboard_help_should_embed(self) -> bool:
        """Use an in-window guide when the IME is fullscreen or maximized."""
        try:
            if bool(self.root.attributes('-fullscreen')):
                return True
        except tk.TclError:
            pass
        try:
            if self.root.state() == 'zoomed':
                return True
        except tk.TclError:
            pass
        return False

    def set_keyboard_help_container_for_window_state(self) -> None:
        """Switch the guide between popup and embedded containers."""
        should_embed = self.keyboard_help_should_embed()
        if should_embed:
            self.keyboard_help_content = self.keyboard_help_embedded_content
            if self.keyboard_help_panel is not None:
                try:
                    self.keyboard_help_panel.withdraw()
                except tk.TclError:
                    pass
            if self.keyboard_help_embedded_panel is not None:
                try:
                    if not self.keyboard_help_embedded_panel.winfo_ismapped():
                        self.keyboard_help_embedded_panel.pack(fill='x', pady=(2, 0))
                except tk.TclError:
                    pass
        else:
            self.keyboard_help_content = self.keyboard_help_popup_content
            if self.keyboard_help_embedded_panel is not None:
                try:
                    if self.keyboard_help_embedded_panel.winfo_ismapped():
                        self.keyboard_help_embedded_panel.pack_forget()
                except tk.TclError:
                    pass
        self.keyboard_help_embedded = should_embed

    def position_keyboard_help_panel(self) -> None:
        """Place the keyboard guide below the main window in normal window mode."""
        if self.keyboard_help_panel is None or self.keyboard_help_embedded:
            return
        try:
            self.root.update_idletasks()
            base_width = 640 if self.input_mode.get() == 'bopomofo' else 560
            width = max(base_width, self.root.winfo_width())
            height = 300
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()
            screen_x = self.root.winfo_vrootx()
            screen_w = self.root.winfo_vrootwidth()
            screen_right = screen_x + screen_w

            x = root_x + max(0, (root_w - width) // 2)
            x = min(max(screen_x, x), max(screen_x, screen_right - width))
            y = root_y + root_h
            self.keyboard_help_panel.geometry(f'{width}x{height}+{x}+{y}')
            self.keyboard_help_panel.attributes('-topmost', bool(self.always_on_top.get()))
            self.keyboard_help_panel.lift()
        except tk.TclError:
            pass

    def show_keyboard_help_for_current_window_state(self, refresh: bool = False) -> None:
        if self.keyboard_help_panel is None:
            self.build_keyboard_help_panel()
        previous_embedded = self.keyboard_help_embedded
        self.set_keyboard_help_container_for_window_state()
        if refresh or previous_embedded != self.keyboard_help_embedded:
            self.refresh_keyboard_help_panel()
        if self.keyboard_help_embedded:
            return
        self.position_keyboard_help_panel()
        if self.keyboard_help_panel is not None:
            try:
                self.keyboard_help_panel.deiconify()
                self.keyboard_help_panel.lift()
                self.keyboard_help_panel.attributes('-topmost', bool(self.always_on_top.get()))
            except tk.TclError:
                pass

    def close_keyboard_help_panel(self) -> None:
        """Hide the keyboard guide popup without changing the main window size."""
        self.keyboard_help_open = False
        self.clear_keyboard_guide_physical_keys()
        self.clear_keyboard_help_content()
        if self.keyboard_help_embedded_panel is not None:
            try:
                self.keyboard_help_embedded_panel.pack_forget()
            except tk.TclError:
                pass
        if self.keyboard_help_panel is not None:
            try:
                self.keyboard_help_panel.withdraw()
            except tk.TclError:
                pass
        self.keyboard_help_embedded = False
        if self.keyboard_help_button is not None:
            self.keyboard_help_button.configure(text=self.keyboard_help_button_label())

    def update_keyboard_help_button_visibility(self) -> None:
        """Keep the keyboard-guide button available for the active keyboard mode."""
        if self.keyboard_help_button is None:
            return
        try:
            if not self.keyboard_help_button.winfo_ismapped():
                self.keyboard_help_button.pack(side='right', padx=(6, 0))
        except tk.TclError:
            pass

    def clear_keyboard_help_content(self) -> None:
        self.keyboard_guide_keycaps = {}
        for content in (self.keyboard_help_popup_content, self.keyboard_help_embedded_content):
            if content is None:
                continue
            for child in content.winfo_children():
                child.destroy()

    def refresh_keyboard_help_panel(self) -> None:
        """Refresh the keyboard instructions for the current input mode."""
        if self.keyboard_help_content is None:
            return
        self.clear_keyboard_help_content()
        if self.input_mode.get() == 'lomari':
            self.show_lomari_keyboard_help()
        elif self.input_mode.get() == 'bopomofo':
            self.show_bopomofo_keyboard_help()
        else:
            self.show_hangul_keyboard_help()

    def show_hangul_keyboard_help(self) -> None:
        """Display the clickable Hangul keyboard layout."""
        if self.keyboard_help_content is None:
            return
        self.show_clickable_keyboard_help(show_hangul_output=True)

    def show_lomari_keyboard_help(self) -> None:
        """Display the clickable Lomari keyboard layout."""
        if self.keyboard_help_content is None:
            return
        self.show_clickable_keyboard_help(show_hangul_output=True)

    def show_bopomofo_keyboard_help(self) -> None:
        """Display the clickable Bopomofo-style keyboard layout."""
        if self.keyboard_help_content is None:
            return
        self.show_clickable_keyboard_help(show_hangul_output=True)

    def show_keyboard_help_subtitle(self, subtitle_text: str, bg: str, muted: str) -> None:
        normal_font = self.ui_font_tuple(9)
        bold_font = self.ui_font_tuple(9, 'bold')
        bold_word = next((word for word in ('Bolded', '粗體') if word in subtitle_text), '')
        if not bold_word:
            subtitle = tk.Label(
                self.keyboard_help_content,
                text=subtitle_text,
                font=normal_font,
                bg=bg,
                fg=muted,
                wraplength=510,
                justify='center',
            )
            subtitle.pack(fill='x', padx=12, pady=(2, 10), anchor='center')
            return

        prefix, rest = subtitle_text.split(bold_word, 1)
        subtitle_row = tk.Frame(self.keyboard_help_content, bg=bg)
        subtitle_row.pack(fill='x', padx=12, pady=(2, 10), anchor='center')
        subtitle = tk.Frame(subtitle_row, bg=bg)
        subtitle.pack(anchor='center')
        for text, font in ((prefix, normal_font), (bold_word, bold_font), (rest, normal_font)):
            if not text:
                continue
            tk.Label(
                subtitle,
                text=text,
                font=font,
                bg=bg,
                fg=muted,
            ).pack(side='left', anchor='w')

    def keyboard_guide_keycap_width(self, key: str) -> int:
        if self.input_mode.get() == 'bopomofo' and key not in {'Ctrl', 'Shift', '’', 'Space', 'Backspace'}:
            return 50
        return {'Ctrl': 82, 'Shift': 82, 'Space': 188, 'Backspace': 96, '-': 54}.get(key, max(44, 34 + (len(key) * 9)))

    def keyboard_guide_keycap_height(self, key: str) -> int:
        return 26 if key in {'Ctrl', 'Shift', '’', 'Space', 'Backspace'} else 52

    def keyboard_guide_row_width(self, row: list[str]) -> int:
        return sum(self.keyboard_guide_keycap_width(key) + 6 for key in row)

    def add_lomari_keyboard_inline_hint(self, parent, bg: str, muted: str, wraplength: int) -> None:
        hint_text = self.tr('lomari_shift_initials_hint')
        if normalize_lomari_key_style(self.lomari_key_style.get()) != LOMARI_KEY_STYLE_STANDARD:
            hint_text += '\n' + self.tr('lomari_key_style_hint_ir')
        tk.Label(
            parent,
            text=hint_text,
            font=self.ui_font_tuple(8),
            bg=bg,
            fg=muted,
            wraplength=wraplength,
            justify='left',
        ).place(relx=1.0, x=-2, rely=0.5, anchor='e')

    def show_clickable_keyboard_help(self, show_hangul_output: bool) -> None:
        bg = getattr(self, 'card_bg', '#ffffff')
        muted = '#5f6368'
        key_font = (self.lomari_font_family, 9, 'bold')
        value_font = (self.hangul_font_family, 12)

        keyboard = tk.Frame(self.keyboard_help_content, bg=bg)
        keyboard.pack(fill='both', expand=True, padx=12, pady=12)
        rows = self.keyboard_guide_rows()
        full_row_width = self.keyboard_guide_row_width(list('qwertyuiop'))
        for row_index, row in enumerate(rows):
            if self.input_mode.get() == 'lomari' and row_index == 0:
                row_container = tk.Frame(keyboard, bg=bg, width=full_row_width, height=52)
                row_container.pack(anchor='center', pady=(0, 6))
                row_container.pack_propagate(False)
                row_frame = tk.Frame(row_container, bg=bg)
                row_frame.place(relx=0.5, rely=0.5, anchor='center')
                hint_width = max(120, (full_row_width - self.keyboard_guide_row_width(row)) // 2 - 10)
                self.add_lomari_keyboard_inline_hint(row_container, bg, muted, hint_width)
            else:
                row_frame = tk.Frame(keyboard, bg=bg)
                row_frame.pack(anchor='center', pady=(0, 6) if row_index < len(rows) - 1 else (4, 0))
            for key in row:
                self.add_keyboard_guide_keycap(row_frame, key, key_font, value_font, show_hangul_output)

    def keyboard_guide_rows(self) -> list[list[str]]:
        if self.input_mode.get() == 'bopomofo':
            return [
                list('1234567890') + ['-'],
                list('qwertyuiop'),
                list('asdfghjkl;'),
                list('zxcvbnm,./'),
                ['Ctrl', 'Shift', 'Space', '’', 'Backspace'],
            ]
        top_row = ['1', '2', '4', '5']
        if self.input_mode.get() == 'lomari':
            top_row.append('-')
        return [
            top_row,
            list('qwertyuiop'),
            list('asdfghjkl'),
            list('zxcvbnm'),
            ['Shift', 'Space', '’', 'Backspace'],
        ]

    def keyboard_guide_key_sequence(self, key: str) -> str:
        if key in {'Ctrl', 'Shift', 'Space', 'Backspace'}:
            return ''
        if self.input_mode.get() == 'bopomofo':
            if self.keyboard_help_ctrled and key in BOPOMOFO_CTRL_PUNCTUATION:
                return BOPOMOFO_CTRL_PUNCTUATION[key]
            if self.keyboard_help_shifted and key in BOPOMOFO_SHIFTED_PUNCTUATION:
                return BOPOMOFO_SHIFTED_PUNCTUATION[key]
            shifted_key = key.upper()
            if self.keyboard_help_shifted and shifted_key in BOPOMOFO_SHIFT_VOWEL_KEYS:
                return shifted_key
            return key
        if self.input_mode.get() == 'lomari' and key == '-':
            return LOMARI_BOUNDARY_MARK
        if self.input_mode.get() == 'lomari' and self.keyboard_help_shifted:
            shifted_lomari = {
                'er': 'Er',
                'au': 'Au',
                'iau': 'Iau',
            }
            if key in shifted_lomari:
                return shifted_lomari[key]
            if len(key) == 1:
                return key.upper()
            return key
        if self.keyboard_help_shifted and len(key) == 1:
            return key.upper()
        return key

    def keyboard_guide_key_label(self, key: str) -> str:
        if self.input_mode.get() in {'lomari', 'bopomofo'} and key == '-':
            return '-詞'
        return key

    def keyboard_guide_lomari_output(self, key: str) -> tuple[str, bool]:
        """Return (label, bold) for one Lomari keycap output.

        In the unshifted guide, a key that types a complete ㅇ-initial vowel
        syllable is labelled with its corresponding standalone letter in bold.
        Example: e types 에, but the keycap displays bold ㅔ.  Activating Shift
        displays the actual standalone-letter output in the normal upright font.
        """
        sequence = self.keyboard_guide_key_sequence(key)
        if sequence in TONE_DIGITS:
            return {'1': 'ˆ', '2': 'ˋ', '4': 'ˊ', '5': 'ˉ'}.get(sequence, ''), False
        if sequence == LOMARI_BOUNDARY_MARK:
            return '', False
        output = convert_lomari_raw_to_hangul(
            sequence,
            lomari_key_style=self.lomari_key_style.get(),
        ).replace(INTERNAL_TONE_MARKS.get('3', ''), '')
        if not any(is_hangulish_for_tone(ch) for ch in output):
            return '', False

        return output, False

    def keyboard_guide_key_output(self, key: str, show_hangul_output: bool) -> str:
        if not show_hangul_output or key in {'Ctrl', 'Shift', 'Space', 'Backspace'}:
            return ''
        sequence = self.keyboard_guide_key_sequence(key)
        if self.input_mode.get() == 'bopomofo':
            if self.keyboard_help_ctrled and key in BOPOMOFO_CTRL_PUNCTUATION:
                return BOPOMOFO_CTRL_PUNCTUATION[key]
            if self.keyboard_help_shifted and key in BOPOMOFO_SHIFTED_PUNCTUATION:
                return BOPOMOFO_SHIFTED_PUNCTUATION[key]
            return BOPOMOFO_GUIDE_OUTPUTS.get(sequence, '')
        if self.input_mode.get() == 'lomari':
            return self.keyboard_guide_lomari_output(key)[0]
        if len(sequence) == 1:
            if sequence in TONE_DIGITS:
                return {'1': 'ˆ', '2': 'ˋ', '4': 'ˊ', '5': 'ˉ'}.get(sequence, '')
            output = KEY_TO_JAMO.get(normalize_keyboard_char(sequence), '')
            if output in SPECIAL_MEDIALS:
                return '\u115F' + output
            return output
        return ''

    def keyboard_guide_repaint_keycap(self, widget, color: str, border: str | None = None) -> None:
        try:
            widget.configure(bg=color)
            if border is not None and hasattr(widget, 'configure'):
                widget.configure(highlightbackground=border)
        except tk.TclError:
            pass
        for child in getattr(widget, 'winfo_children', lambda: [])():
            self.keyboard_guide_repaint_keycap(child, color)

    def apply_keyboard_guide_keycap_state(self, key: str) -> None:
        item = self.keyboard_guide_keycaps.get(key)
        if not item:
            return
        cap = item.get('cap')
        fill = item.get('fill', '#ffffff')
        hover = bool(item.get('hover'))
        pressed = key in self.keyboard_guide_pressed_keys
        if pressed:
            color = '#d2e3fc'
            border = '#1a73e8'
        elif hover:
            active_modifier = (
                (key == 'Shift' and self.keyboard_help_shifted)
                or (key == 'Ctrl' and self.keyboard_help_ctrled)
            )
            color = '#f8fbff' if not active_modifier else '#d2e3fc'
            border = '#dadce0'
        else:
            color = fill
            border = '#dadce0'
        self.keyboard_guide_repaint_keycap(cap, color, border)

    def keyboard_guide_key_from_event(self, event: tk.Event) -> str | None:
        key = str(getattr(event, 'keysym', '') or '')
        char = str(getattr(event, 'char', '') or '')
        if self.input_mode.get() == 'bopomofo' and key in {'Control_L', 'Control_R'}:
            return 'Ctrl'
        if key in {'Shift_L', 'Shift_R'}:
            return 'Shift'
        if key == 'space' or char == ' ':
            return 'Space'
        if key == 'BackSpace':
            return 'Backspace'
        if self.input_mode.get() == 'bopomofo':
            shifted_punctuation = BOPOMOFO_SHIFTED_PUNCTUATION_TO_KEY.get(char)
            if shifted_punctuation:
                return shifted_punctuation
        if key.startswith('KP_') and key[3:] in {'1', '2', '4', '5'}:
            return key[3:]
        if self.input_mode.get() == 'bopomofo' and key.startswith('KP_') and key[3:] in set('0123456789'):
            return key[3:]
        if char == '-' or key in {'minus', 'hyphen'}:
            return '-'
        if char in {"'", '’', '‘'} or key in {'apostrophe', 'quoteright'}:
            return '’'
        if len(char) == 1:
            lowered = char.lower()
            if self.input_mode.get() == 'bopomofo' and lowered in BOPOMOFO_KEYS:
                return lowered
            if lowered in set('qwertyuiopasdfghjklzxcvbnm1245-'):
                return lowered
        if len(key) == 1:
            lowered = key.lower()
            if self.input_mode.get() == 'bopomofo' and lowered in BOPOMOFO_KEYS:
                return lowered
            if lowered in set('qwertyuiopasdfghjklzxcvbnm1245-'):
                return lowered
        return None

    def set_keyboard_guide_physical_key_pressed(self, key: str | None, pressed: bool) -> None:
        if not key:
            return
        if pressed:
            self.keyboard_guide_pressed_keys.add(key)
        else:
            self.keyboard_guide_pressed_keys.discard(key)
        self.apply_keyboard_guide_keycap_state(key)

    def set_keyboard_guide_shifted(self, shifted: bool) -> None:
        if self.keyboard_help_shifted == shifted:
            return
        self.keyboard_help_shifted = shifted
        self.refresh_keyboard_guide_keycaps_for_shift()

    def set_keyboard_guide_ctrled(self, ctrled: bool) -> None:
        if self.keyboard_help_ctrled == ctrled:
            return
        self.keyboard_help_ctrled = ctrled
        self.refresh_keyboard_guide_keycaps_for_ctrl()

    def on_keyboard_guide_keyrelease(self, event: tk.Event) -> None:
        key = self.keyboard_guide_key_from_event(event)
        self.set_keyboard_guide_physical_key_pressed(key, False)
        if key == 'Shift':
            self.set_keyboard_guide_shifted(False)
        if key == 'Ctrl':
            self.set_keyboard_guide_ctrled(False)

    def clear_keyboard_guide_physical_keys(self, _event: tk.Event | None = None) -> None:
        pressed = list(self.keyboard_guide_pressed_keys)
        self.keyboard_guide_pressed_keys.clear()
        for key in pressed:
            self.apply_keyboard_guide_keycap_state(key)

    def keyboard_guide_keycap_fill(self, key: str) -> str:
        return '#e8f0fe' if (
            (key == 'Shift' and self.keyboard_help_shifted)
            or (key == 'Ctrl' and self.keyboard_help_ctrled)
        ) else '#ffffff'

    def populate_keyboard_guide_keycap_content(
        self,
        cap,
        key: str,
        key_font,
        value_font,
        show_hangul_output: bool,
        fill: str,
    ) -> None:
        is_control = key in {'Ctrl', 'Shift', 'Space', 'Backspace'}
        bopomofo_shifted_punctuation = (
            self.input_mode.get() == 'bopomofo'
            and self.keyboard_help_shifted
            and key in BOPOMOFO_SHIFTED_PUNCTUATION
        )
        bopomofo_ctrl_punctuation = (
            self.input_mode.get() == 'bopomofo'
            and self.keyboard_help_ctrled
            and key in BOPOMOFO_CTRL_PUNCTUATION
        )
        is_center_key = (
            is_control
            or key == '’'
            or (
                self.input_mode.get() in {'lomari', 'bopomofo'}
                and key == '-'
                and not bopomofo_shifted_punctuation
            )
        )
        width = self.keyboard_guide_keycap_width(key)
        guide_muted = '#9aa0a6'

        if self.input_mode.get() in {'lomari', 'bopomofo'} and key == '-' and not bopomofo_shifted_punctuation:
            canvas = tk.Canvas(cap, bg=fill, highlightthickness=0, bd=0)
            canvas.pack(fill='both', expand=True)
            if self.input_mode.get() == 'bopomofo':
                canvas.create_text(8, 8, text='-', font=key_font, fill=guide_muted, anchor='nw')
            else:
                canvas.create_text(width // 2, 11, text='-', font=key_font, fill=guide_muted)
            canvas.create_text(width // 2, 33, text='-詞', font=(self.hanri_font_family, 9, 'bold'), fill=guide_muted)
            return

        if self.input_mode.get() == 'bopomofo' and not is_control and key != '’':
            canvas = tk.Canvas(cap, bg=fill, highlightthickness=0, bd=0)
            canvas.pack(fill='both', expand=True)
            char = self.keyboard_guide_key_sequence(key)
            output = self.keyboard_guide_key_output(key, show_hangul_output)
            bopomofo_symbol = BOPOMOFO_GUIDE_SYMBOLS.get(key, '')
            output_font = self.tone_font if char in BOPOMOFO_TONE_KEYS else value_font
            canvas.create_text(8, 8, text=key, font=key_font, fill=guide_muted, anchor='nw')
            canvas.create_text(
                width - 8,
                8,
                text=bopomofo_symbol,
                font=(self.hanri_font_family, 9, 'bold'),
                fill=guide_muted,
                anchor='ne',
            )
            canvas.create_text(width // 2, 35, text=output, font=output_font, fill='#202124')
            return

        if is_center_key:
            label = tk.Label(cap, text=self.keyboard_guide_key_label(key), font=key_font, bg=fill, fg='#202124')
            label.pack(fill='both', expand=True)
            return

        char = self.keyboard_guide_key_sequence(key)
        output = self.keyboard_guide_key_output(key, show_hangul_output)
        key_font_to_use = (
            (self.lomari_font_family, 9, 'bold italic')
            if self.input_mode.get() == 'lomari' and key in LOMARI_GUIDE_NON_ROMAN_KEYS
            else key_font
        )
        output_is_bold = bool(
            show_hangul_output
            and self.input_mode.get() == 'lomari'
            and self.keyboard_guide_lomari_output(key)[1]
        )
        canvas = tk.Canvas(cap, bg=fill, highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        if output and char in TONE_DIGITS:
            canvas.create_text(width // 2, 12, text=char, font=key_font_to_use, fill=guide_muted)
            canvas.create_text(width // 2, 35, text=output, font=self.tone_font, fill='#202124')
            return

        value_text = output if output else ('' if show_hangul_output else char)
        if output_is_bold:
            value_font_to_use = (self.hangul_font_family, 12, 'bold')
        else:
            value_font_to_use = value_font if output else (self.lomari_font_family, 12)
        value_fill = '#202124'
        canvas.create_text(width // 2, 11, text=char, font=key_font_to_use, fill=guide_muted)
        canvas.create_text(width // 2, 34, text=value_text, font=value_font_to_use, fill=value_fill)

    def bind_keyboard_guide_keycap_events(self, cap, key: str) -> None:
        def on_enter(_event) -> None:
            item = self.keyboard_guide_keycaps.get(key)
            if item is not None:
                item['hover'] = True
            self.apply_keyboard_guide_keycap_state(key)

        def on_leave(_event) -> None:
            item = self.keyboard_guide_keycaps.get(key)
            if item is not None:
                item['hover'] = False
            self.apply_keyboard_guide_keycap_state(key)

        def on_press(_event) -> None:
            self.set_keyboard_guide_physical_key_pressed(key, True)

        def on_click(_event) -> None:
            self.set_keyboard_guide_physical_key_pressed(key, False)
            if key == 'Shift':
                self.toggle_keyboard_guide_shift()
            elif key == 'Ctrl':
                self.toggle_keyboard_guide_ctrl()
            elif key == 'Space':
                self.press_keyboard_guide_char(' ')
            elif key == 'Backspace':
                self.press_keyboard_guide_backspace()
            else:
                self.press_keyboard_guide_sequence(self.keyboard_guide_key_sequence(key))

        for widget in [cap, *cap.winfo_children()]:
            widget.bind('<Enter>', on_enter)
            widget.bind('<Leave>', on_leave)
            widget.bind('<ButtonPress-1>', on_press)
            widget.bind('<ButtonRelease-1>', on_click)

    def add_keyboard_guide_keycap(self, parent, key: str, key_font, value_font, show_hangul_output: bool) -> None:
        width = self.keyboard_guide_keycap_width(key)
        height = self.keyboard_guide_keycap_height(key)
        fill = self.keyboard_guide_keycap_fill(key)
        cap = tk.Frame(parent, bg=fill, highlightthickness=1, highlightbackground='#dadce0', width=width, height=height)
        cap.pack(side='left', padx=3)
        cap.pack_propagate(False)
        cap.configure(cursor='hand2')

        self.keyboard_guide_keycaps[key] = {
            'cap': cap,
            'fill': fill,
            'hover': False,
            'key_font': key_font,
            'value_font': value_font,
            'show_hangul_output': show_hangul_output,
        }
        self.populate_keyboard_guide_keycap_content(cap, key, key_font, value_font, show_hangul_output, fill)
        self.bind_keyboard_guide_keycap_events(cap, key)
        self.apply_keyboard_guide_keycap_state(key)

    def refresh_keyboard_guide_keycap(self, key: str) -> None:
        item = self.keyboard_guide_keycaps.get(key)
        if not item:
            return
        cap = item.get('cap')
        if cap is None:
            return
        fill = self.keyboard_guide_keycap_fill(key)
        item['fill'] = fill
        try:
            cap.configure(bg=fill)
            for child in cap.winfo_children():
                child.destroy()
        except tk.TclError:
            return
        self.populate_keyboard_guide_keycap_content(
            cap,
            key,
            item.get('key_font', (self.lomari_font_family, 9, 'bold')),
            item.get('value_font', (self.hangul_font_family, 12)),
            bool(item.get('show_hangul_output', True)),
            fill,
        )
        self.bind_keyboard_guide_keycap_events(cap, key)
        self.apply_keyboard_guide_keycap_state(key)

    def refresh_keyboard_guide_keycaps_for_shift(self) -> None:
        for key in list(self.keyboard_guide_keycaps):
            if key == 'Shift' or (len(key) == 1 and key.isalpha()) or key in BOPOMOFO_SHIFTED_PUNCTUATION:
                self.refresh_keyboard_guide_keycap(key)

    def refresh_keyboard_guide_keycaps_for_ctrl(self) -> None:
        for key in list(self.keyboard_guide_keycaps):
            if key == 'Ctrl' or key in BOPOMOFO_CTRL_PUNCTUATION:
                self.refresh_keyboard_guide_keycap(key)

    def toggle_keyboard_guide_shift(self) -> None:
        self.set_keyboard_guide_shifted(not self.keyboard_help_shifted)

    def toggle_keyboard_guide_ctrl(self) -> None:
        self.set_keyboard_guide_ctrled(not self.keyboard_help_ctrled)

    def press_keyboard_guide_char(self, char: str) -> None:
        self.press_keyboard_guide_sequence(char)

    def press_keyboard_guide_sequence(self, sequence: str) -> None:
        if not sequence:
            return
        was_shifted = self.keyboard_help_shifted
        was_ctrled = self.keyboard_help_ctrled
        replacing_selection = self.selected_offsets() is not None
        self.close_candidate_popup()
        if replacing_selection:
            self.push_undo_state()
            self.delete_selection_if_any(push_undo=False)
        else:
            self.push_undo_state()
        for char in sequence:
            char = self.normalize_apostrophe_input(char)
            if not self.ime_on.get():
                self.key_history = []
                self.reset_lomari_buffer()
                self.composer.insert_literal(char)
            elif self.input_mode.get() == 'lomari':
                self.key_history = []
                self.process_lomari_mode_char(char)
            elif self.input_mode.get() == 'bopomofo':
                self.key_history = []
                self.reset_lomari_buffer()
                if was_ctrled and char in BOPOMOFO_CTRL_PUNCTUATION.values():
                    self.reset_bopomofo_boundary()
                    self.composer.insert_literal(char)
                else:
                    self.process_bopomofo_mode_char(char)
            else:
                self.reset_lomari_buffer()
                self.process_hokkien_sequence_or_standard(char)
                if char in TONE_DIGITS:
                    self.apply_tone_digit_display_to_latest_input(char)
        self.keyboard_help_shifted = False
        self.keyboard_help_ctrled = False
        self.render()
        if was_shifted and self.keyboard_help_open:
            self.refresh_keyboard_guide_keycaps_for_shift()
        if was_ctrled and self.keyboard_help_open:
            self.refresh_keyboard_guide_keycaps_for_ctrl()
        self.maybe_show_hanri_candidates()
        self.text.focus_set()

    def press_keyboard_guide_backspace(self) -> None:
        self.close_candidate_popup()
        was_shifted = self.keyboard_help_shifted
        was_ctrled = self.keyboard_help_ctrled
        replacing_selection = self.selected_offsets() is not None
        self.push_undo_state()
        if replacing_selection:
            self.delete_selection_if_any(push_undo=False)
        elif self.input_mode.get() == 'lomari' and self.backspace_lomari_mode():
            pass
        else:
            self.reset_lomari_buffer()
            backspace_info = self.composer.backspace()
            self.prepare_special_backspace_reinflate(backspace_info)
        self.key_history = []
        self.keyboard_help_shifted = False
        self.keyboard_help_ctrled = False
        self.render()
        if was_shifted and self.keyboard_help_open:
            self.refresh_keyboard_guide_keycaps_for_shift()
        if was_ctrled and self.keyboard_help_open:
            self.refresh_keyboard_guide_keycaps_for_ctrl()
        self.maybe_show_hanri_candidates()
        self.text.focus_set()

    def add_lomari_guide_table(
        self,
        parent,
        column: int,
        heading: str,
        rows: list[tuple[str, str]],
        key_font,
        value_font,
        header_font,
        bg: str,
    ) -> None:
        frame = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground='#dadce0')
        frame.grid(row=0, column=column, sticky='nsew', padx=(0, 8) if column == 0 else (8, 0))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        heading_label = tk.Label(frame, text=heading, font=header_font, bg='#f1f3f4', fg='#202124', anchor='w')
        heading_label.grid(row=0, column=0, columnspan=2, sticky='ew', padx=0, pady=0, ipady=5)

        for row_index, (keys, output) in enumerate(rows, start=1):
            row_bg = '#ffffff' if row_index % 2 else '#f8fafd'
            left_font = value_font if any(ch in keys for ch in {'ㆆ', 'ㅇ'}) else key_font
            left = tk.Label(frame, text=keys, font=left_font, bg=row_bg, fg='#202124', anchor='w', padx=8, pady=5)
            right = tk.Label(frame, text=output, font=value_font, bg=row_bg, fg='#202124', anchor='w', padx=8, pady=5)
            left.grid(row=row_index, column=0, sticky='ew')
            right.grid(row=row_index, column=1, sticky='ew')

    def toggle_keyboard_help(self) -> None:
        """Open/close the keyboard guide."""
        if self.keyboard_help_panel is None:
            self.build_keyboard_help_panel()
        if self.keyboard_help_panel is None:
            return

        if self.keyboard_help_open:
            self.close_keyboard_help_panel()
            return

        self.keyboard_help_open = True
        self.show_keyboard_help_for_current_window_state(refresh=True)
        if self.keyboard_help_button is not None:
            self.keyboard_help_button.configure(text=self.keyboard_help_button_label())

    def select_all_roman_preview(self, event: tk.Event | None = None) -> str:
        if not hasattr(self, 'roman_preview'):
            return 'break'
        try:
            self.roman_preview.tag_add('sel', '1.0', 'end-1c')
            self.roman_preview.mark_set('insert', 'end-1c')
            self.roman_preview.focus_set()
        except tk.TclError:
            pass
        return 'break'

    def on_roman_preview_keypress(self, event: tk.Event) -> str | None:
        # The Lomari preview should be selectable/copyable, but not editable.
        if (event.state & 0x4) and event.keysym.lower() in {'c', 'a'}:
            return None
        return 'break'

    def keep_text_cursor_steady_while_typing(self) -> None:
        """Keep the insertion cursor visible and non-blinking during active typing."""
        if not hasattr(self, 'text'):
            return
        if self.text_cursor_steady_after_id is not None:
            try:
                self.root.after_cancel(self.text_cursor_steady_after_id)
            except tk.TclError:
                pass
            self.text_cursor_steady_after_id = None
        try:
            self.text.configure(
                insertbackground=TEXT_CURSOR_COLOR,
                insertwidth=TEXT_CURSOR_WIDTH,
                insertontime=0,
                insertofftime=0,
            )
        except tk.TclError:
            return
        self.text_cursor_steady_after_id = self.root.after(
            TEXT_CURSOR_TYPING_STEADY_MS,
            self.restore_text_cursor_blink,
        )

    def restore_text_cursor_blink(self) -> None:
        self.text_cursor_steady_after_id = None
        if not hasattr(self, 'text'):
            return
        try:
            self.text.configure(
                insertbackground=TEXT_CURSOR_COLOR,
                insertwidth=TEXT_CURSOR_WIDTH,
                insertontime=TEXT_CURSOR_BLINK_ON_MS,
                insertofftime=TEXT_CURSOR_BLINK_OFF_MS,
            )
        except tk.TclError:
            pass

    def update_roman_preview(self, content: str) -> None:
        """Debounce the expensive Lomari preview update during fast typing."""
        if not hasattr(self, 'roman_preview'):
            return
        self.roman_preview_pending_content = content
        if self.roman_preview_after_id is not None:
            try:
                self.root.after_cancel(self.roman_preview_after_id)
            except tk.TclError:
                pass
            self.roman_preview_after_id = None
        self.roman_preview_after_id = self.root.after(
            ROMAN_PREVIEW_DEBOUNCE_MS,
            self.flush_roman_preview_update,
        )

    def flush_roman_preview_update(self) -> None:
        if not hasattr(self, 'roman_preview'):
            return
        self.roman_preview_after_id = None
        content = self.roman_preview_pending_content
        if content == self.roman_preview_rendered_content:
            return
        preview_source = self.text_with_hanri_instance_readings(content)
        preview = visible_text_to_lomari(preview_source)
        if preview == self.roman_preview_rendered_text:
            self.roman_preview_rendered_content = content
            return
        preview_line_count = preview.count('\n') + 1 if preview else ROMAN_PREVIEW_MIN_LINES
        preview_height = max(
            ROMAN_PREVIEW_MIN_LINES,
            min(ROMAN_PREVIEW_MAX_LINES, preview_line_count),
        )
        self.roman_preview.configure(state='normal')
        if hasattr(self, 'roman_preview_frame'):
            self.roman_preview_frame.configure(
                height=(getattr(self, 'roman_preview_line_height', 18) * preview_height) + 8
            )
        self.roman_preview.configure(height=preview_height)
        self.roman_preview.delete('1.0', 'end')
        self.roman_preview.insert('1.0', preview)
        self.roman_preview.mark_set('insert', 'end-1c')
        self.roman_preview.see('end-1c')
        self.roman_preview.yview_moveto(1.0)
        self.roman_preview_rendered_content = content
        self.roman_preview_rendered_text = preview

    def _bind_keys(self) -> None:
        # Exact Alt+digit bindings are kept separate from the generic KeyPress
        # handler.  This prevents normal digit keypresses from being mistaken
        # for literal Arabic numerals on Windows/Tk builds where modifier state
        # bits can be noisy.  Normal Hangul+1/2/3/4/5 therefore remains tone
        # input; Alt+digit alone inserts a pronounceable literal number.
        for digit in ARABIC_NUMERAL_DIGITS:
            self.text.bind(f'<Alt-KeyPress-{digit}>', self.on_alt_digit_keypress)
            self.text.bind(f'<Alt-KeyPress-KP_{digit}>', self.on_alt_digit_keypress)
        self.text.bind('<KeyPress>', self.on_keypress)
        self.text.bind('<KeyRelease>', self.on_keyboard_guide_keyrelease)
        self.text.bind('<FocusOut>', self.clear_keyboard_guide_physical_keys)
        self.text.bind('<ButtonPress-1>', self.on_mouse_press)
        self.text.bind('<B1-Motion>', self.on_mouse_drag_select)
        self.text.bind('<ButtonRelease-1>', self.on_mouse_release)
        self.text.bind('<<Paste>>', lambda event: self.paste_raw_clipboard())
        self.text.bind('<<Cut>>', lambda event: self.cut_selection())
        self.text.bind('<Control-a>', self.select_all_main_text)
        self.text.bind('<Control-A>', self.select_all_main_text)
        self.text.bind('<Control-c>', self.copy_selection_or_all)
        self.text.bind('<Control-C>', self.copy_selection_or_all)
        self.text.bind('<<Copy>>', self.copy_selection_or_all)
        self.text.bind('<Control-v>', lambda event: self.paste_raw_clipboard())
        self.text.bind('<Control-V>', lambda event: self.paste_raw_clipboard())
        self.text.bind('<Control-x>', lambda event: self.cut_selection())
        self.text.bind('<Control-X>', lambda event: self.cut_selection())
        self.text.bind('<Control-z>', lambda event: self.undo_last_action())
        self.text.bind('<Control-Z>', lambda event: self.undo_last_action())
        self.text.bind('<Control-y>', lambda event: self.redo_last_action())
        self.text.bind('<Control-Y>', lambda event: self.redo_last_action())
        self.root.bind('<F6>', lambda event: self.copy_text())
        self.root.bind('<F7>', lambda event: self.clear())
        self.root.bind('<F8>', lambda event: self.toggle_hanri())
        self.root.bind('<F9>', lambda event: self.play_recorded_audio())
        self.root.bind('<Control-space>', lambda event: self.toggle_ime())
        self.root.bind('<Unmap>', self.on_root_unmap)
        self.root.bind('<Configure>', self.on_root_configure)

    def sync_hanri_instance_readings(self) -> None:
        """Keep remembered per-instance Hanri readings aligned with current text."""
        if not hasattr(self, 'hanri_instance_readings'):
            self.hanri_instance_readings = []
            self.hanri_instance_text_snapshot = self.composer.text()
            return

        current = self.composer.text()
        old = getattr(self, 'hanri_instance_text_snapshot', '')
        spans = list(getattr(self, 'hanri_instance_readings', []) or [])
        if old == current:
            return
        if not spans:
            self.hanri_instance_text_snapshot = current
            return

        matcher = difflib.SequenceMatcher(None, old, current, autojunk=False)
        updated: list[dict] = []
        for span in spans:
            try:
                start = int(span.get('start', -1))
                end = int(span.get('end', -1))
            except Exception:
                continue
            hanri = str(span.get('hanri', '') or '')
            reading = str(span.get('reading', '') or '')
            if start < 0 or end <= start or not hanri or not reading:
                continue

            new_start = new_end = None
            for block in matcher.get_matching_blocks():
                if block.size <= 0:
                    continue
                block_a_end = block.a + block.size
                if block.a <= start and end <= block_a_end:
                    new_start = block.b + (start - block.a)
                    new_end = block.b + (end - block.a)
                    break
            if new_start is None or new_end is None:
                continue
            if current[new_start:new_end] != hanri:
                continue
            updated.append({
                'start': new_start,
                'end': new_end,
                'hanri': hanri,
                'reading': reading,
                'auto_sandhi': bool(span.get('auto_sandhi')),
            })

        self.hanri_instance_readings = sorted(updated, key=lambda item: (item['start'], item['end']))
        self.hanri_instance_text_snapshot = current

    def remember_hanri_instance_reading(self, start: int, hanri: str, reading: str, auto_sandhi: bool = False) -> None:
        """Remember the exact reading used for this visible Hanri span."""
        hanri = str(hanri or '')
        reading = normalize_tone_symbols_to_digits(str(reading or ''))
        if not field_is_plain_hanri(hanri) or not reading:
            return
        self.sync_hanri_instance_readings()
        end = start + len(hanri)
        current = self.composer.text()
        if current[start:end] != hanri:
            return
        self.hanri_instance_readings = [
            item for item in self.hanri_instance_readings
            if int(item.get('end', -1)) <= start or int(item.get('start', -1)) >= end
        ]
        self.hanri_instance_readings.append({
            'start': start,
            'end': end,
            'hanri': hanri,
            'reading': reading,
            'auto_sandhi': bool(auto_sandhi),
        })
        self.hanri_instance_readings.sort(key=lambda item: (item['start'], item['end']))
        self.hanri_instance_text_snapshot = current

    def text_with_hanri_instance_readings(self, text: str | None = None) -> str:
        """Inject hidden [HanriReading] annotations for remembered instances."""
        self.sync_hanri_instance_readings()
        source = self.composer.text() if text is None else str(text)
        bracket_ranges: list[tuple[int, int]] = []
        search_pos = 0
        while search_pos < len(source):
            start_bracket = source.find('[', search_pos)
            if start_bracket == -1:
                break
            end_bracket = source.find(']', start_bracket + 1)
            if end_bracket == -1:
                break
            bracket_ranges.append((start_bracket, end_bracket + 1))
            search_pos = end_bracket + 1

        def overlaps_bracket(start: int, end: int) -> bool:
            return any(start < bracket_end and bracket_start < end for bracket_start, bracket_end in bracket_ranges)

        spans = []
        for item in self.hanri_instance_readings:
            start = int(item.get('start', -1))
            end = int(item.get('end', -1))
            hanri = str(item.get('hanri', '') or '')
            reading = str(item.get('reading', '') or '')
            auto_sandhi = bool(item.get('auto_sandhi'))
            if start < 0 or end <= start or source[start:end] != hanri or not reading:
                continue
            if overlaps_bracket(start, end):
                continue
            if (not auto_sandhi) and is_reading_followed_by_connected_text(source, end - 1):
                reading = citation_to_sandhi_reading(reading) or reading
            spans.append((start, end, hanri, reading))

        if not spans:
            return source

        out: list[str] = []
        pos = 0
        for start, end, hanri, reading in sorted(spans):
            if start < pos:
                continue
            out.append(source[pos:start])
            out.append(f'[{hanri}{reading}]')
            pos = end
        out.append(source[pos:])
        return ''.join(out)

    def composer_state_snapshot(self) -> tuple:
        """Return a restorable snapshot for Ctrl+Z."""
        self.sync_hanri_instance_readings()
        return (
            self.composer.output,
            self.composer.cursor_pos,
            self.composer.initial,
            self.composer.medial,
            self.composer.final,
            [dict(item) for item in self.hanri_instance_readings],
            self.hanri_instance_text_snapshot,
        )

    def push_undo_state(self) -> None:
        """Save the current IME buffer state before a user-visible edit."""
        snapshot = self.composer_state_snapshot()
        if self.undo_stack and self.undo_stack[-1] == snapshot:
            return
        self.undo_stack.append(snapshot)
        self.redo_stack = []
        if len(self.undo_stack) > 200:
            self.undo_stack = self.undo_stack[-200:]

    def restore_undo_state(self, snapshot: tuple) -> None:
        if len(snapshot) >= 7:
            (
                self.composer.output,
                self.composer.cursor_pos,
                self.composer.initial,
                self.composer.medial,
                self.composer.final,
                instance_readings,
                instance_snapshot,
            ) = snapshot[:7]
            self.hanri_instance_readings = [dict(item) for item in instance_readings]
            self.hanri_instance_text_snapshot = str(instance_snapshot)
        else:
            self.composer.output, self.composer.cursor_pos, self.composer.initial, self.composer.medial, self.composer.final = snapshot[:5]
            self.hanri_instance_readings = []
            self.hanri_instance_text_snapshot = self.composer.output
        self.composer.clamp_cursor()
        self.key_history = []
        self.reset_lomari_buffer()
        self.close_candidate_popup()

    def undo_last_action(self) -> str:
        """Undo the latest IME edit and make it redoable with Ctrl+Y."""
        if not self.undo_stack:
            self.text.focus_set()
            return 'break'
        current = self.composer_state_snapshot()
        snapshot = self.undo_stack.pop()
        if current != snapshot:
            self.redo_stack.append(current)
            if len(self.redo_stack) > 200:
                self.redo_stack = self.redo_stack[-200:]
        self.restore_undo_state(snapshot)
        self.render()
        self.maybe_show_hanri_candidates()
        self.text.focus_set()
        return 'break'

    def redo_last_action(self) -> str:
        """Redo the latest Ctrl+Z action."""
        if not self.redo_stack:
            self.text.focus_set()
            return 'break'
        current = self.composer_state_snapshot()
        snapshot = self.redo_stack.pop()
        if current != snapshot:
            self.undo_stack.append(current)
            if len(self.undo_stack) > 200:
                self.undo_stack = self.undo_stack[-200:]
        self.restore_undo_state(snapshot)
        self.render()
        self.maybe_show_hanri_candidates()
        self.text.focus_set()
        return 'break'

    def text_index_to_offset(self, index: str) -> int:
        """Convert a Tk Text index to a zero-based character offset."""
        try:
            return len(self.text.get('1.0', index))
        except tk.TclError:
            return self.composer.display_cursor_pos()

    def offset_to_text_index(self, offset: int) -> str:
        """Convert a zero-based character offset into a Tk Text index."""
        return f'1.0+{max(0, int(offset))}c'

    def expand_atomic_selection_offsets(
        self,
        start: int,
        end: int,
        content: str | None = None,
    ) -> tuple[int, int]:
        """Expand selection edges so jamo clusters are selected as whole units."""
        text = self.composer.text() if content is None else str(content)
        length = len(text)
        start = max(0, min(int(start), length))
        end = max(0, min(int(end), length))
        if end < start:
            start, end = end, start

        start_bounds = atomic_hangul_cluster_bounds_at(text, start)
        if start_bounds is not None:
            start = start_bounds[0]

        end_bounds = atomic_hangul_cluster_bounds_at(text, end)
        if end_bounds is not None:
            end = end_bounds[1]

        return start, end

    def normalize_atomic_text_selection(self) -> tuple[int, int] | None:
        """Snap the visible Tk selection tag to atomic jamo-cluster boundaries."""
        try:
            start_index = self.text.index('sel.first')
            end_index = self.text.index('sel.last')
        except tk.TclError:
            return None

        content = self.text.get('1.0', 'end-1c')
        start = self.text_index_to_offset(start_index)
        end = self.text_index_to_offset(end_index)
        start, end = self.expand_atomic_selection_offsets(start, end, content)
        if end <= start:
            try:
                self.text.tag_remove('sel', '1.0', 'end')
            except tk.TclError:
                pass
            return None

        snapped_start_index = self.offset_to_text_index(start)
        snapped_end_index = self.offset_to_text_index(end)
        if start_index != snapped_start_index or end_index != snapped_end_index:
            try:
                self.text.tag_remove('sel', '1.0', 'end')
                self.text.tag_add('sel', snapped_start_index, snapped_end_index)
            except tk.TclError:
                pass
        return start, end

    def selected_offsets(self) -> tuple[int, int] | None:
        """Return selected text offsets, or None if there is no active selection."""
        try:
            start_index = self.text.index('sel.first')
            end_index = self.text.index('sel.last')
        except tk.TclError:
            return None

        start = self.text_index_to_offset(start_index)
        end = self.text_index_to_offset(end_index)
        start, end = self.expand_atomic_selection_offsets(start, end, self.text.get('1.0', 'end-1c'))
        if end <= start:
            return None
        return start, end

    def select_all_main_text(self, event: tk.Event | None = None) -> str:
        """Select only real text characters in the main IME pad.

        Tk Text's default Ctrl+A can include the trailing phantom newline on
        some platforms.  Selecting end-1c keeps the copied content clean.
        """
        self.close_candidate_popup()
        self.flush_sequence_buffer()
        self.reset_lomari_buffer()
        self.composer.commit()
        self.render()
        try:
            self.text.tag_remove('sel', '1.0', 'end')
            self.text.tag_add('sel', '1.0', 'end-1c')
            self.text.mark_set('insert', 'end-1c')
            self.text.focus_set()
        except tk.TclError:
            pass
        return 'break'

    def clipboard_plain_text(self, content: str) -> str:
        """Return clean clipboard text with no IME-only invisible markers."""
        return format_text_tones_for_output(
            str(content).replace(LITERAL_DIGIT_MARK, ''),
            self.output_tones_on.get(),
        ).replace(LITERAL_DIGIT_MARK, '')

    def set_windows_clipboard_unicode_text(self, text: str) -> bool:
        """Set the Windows clipboard directly as CF_UNICODETEXT.

        Shelling out to PowerShell/clip can leave the clipboard momentarily
        unavailable, which made some external apps need Ctrl+V twice.  The
        Win32 clipboard API is synchronous and leaves real OS-owned Unicode
        text behind, so paste works immediately and still survives after the
        IME window closes.
        """
        if not sys.platform.startswith('win'):
            return False

        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return False

        try:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            GMEM_ZEROINIT = 0x0040

            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            user32.SetClipboardData.restype = wintypes.HANDLE
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL

            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalFree.restype = wintypes.HGLOBAL

            # CF_UNICODETEXT convention expects CRLF line endings and a final
            # UTF-16 NUL.
            normalized = str(text).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
            data = normalized.encode('utf-16le') + b'\x00\x00'

            if not user32.OpenClipboard(None):
                return False

            handle = None
            try:
                if not user32.EmptyClipboard():
                    return False

                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
                if not handle:
                    return False

                locked = kernel32.GlobalLock(handle)
                if not locked:
                    kernel32.GlobalFree(handle)
                    handle = None
                    return False

                ctypes.memmove(locked, data, len(data))
                kernel32.GlobalUnlock(handle)

                if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    kernel32.GlobalFree(handle)
                    handle = None
                    return False

                # Ownership of handle transfers to the clipboard on success.
                handle = None
                return True
            finally:
                user32.CloseClipboard()
                if handle:
                    kernel32.GlobalFree(handle)
        except Exception:
            return False

    def set_system_clipboard_text(self, content: str) -> None:
        """Put clean plain text on the system clipboard.

        Tk keeps in-app paste working.  On Windows, a direct Win32 clipboard
        write is used afterwards so other apps can paste on the first Ctrl+V
        and the clipboard still survives after closing the IME.
        """
        text = str(content)
        self.last_clipboard_plain_text = text

        # First update Tk's clipboard for immediate in-app Ctrl+C -> Ctrl+V.
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
        except tk.TclError:
            pass

        try:
            if sys.platform.startswith('win'):
                self.set_windows_clipboard_unicode_text(text)
            elif sys.platform == 'darwin':
                subprocess.run(['pbcopy'], input=text, text=True, encoding='utf-8', timeout=3, check=False)
            else:
                for command in (['wl-copy'], ['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']):
                    try:
                        subprocess.run(command, input=text, text=True, encoding='utf-8', timeout=3, check=False)
                        break
                    except Exception:
                        continue
        except Exception:
            # Tk clipboard above is still a valid fallback.
            pass

    def copy_selection_or_all(self, event: tk.Event | None = None) -> str:
        """Copy selected main-text content as plain text; if none, copy all."""
        offsets = self.normalize_atomic_text_selection()
        selected = None
        if offsets is not None:
            start, end = offsets
            selected = self.text.get('1.0', 'end-1c')[start:end]

        self.close_candidate_popup()
        self.flush_sequence_buffer()
        self.reset_lomari_buffer()

        if selected is None:
            self.composer.commit()
            selected = self.composer.text()
            self.render()

        content = self.clipboard_plain_text(selected)
        self.set_system_clipboard_text(content)
        self.status.configure(text=self.tr('copied'))
        self.text.focus_set()
        return 'break'

    def delete_selection_if_any(self, push_undo: bool = True) -> bool:
        """Delete the selected text from the composer/output, if any."""
        offsets = self.selected_offsets()
        if offsets is None:
            return False

        start, end = offsets
        content = self.text.get('1.0', 'end-1c')
        if push_undo:
            self.push_undo_state()
        self.composer.output = content[:start] + content[end:]
        self.composer.cursor_pos = start
        self.composer.initial = self.composer.medial = self.composer.final = ''
        self.key_history = []
        self.reset_lomari_buffer()
        self.close_candidate_popup()
        return True

    def cut_selection(self) -> str:
        """Cut selected text to clipboard and delete it from the IME buffer.

        Ctrl+X must be handled by this IME model, not by Tk's default Text
        widget edit command.  Read the selected text directly from the Text
        widget before changing anything, then explicitly claim the system
        clipboard and only then update the internal composer text.
        """
        offsets = self.normalize_atomic_text_selection()
        if offsets is None:
            return 'break'

        start, end = offsets
        content = self.text.get('1.0', 'end-1c')
        selected = content[start:end]
        if not selected:
            return 'break'

        if end <= start:
            return 'break'

        self.push_undo_state()

        # Put the selected words onto the real system clipboard first.
        self.set_system_clipboard_text(self.clipboard_plain_text(selected))

        self.composer.output = content[:start] + content[end:]
        self.composer.cursor_pos = start
        self.composer.initial = self.composer.medial = self.composer.final = ''
        self.key_history = []
        self.reset_lomari_buffer()
        self.close_candidate_popup()
        self.render()
        self.status.configure(text='Cut to clipboard.')
        self.text.focus_set()
        return 'break'

    def move_cursor_vertically(self, direction: int) -> None:
        """Move the text cursor up/down by one visible line."""
        self.composer.commit()
        current = self.text.index('insert')
        target = self.text.index(f'{current} {direction:+d} lines')
        self.composer.move_to(self.text_index_to_offset(target))

    def sync_cursor_from_text_widget(self) -> None:
        """Update the internal cursor after a mouse click. Keep selections intact."""
        # If there is a selection, leave it for Backspace/typing to delete.
        if self.normalize_atomic_text_selection() is not None:
            return
        raw_offset = self.text_index_to_offset('insert')
        self.composer.move_to(raw_offset)
        snapped_offset = self.composer.display_cursor_pos()
        if snapped_offset != raw_offset:
            try:
                self.text.mark_set('insert', f'1.0+{snapped_offset}c')
                self.text.see('insert')
            except tk.TclError:
                pass
        self.key_history = []
        self.reset_lomari_buffer()
        self.close_candidate_popup()

    def on_mouse_press(self, event: tk.Event) -> None:
        """Remember the raw click position so drag selection can stay atomic."""
        try:
            index = self.text.index(f'@{event.x},{event.y}')
            self.mouse_selection_anchor_offset = self.text_index_to_offset(index)
        except tk.TclError:
            self.mouse_selection_anchor_offset = self.composer.display_cursor_pos()

    def on_mouse_drag_select(self, event: tk.Event) -> str:
        """Select jamo clusters as whole units while the mouse is dragging."""
        content = self.text.get('1.0', 'end-1c')
        anchor = getattr(self, 'mouse_selection_anchor_offset', None)
        if anchor is None:
            anchor = self.text_index_to_offset('insert')
            self.mouse_selection_anchor_offset = anchor

        try:
            current = self.text_index_to_offset(self.text.index(f'@{event.x},{event.y}'))
        except tk.TclError:
            current = anchor

        start, end = self.expand_atomic_selection_offsets(anchor, current, content)
        try:
            self.text.tag_remove('sel', '1.0', 'end')
            if end > start:
                self.text.tag_add('sel', self.offset_to_text_index(start), self.offset_to_text_index(end))
            insert_offset = end if current >= anchor else start
            self.text.mark_set('insert', self.offset_to_text_index(insert_offset))
            self.text.see('insert')
        except tk.TclError:
            pass
        return 'break'

    def on_mouse_release(self, event: tk.Event) -> None:
        # Let Tk finish placing the cursor/selection first, then sync our model.
        self.root.after_idle(self.sync_cursor_from_text_widget)

    def on_root_unmap(self, event: tk.Event) -> None:
        """Hide candidate popup when the main IME window is minimised."""
        if event.widget is not self.root:
            return
        self.root.after_idle(self.close_candidate_popup_if_root_hidden)

    def close_candidate_popup_if_root_hidden(self) -> None:
        try:
            state = self.root.state()
        except tk.TclError:
            state = ''
        try:
            viewable = bool(self.root.winfo_viewable())
        except tk.TclError:
            viewable = True

        if state in {'iconic', 'withdrawn'} or not viewable:
            self.close_candidate_popup()
            if self.keyboard_help_open:
                self.close_keyboard_help_panel()

    def on_root_configure(self, event: tk.Event) -> None:
        """Extra Windows safeguard: hide the popup as soon as root is minimised."""
        if event.widget is self.root:
            self.root.after_idle(self.close_candidate_popup_if_root_hidden)
            if self.keyboard_help_open:
                self.root.after_idle(self.show_keyboard_help_for_current_window_state)

    def start_candidate_visibility_monitor(self) -> None:
        """Periodically close the candidate popup if the main window is minimised.

        Some Windows / pythonw / Tk combinations leave a topmost Toplevel on
        screen even when <Unmap> is not delivered reliably.  A light monitor
        makes the popup disappear as soon as the main IME window is minimised.
        """
        if self.candidate_visibility_after_id is not None:
            try:
                self.root.after_cancel(self.candidate_visibility_after_id)
            except tk.TclError:
                pass
            self.candidate_visibility_after_id = None
        self.candidate_visibility_after_id = self.root.after(120, self.monitor_candidate_visibility)

    def monitor_candidate_visibility(self) -> None:
        self.candidate_visibility_after_id = None
        if self.candidate_popup is None:
            return
        self.close_candidate_popup_if_root_hidden()
        if self.candidate_popup is not None:
            self.candidate_visibility_after_id = self.root.after(120, self.monitor_candidate_visibility)

    def toggle_topmost(self) -> None:
        topmost = bool(self.always_on_top.get())
        self.root.attributes('-topmost', topmost)
        if self.keyboard_help_panel is not None:
            try:
                self.keyboard_help_panel.attributes('-topmost', topmost)
            except tk.TclError:
                pass

    def on_e_to_ye_autocorrect_setting_changed(self) -> None:
        if self.e_to_ye_autocorrect_on.get():
            return
        if self.composer.e_to_ye_autocorrected and self.composer.medial == 'ᅨ':
            self.composer.medial = 'ᅦ'
            self.composer.e_to_ye_autocorrected = False
            self.render()

    def on_lomari_key_style_changed(self) -> None:
        self.lomari_key_style.set(normalize_lomari_key_style(self.lomari_key_style.get()))
        self.close_candidate_popup()
        self.reset_lomari_buffer()
        if self.keyboard_help_open:
            self.refresh_keyboard_help_panel()

    def toggle_hanri(self) -> str:
        self.hanri_on.set(not self.hanri_on.get())
        self.apply_hanri_and_render()
        return 'break'

    def set_composer_text_after_toggle(self, text: str) -> None:
        """Replace the composer text with a clean committed string."""
        self.composer.output = str(text)
        self.composer.cursor_pos = len(self.composer.output)
        self.composer.initial = self.composer.medial = self.composer.final = ''
        self.composer.clamp_cursor()
        self.hanri_instance_readings = []
        self.hanri_instance_text_snapshot = self.composer.output
        self.key_history = []
        self.reset_lomari_buffer()

    def hanri_to_hangul_toggle_index(self) -> list[tuple[str, str]]:
        """Return visible Hanri keys mapped to fully tone-marked Hangul readings."""
        items: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for key, reading in AUDIO_HANRI_INDEX:
            key = str(key or '')
            reading = str(reading or '')
            if not key or not reading or not field_has_hanri(key):
                continue
            hangul = format_text_tones_for_output(reading, True)
            if not hangul:
                continue
            pair = (key, hangul)
            if pair not in seen:
                items.append(pair)
                seen.add(pair)
        return sorted(items, key=lambda item: len(item[0]), reverse=True)

    def convert_hanri_text_to_hangul_for_toggle(self, text: str) -> tuple[str, list[dict]]:
        """Convert Hanri spans to tone-marked Hangul and record segment provenance.

        Segments marked from_hanri=True are the only spans allowed to turn back
        into Hanri after an edited Hanri-off state.  All original Hangul/text
        spans are protected from automatic Hanri restoration.
        """
        source = str(text)
        index = self.hanri_to_hangul_toggle_index()
        out: list[str] = []
        segments: list[dict] = []

        def add_segment(piece: str, from_hanri: bool, original: str | None = None) -> None:
            if not piece:
                return
            start = sum(len(seg['text']) for seg in segments)
            if segments and segments[-1]['from_hanri'] == from_hanri and not from_hanri:
                segments[-1]['text'] += piece
                segments[-1]['original'] += original if original is not None else piece
                segments[-1]['end'] += len(piece)
                return
            segments.append({
                'start': start,
                'end': start + len(piece),
                'text': piece,
                'from_hanri': bool(from_hanri),
                'original': original if original is not None else piece,
            })

        i = 0
        while i < len(source):
            tail = source[i:]
            matched = False
            for key, hangul in index:
                # Mixed candidates such as 고비店 begin with Hangul but still
                # contain Hanri.  Try them at every position; the index itself
                # already excludes keys without Hanri characters.
                if tail.startswith(key):
                    out.append(hangul)
                    add_segment(hangul, True, source[i:i + len(key)])
                    i += len(key)
                    matched = True
                    break
            if matched:
                continue
            out.append(source[i])
            add_segment(source[i], False, source[i])
            i += 1

        return ''.join(out), segments

    def first_hanri_toggle_entries(self) -> list[tuple[str, str]]:
        """Return Hangul reading keys mapped to the first TSV Hanri output.

        This is used only when Hanri was toggled off, the user edited the
        Hangulised text, and exact restoration is no longer safe.  Auto-generated
        sandhi rows are skipped so "first entry" means the first real TSV row
        after priority/row sorting.
        """
        items: list[tuple[str, str]] = []
        seen_key: set[str] = set()

        for base_reading, entries in HANRI_DICT.items():
            sorted_entries = sorted(entries, key=lambda e: (e.get('priority', 9999), e.get('row', 9999), e.get('hanri', '')))
            for entry in sorted_entries:
                if entry.get('auto_sandhi'):
                    continue
                hanri = str(entry.get('hanri', ''))
                if not field_has_hanri(hanri):
                    continue
                if not should_display_hanri_entry(entry, base_reading):
                    continue

                reading = str(entry.get('reading', base_reading) or base_reading)
                corrected = str(entry.get('corrected', '') or '')
                if entry.get('nonstandard') and corrected:
                    reading = corrected

                output = format_text_tones_for_output(hanri, True)
                keys = [
                    format_text_tones_for_output(reading, True),
                    display_reading_tones(normalize_tone_symbols_to_digits(reading)),
                    normalize_tone_symbols_to_digits(reading),
                    strip_reading_tones(reading),
                    base_reading,
                ]

                for key in keys:
                    key = str(key or '')
                    if not key or key in seen_key:
                        continue
                    seen_key.add(key)
                    items.append((key, output))
                break

        return sorted(items, key=lambda item: len(item[0]), reverse=True)

    def protected_ranges_from_hanri_snapshot(self, current_text: str) -> list[tuple[int, int]]:
        """Map original non-Hanri spans from the Hanri-off snapshot into current text."""
        snap = self.hanri_toggle_snapshot
        if not isinstance(snap, dict):
            return []
        snapshot_text = str(snap.get('hangul_text', ''))
        current_text = str(current_text)
        if not snapshot_text or not current_text:
            return []

        protected_source_ranges = [
            (int(seg.get('start', 0)), int(seg.get('end', 0)))
            for seg in snap.get('segments', [])
            if not seg.get('from_hanri') and int(seg.get('end', 0)) > int(seg.get('start', 0))
        ]
        if not protected_source_ranges:
            return []

        mapped: list[tuple[int, int]] = []
        matcher = difflib.SequenceMatcher(None, snapshot_text, current_text, autojunk=False)
        for block in matcher.get_matching_blocks():
            if block.size <= 0:
                continue
            block_a_start = block.a
            block_a_end = block.a + block.size
            for src_start, src_end in protected_source_ranges:
                inter_start = max(src_start, block_a_start)
                inter_end = min(src_end, block_a_end)
                if inter_end <= inter_start:
                    continue
                cur_start = block.b + (inter_start - block_a_start)
                cur_end = cur_start + (inter_end - inter_start)
                mapped.append((cur_start, cur_end))

        if not mapped:
            return []
        mapped.sort()
        merged: list[tuple[int, int]] = []
        for start, end in mapped:
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    def convert_hangul_text_to_first_hanri_for_toggle(
        self,
        text: str,
        protected_ranges: list[tuple[int, int]] | None = None,
    ) -> str:
        """Convert unprotected Hangul readings to first TSV Hanri entries."""
        source = str(text)
        index = self.first_hanri_toggle_entries()
        protected_ranges = sorted(protected_ranges or [])
        out: list[str] = []
        i = 0
        protect_i = 0

        def protected_end_at(pos: int) -> int | None:
            nonlocal protect_i
            while protect_i < len(protected_ranges) and protected_ranges[protect_i][1] <= pos:
                protect_i += 1
            if protect_i < len(protected_ranges):
                start, end = protected_ranges[protect_i]
                if start <= pos < end:
                    return end
            return None

        while i < len(source):
            end = protected_end_at(i)
            if end is not None:
                out.append(source[i:end])
                i = end
                continue

            tail = source[i:]
            matched = False
            for key, hanri in index:
                if not key:
                    continue
                # Do not let a match cross into a protected original-Hangul span.
                next_protected_start = None
                for start, _end in protected_ranges:
                    if start >= i:
                        next_protected_start = start
                        break
                if next_protected_start is not None and i + len(key) > next_protected_start:
                    continue
                if tail.startswith(key):
                    out.append(hanri)
                    # When a tone-marked Hangul reading is converted back into
                    # Hanri, no visible tone mark should be left dangling after
                    # the Hanri text.  This matters when a shorter fallback key
                    # such as the tone-stripped reading wins or when the user has
                    # edited the Hanri-off text but left a tone mark immediately
                    # after the matched reading.  Literal Alt+digits are protected
                    # by LITERAL_DIGIT_MARK and are therefore not consumed here.
                    consume_end = i + len(key)
                    while (
                        consume_end < len(source)
                        and source[consume_end] in TONE_SYMBOLS.union(TONE_DIGITS).union(INTERNAL_TONE_MARK_CHARS)
                    ):
                        consume_end += 1
                    i = consume_end
                    matched = True
                    break
            if matched:
                continue
            out.append(source[i])
            i += 1

        return ''.join(out)

    def apply_hanri_toggle_transform(self) -> bool:
        """Apply text conversion when the Hanri toggle changes.

        Returns True if the text changed.
        """
        self.composer.commit()
        current = self.composer.text()

        if not self.hanri_on.get():
            converted, segments = self.convert_hanri_text_to_hangul_for_toggle(current)
            self.hanri_toggle_snapshot = {
                'source_text': current,
                'hangul_text': converted,
                'segments': segments,
            }
            if converted != current:
                self.set_composer_text_after_toggle(converted)
                return True
            return False

        # Hanri has been turned back on.
        # Restore only when the Hanri-off text is unchanged.  If the user edited
        # the Hangulised text, leave it exactly as edited; do not fall back to
        # the first TSV Hanri entry.
        snap = self.hanri_toggle_snapshot
        if isinstance(snap, dict) and current == snap.get('hangul_text'):
            restored = str(snap.get('source_text', current))
        else:
            restored = current

        self.hanri_toggle_snapshot = None
        if restored != current:
            self.set_composer_text_after_toggle(restored)
            return True
        return False

    def apply_hanri_and_render(self) -> None:
        self.close_candidate_popup()
        before = self.composer_state_snapshot()
        changed = self.apply_hanri_toggle_transform()
        if changed:
            if not self.undo_stack or self.undo_stack[-1] != before:
                self.undo_stack.append(before)
                if len(self.undo_stack) > 200:
                    self.undo_stack = self.undo_stack[-200:]
            self.redo_stack = []
        self.render()
        if self.hanri_on.get():
            self.maybe_show_hanri_candidates()

    def apply_tone_digit_display_to_latest_input(self, digit: str) -> None:
        """Turn a just-typed tone digit into the displayed tone form.

        This happens even when the Hangul+tone reading is not in the Hanri TSV.
        Examples with Hangul tones ON:
            가4 -> 가ˊ
            가1 -> 가ˆ
            가2 -> 가ˋ
            가3 -> 가
            가5 -> 가ˉ

        With Hangul tones OFF, the digit is removed instead.
        Candidate lookup still works because find_hanri_candidate() normalises
        tone symbols back to digits internally.
        """
        if digit not in TONE_DIGITS:
            return

        # Tone digits are inserted literally first.  After insertion, the
        # digit should be immediately before the cursor and the previous
        # character should be Hangul/Jamo.
        self.composer.commit()
        self.composer.clamp_cursor()
        pos = self.composer.cursor_pos
        if pos < 1 or self.composer.output[pos - 1] != digit:
            return
        if pos < 2 or not can_attach_tone_to_text(self.composer.output, pos - 2):
            return

        if self.output_tones_on.get():
            replacement = INTERNAL_TONE_MARKS[digit] if digit == '3' else display_reading_tones(digit)
        else:
            # Hide the tone in the typing box, but keep it internally so Hanri
            # lookup can still filter by tone.
            replacement = INTERNAL_TONE_MARKS[digit]
        self.composer.output = self.composer.output[:pos - 1] + replacement + self.composer.output[pos:]
        self.composer.cursor_pos = pos - 1 + len(replacement)

    def normalize_apostrophe_input(self, char: str) -> str:
        """Change straight apostrophe to curly connector apostrophe live.

        The conversion is visible immediately in the IME typing box.

        Examples:
            랑'       -> 랑’
            人'       -> 人’
            랑ˊ'      -> 랑ˊ’
            [全좐]'   -> [全좐]’
        """
        if char != "'":
            return char

        current = self.composer.text()
        pos = self.composer.display_cursor_pos()
        prev = previous_non_tone_char(current, pos)
        if is_hangul_or_hanri_char(prev) or prev == ']':
            return '’'
        return char

    def format_hangul_output(self, reading: str) -> str:
        """Format pure Hangul output according to the Hangul tones toggle."""
        if self.output_tones_on.get():
            return display_reading_tones(reading)
        return strip_reading_tones(reading)

    def format_entry_label_detail(self, entry: dict, base_reading: str) -> str:
        """Return the right-side detail shown after a candidate.

        Standard entries use their TSV reading as the pronunciation/detail.
        Non-standard entries marked with a rightmost * in the TSV reading use
        the TSV corrected column instead, so the menu can convert from a wrong
        spelling while showing the standard Hangul spelling on the right.
        """
        written = entry.get('reading', base_reading)
        form = entry.get('form', '')
        corrected = entry.get('corrected', '')
        use_corrected = bool(entry.get('nonstandard') and corrected)
        detail_source = corrected if use_corrected else written

        should_show_reading = (
            use_corrected
            or bool(form)
            or reading_has_tones(written)
            or written != base_reading
        )
        if not should_show_reading:
            return ''

        detail = self.format_hangul_output(detail_source)
        if form:
            detail += f' ({form})'
        return f'  {detail}'

    def _candidate_choices_from_entries(self, base_reading: str, entries: list[dict], typed_form: str = '') -> tuple[list[str], list[str], list[str | None], list[bool]]:
        """Build candidate choices.

        Ordering rule for tone variants:
        - if the user typed a toneless form, toneless candidates come first,
          then dictionary-supported toned candidates.
        - if the user typed a toned form, toned candidates come first,
          then toneless candidates.

        This is applied universally to both mixed Hanri/Hangul outputs and pure
        Hangul reading suggestions.
        """
        typed_has_tones = reading_has_tones(typed_form)

        if typed_has_tones:
            # Tone filtering is strict about tones the user typed, but tolerant
            # about earlier tones the user omitted.  Example:
            #   TSV citation: 옝1완2  永遠
            #   auto sandhi:  옝1완1  永遠
            #   typed 옝완2 -> matches citation
            #   typed 옝완1 -> matches sandhi
            filtered = [
                entry for entry in entries
                if typed_tones_are_compatible_with_entry(
                    typed_form,
                    entry.get('reading', base_reading),
                )
            ]

            # If the TSV only has an untoned reading, e.g. 활히 / 歡喜,
            # typed 활5히2 should still offer 歡喜 instead of showing no menu.
            # Auto-generated sandhi entries are not used for this fallback.
            if not filtered:
                typed_base = strip_reading_tones(typed_form)
                filtered = [
                    entry for entry in entries
                    if (
                        strip_reading_tones(entry.get('reading', base_reading)) == typed_base
                        and not entry.get('auto_sandhi')
                    )
                ]
        else:
            # Plain untoned input should show the actual TSV candidates, not
            # every generated sandhi alternative.  Toned input can still reach
            # the generated sandhi forms directly.
            filtered = [entry for entry in entries if not entry.get('auto_sandhi')]

        choices: list[str] = []
        labels: list[str] = []
        choice_readings: list[str | None] = []
        choice_auto_sandhi: list[bool] = []
        seen_choice_values: set[str] = set()
        seen_label_candidates = set()
        pure_readings: list[str] = []

        def add_choice(value: str, label_text: str | None = None, reading: str | None = None, auto_sandhi: bool = False) -> None:
            if not value or value in seen_choice_values:
                return
            seen_choice_values.add(value)
            choices.append(value)
            choice_readings.append(reading)
            choice_auto_sandhi.append(bool(auto_sandhi))
            labels.append(f'{len(labels) + 1}  {label_text if label_text is not None else value}')

        def tone_variants(value: str) -> list[str]:
            """Return value as [preferred tone form, alternate tone form]."""
            toned = format_text_tones_for_output(value, True)
            toneless = format_text_tones_for_output(value, False)
            if typed_has_tones:
                ordered = [toned, toneless]
            else:
                ordered = [toneless, toned]

            result: list[str] = []
            for item in ordered:
                if item and item not in result:
                    result.append(item)
            return result

        def add_pure_hangul_variants(value: str) -> None:
            for variant in tone_variants(value):
                add_choice(variant)

        # Plain, unmarked Hangul should be the safest/default choice in the menu.
        # Example: typing 시 should offer 시 first, even if the TSV also has
        # 時/四/死 or Hangul-only tone helper rows. Explicitly toned input such
        # as 시4 keeps the old behaviour and prioritises matching TSV entries.
        if not typed_has_tones:
            add_pure_hangul_variants(base_reading)

        for entry in filtered:
            reading_value = entry.get('reading', base_reading)
            if reading_value not in pure_readings:
                pure_readings.append(reading_value)

            if not should_display_hanri_entry(entry, base_reading):
                # A Hangul-only hanri field should not be displayed as a Hanri
                # conversion candidate.  However, its TSV reading can still be
                # useful as a pure-Hangul/tone suggestion below.
                continue

            hanri_raw = entry['hanri']
            commit_reading_value = entry.get('citation_reading', reading_value) if entry.get('auto_sandhi') else reading_value
            commit_auto_sandhi = bool(entry.get('auto_sandhi') and not entry.get('citation_reading'))
            variants = tone_variants(hanri_raw)

            # If a Hanri candidate itself has tone variants because it contains
            # Hangul/Jamo after Hanri, show those exact output forms directly.
            # Example from TSV:
            #   쟣바2’ᄅᆤ2  食飽’ᄅᆤˋ
            # untoned input should show:
            #   食飽’ᄅᆤ
            #   食飽’ᄅᆤˋ
            # without an extra right-side reading detail, because the candidate
            # text is already the exact committed output.
            has_hanri_tone_variants = len(variants) > 1

            reading_detail_toned = is_fully_toned_reading(reading_value)
            hanri_is_hangul_only_replacement = is_hangul_only_field(hanri_raw) and not field_has_hanri(hanri_raw)
            corrected_detail = self.format_entry_label_detail(entry, base_reading) if entry.get('nonstandard') else ''

            for variant_index, variant in enumerate(variants):
                if has_hanri_tone_variants:
                    # Mixed Hanri+Hangul candidates can have visible tone variants,
                    # e.g. 食飽’ᄅᆤ / 食飽’ᄅᆤˋ.  The pronunciation shown on
                    # the right should always be the fully tone-marked reading,
                    # e.g. 쟣바ˋ’ᄅᆤˋ, unless the row is a Hangul-to-Hangul
                    # replacement where the candidate itself is already the output.
                    # Non-standard rows marked with * override this: their right
                    # side shows the corrected column.
                    label_text = variant
                    if corrected_detail:
                        label_text = f'{variant}{corrected_detail}'
                    elif (
                        not hanri_is_hangul_only_replacement
                        and reading_detail_toned
                        and reading_detail_toned != variant
                    ):
                        label_text = f'{variant}  {reading_detail_toned}'
                    add_choice(variant, label_text, commit_reading_value, commit_auto_sandhi)
                else:
                    detail = self.format_entry_label_detail(entry, base_reading)
                    dedupe_key = (variant, entry.get('reading', base_reading), entry.get('form', ''), detail)
                    if dedupe_key in seen_label_candidates:
                        continue
                    seen_label_candidates.add(dedupe_key)
                    add_choice(variant, f'{variant}{detail}', commit_reading_value, commit_auto_sandhi)

        # Pure Hangul ordering follows the user's input too:
        # - toneless input: typed/base toneless form first, then toned TSV reading(s)
        # - toned input: typed toned form first, then toneless base form
        if typed_has_tones:
            add_pure_hangul_variants(typed_form)
            for reading in pure_readings:
                add_pure_hangul_variants(reading)
            add_pure_hangul_variants(base_reading)
        else:
            add_pure_hangul_variants(base_reading)
            for reading in pure_readings:
                add_pure_hangul_variants(reading)

        return choices, labels, choice_readings, choice_auto_sandhi

    def with_lomari_key_style_alternate_candidates(self, candidate: dict | None) -> dict | None:
        """Add POJ/Tai-lo ambiguous oe/ue Hanri candidates to a Lomari menu."""
        if self.input_mode.get() != 'lomari':
            return candidate

        style = normalize_lomari_key_style(self.lomari_key_style.get())
        if not self.lomari_raw:
            return candidate

        current = self.composer.text()
        cursor_pos = self.composer.display_cursor_pos()
        before_cursor = current[:cursor_pos]
        after_cursor = current[cursor_pos:]
        default_text = convert_lomari_raw_to_hangul(
            self.lomari_raw,
            e_to_ye_autocorrect=self.e_to_ye_autocorrect_on.get(),
            lomari_key_style=style,
        )
        if not default_text or not before_cursor.endswith(default_text):
            return candidate

        prefix = before_cursor[:-len(default_text)]
        same_span_candidate = candidate if candidate is not None and candidate.get('prefix') == prefix else None

        merged_choices: list[str] = []
        merged_labels: list[str] = []
        merged_readings: list[str | None] = []
        merged_auto_sandhi: list[bool] = []
        seen_choices: set[str] = set()

        def add_menu_items(
            choices: list[str],
            labels: list[str],
            readings: list[str | None] | None = None,
            auto_sandhi_flags: list[bool] | None = None,
        ) -> None:
            readings = readings or [None] * len(choices)
            auto_sandhi_flags = auto_sandhi_flags or [False] * len(choices)
            for choice, label, reading, auto_sandhi in zip(choices, labels, readings, auto_sandhi_flags):
                if not choice or choice in seen_choices:
                    continue
                seen_choices.add(choice)
                label_detail = str(label).split('  ', 1)[1] if '  ' in str(label) else str(label)
                merged_choices.append(choice)
                merged_readings.append(reading)
                merged_auto_sandhi.append(bool(auto_sandhi))
                merged_labels.append(f'{len(merged_labels) + 1}  {label_detail}')

        if same_span_candidate is not None:
            add_menu_items(
                same_span_candidate.get('choices', []),
                same_span_candidate.get('labels', []),
                same_span_candidate.get('choice_readings', []),
                same_span_candidate.get('choice_auto_sandhi', []),
            )
        else:
            default_display = self.format_hangul_output(default_text)
            add_menu_items([default_display], [f'1  {default_display}'])

        def add_alternate_text_candidates(alternate_text: str) -> None:
            base_reading = strip_reading_tones(normalize_tone_symbols_to_digits(alternate_text))
            entries = HANRI_DICT.get(base_reading)
            if not entries:
                return
            alt_choices, alt_labels, alt_readings, alt_auto_sandhi = self._candidate_choices_from_entries(
                base_reading,
                entries,
                typed_form=alternate_text,
            )
            add_menu_items(alt_choices, alt_labels, alt_readings, alt_auto_sandhi)

        for alternate_text in lomari_loose_candidate_alternate_texts(
            self.lomari_raw,
            e_to_ye_autocorrect=self.e_to_ye_autocorrect_on.get(),
            lomari_key_style=style,
        ):
            add_alternate_text_candidates(alternate_text)

        for alternate_raw in lomari_key_style_alternate_raws(self.lomari_raw, style):
            alternate_text = convert_lomari_raw_to_hangul(
                alternate_raw,
                e_to_ye_autocorrect=self.e_to_ye_autocorrect_on.get(),
                lomari_key_style=LOMARI_KEY_STYLE_STANDARD,
            )
            add_alternate_text_candidates(alternate_text)
            if 'I' in alternate_raw:
                base_reading = strip_reading_tones(normalize_tone_symbols_to_digits(alternate_text))
                if not HANRI_DICT.get(base_reading):
                    alternate_display = self.format_hangul_output(alternate_text)
                    add_menu_items([alternate_display], [f'1  {alternate_display}'])

        if len(merged_choices) <= (len(same_span_candidate.get('choices', [])) if same_span_candidate is not None else 1):
            return candidate

        return {
            'prefix': prefix,
            'suffix': after_cursor,
            'matched_text': default_text,
            'reading': same_span_candidate.get('reading', default_text) if same_span_candidate is not None else default_text,
            'choices': merged_choices,
            'labels': merged_labels,
            'choice_readings': merged_readings,
            'choice_auto_sandhi': merged_auto_sandhi,
        }

    def suppress_current_hanri_candidate_once(self) -> None:
        """Remember that the user chose to keep the current text as Hangul.

        This prevents the IME from asking again for the same just-accepted
        Hangul text when the next key is Space. The suppression is tied to the
        exact text and cursor position, so further typing such as adding a tone
        digit or another syllable can still trigger a fresh candidate menu.
        """
        self.suppressed_hanri_contexts.add((self.composer.text(), self.composer.display_cursor_pos()))

    def current_hanri_candidate_is_suppressed(self) -> bool:
        """Return True only once for a suppressed just-committed context.

        The suppression is meant to stop the menu from reopening immediately
        when the user presses Space/Enter after choosing a candidate.  It must
        not permanently blacklist that same Hangul reading later in the same
        session, because the user may type the same word again and expect the
        menu to appear.
        """
        context = (self.composer.text(), self.composer.display_cursor_pos())
        if context in self.suppressed_hanri_contexts:
            self.suppressed_hanri_contexts.discard(context)
            return True
        return False

    def find_hanri_candidate(self, force: bool = False) -> dict | None:
        """Return an exact or predictive Hanri candidate record.

        Candidate lookup is anchored at the current text cursor, not only at the
        end of the whole input box.  This lets the user move back to the front
        or middle of a sentence and still get Hanri menus there.

        Longest-match rule:
            When several entries can match the text before the cursor, the menu
            belongs to the longest matching reading, not to a shorter suffix.
            Example: if 림롷킈 can match a longer dictionary reading, it should
            not fall back to the suffix 킈 just because 킈 also has an entry.
        """
        if not self.hanri_on.get():
            return None

        current = self.composer.text()
        if not current:
            return None

        cursor_pos = self.composer.display_cursor_pos()
        before_cursor = current[:cursor_pos]
        after_cursor = current[cursor_pos:]

        if not before_cursor:
            return None

        # Candidate lookup treats typed tone symbols as equivalent to tone digits.
        before_lookup = normalize_tone_symbols_to_digits(before_cursor)
        before_loose_lookup = remove_apostrophes_for_lookup(before_lookup)

        if self.current_hanri_candidate_is_suppressed():
            return None

        def match_score(matched_text: str, phase: int) -> tuple[int, int, int]:
            """Sort key for choosing which candidate owns the menu.

            The first number is the length of the canonical reading with
            apostrophe separators removed.  This makes a longer relaxed match
            such as 림롷’킈 beat a shorter suffix match such as 킈.

            The second number prefers tone-explicit matches when the span is the
            same.  The third keeps stricter phases ahead only as a tie-breaker,
            never ahead of a genuinely longer word.
            """
            loose = remove_apostrophes_for_lookup(matched_text)
            # Tone digits are useful for filtering, but they should not let a
            # shorter word beat a longer word purely because it has a tone digit.
            span_len = len(strip_reading_tones(loose))
            tone_bonus = 1 if reading_has_tones(matched_text) else 0
            return (span_len, tone_bonus, -phase)

        def real_start_for_loose_suffix(needed: int) -> int:
            """Return real start index for a loose suffix match before cursor.

            `needed` counts non-apostrophe characters in the matched dictionary
            key.  The user's typed text may or may not contain apostrophes, so
            this walks backward across the real text and ignores apostrophes
            only for locating the span.
            """
            chars_taken = 0
            i = len(before_lookup) - 1
            while i >= 0 and chars_taken < needed:
                if before_lookup[i] not in {"'", '’'}:
                    chars_taken += 1
                i -= 1
            return i + 1

        def build_candidate(prefix: str, matched_typed_form: str, base_reading: str, entries: list[dict]) -> dict:
            choices, labels, choice_readings, choice_auto_sandhi = self._candidate_choices_from_entries(base_reading, entries, typed_form=matched_typed_form)
            # Even if every matching TSV hanri field is Hangul-only,
            # keep the menu open and show only the pure-Hangul fallback.
            # This lets TSV rows support lookup/prediction without showing
            # the non-Hanri hanri column as a conversion candidate.
            return {
                'prefix': prefix,
                'suffix': after_cursor,
                'matched_text': matched_typed_form,
                'reading': base_reading,
                'choices': choices,
                'labels': labels,
                'choice_readings': choice_readings,
                'choice_auto_sandhi': choice_auto_sandhi,
            }

        best_exact: tuple[tuple[int, int, int], dict] | None = None

        def consider_exact(score_text: str, phase: int, prefix: str, matched_typed_form: str, base_reading: str, entries: list[dict]) -> None:
            nonlocal best_exact
            candidate = build_candidate(prefix, matched_typed_form, base_reading, entries)
            score = match_score(score_text, phase)
            if best_exact is None or score > best_exact[0]:
                best_exact = (score, candidate)

        exact_tests_for_suffix = HANRI_EXACT_CANDIDATE_BUCKETS.get(before_lookup[-1], []) if before_lookup else []
        base_tests_for_suffix = HANRI_BASE_CANDIDATE_BUCKETS.get(last_non_tone_char(before_lookup), [])
        exact_tests_for_loose_suffix = HANRI_EXACT_CANDIDATE_BUCKETS.get(before_loose_lookup[-1], []) if before_loose_lookup else []
        base_tests_for_loose_suffix = HANRI_BASE_CANDIDATE_BUCKETS.get(last_non_tone_char(before_loose_lookup), [])

        # Phase 1: strict exact matches.  Example: typed 래 should match TSV
        # 래5 / 內 before any apostrophe-relaxed reading is considered, unless
        # another candidate genuinely spans a longer word.
        for typed_form, base_reading, entries in exact_tests_for_suffix:
            if before_lookup.endswith(typed_form):
                prefix = before_cursor[:-len(typed_form)] if typed_form else before_cursor
                consider_exact(typed_form, 1, prefix, typed_form, base_reading, entries)

        # Phase 2: tone-insensitive strict matches, e.g. typed 활5히2 can match
        # an untoned TSV base 활히.
        for base_reading, entries in base_tests_for_suffix:
            start = toned_suffix_match_start(before_lookup, base_reading)
            if start is not None:
                matched_typed_form = before_lookup[start:]
                prefix = before_cursor[:start]
                consider_exact(matched_typed_form, 2, prefix, matched_typed_form, base_reading, entries)

        # Phase 3: relaxed apostrophe exact matches.  Only internal apostrophes
        # are optional.  Leading apostrophes are meaningful, so 래 must not match
        # a TSV reading like ’래.  A longer relaxed match beats a shorter suffix
        # strict match, e.g. 림롷킈 should prefer 림롷’킈 over 킈.
        for typed_form, base_reading, entries in exact_tests_for_loose_suffix:
            if not has_relaxable_apostrophe(typed_form):
                continue
            typed_form_loose = remove_apostrophes_for_lookup(typed_form)
            if typed_form_loose and before_loose_lookup.endswith(typed_form_loose):
                real_start = real_start_for_loose_suffix(len(typed_form_loose))
                prefix = before_cursor[:real_start]
                consider_exact(typed_form, 3, prefix, typed_form, base_reading, entries)

        # Phase 4: tone-insensitive relaxed matches for internal apostrophe
        # separators.
        for base_reading, entries in base_tests_for_loose_suffix:
            if not has_relaxable_apostrophe(base_reading):
                continue
            base_loose = remove_apostrophes_for_lookup(base_reading)
            loose_start = toned_suffix_match_start(before_loose_lookup, base_loose)
            if loose_start is not None:
                real_start = real_start_for_loose_suffix(len(base_loose))
                prefix = before_cursor[:real_start]
                consider_exact(base_reading, 4, prefix, base_reading, base_reading, entries)

        # Predictive candidates for the longest matching typed prefix immediately
        # before the cursor.  We build this even when an exact match exists, so a
        # longer in-progress word can beat a shorter exact suffix.
        possible_prefixes: list[str] = []
        seen_possible_prefixes: set[str] = set()
        bucket_keys = set()
        if before_lookup:
            bucket_keys.add(before_lookup[-1])
        if before_loose_lookup:
            bucket_keys.add(before_loose_lookup[-1])
        for bucket_key in bucket_keys:
            for prefix in HANRI_PREFIX_LOOKUP_BUCKETS.get(bucket_key, []):
                if prefix not in seen_possible_prefixes:
                    possible_prefixes.append(prefix)
                    seen_possible_prefixes.add(prefix)

        matching_prefixes = [
            prefix for prefix in possible_prefixes
            if (
                before_lookup.endswith(prefix)
                or (
                    has_relaxable_apostrophe(prefix)
                    and before_loose_lookup.endswith(remove_apostrophes_for_lookup(prefix))
                )
            )
        ]

        predictive_candidate: dict | None = None
        predictive_score: tuple[int, int, int] | None = None

        if matching_prefixes:
            matched_text = max(matching_prefixes, key=lambda p: len(strip_reading_tones(remove_apostrophes_for_lookup(p))))
            raw_items = HANRI_PREFIX_INDEX.get(matched_text, [])

            # De-duplicate exact duplicated rows while preserving distinct
            # citation/sandhi readings for the same Hanri.
            seen_candidates = set()
            seen_pure_hangul = set()
            seen_choice_values = set()
            choices = []
            labels = []
            choice_readings: list[str | None] = []
            choice_auto_sandhi: list[bool] = []

            def add_predictive_choice(value: str, label_text: str | None = None, reading: str | None = None, auto_sandhi: bool = False) -> None:
                """Add one predictive candidate, de-duplicating by committed output.

                Predictive lookup can reach the same visible candidate through
                multiple TSV rows: an untoned row, a citation-tone row, and an
                auto-sandhi row.  The user should see each actual output only
                once, while still seeing both toneless and tone-marked variants
                when they are genuinely different.
                """
                if not value or value in seen_choice_values:
                    return
                seen_choice_values.add(value)
                choices.append(value)
                choice_readings.append(reading)
                choice_auto_sandhi.append(bool(auto_sandhi))
                labels.append(f'{len(labels) + 1}  {label_text if label_text is not None else value}')

            def add_pure_hangul_choice(value: str) -> None:
                value = self.format_hangul_output(value)
                if not value or value in seen_pure_hangul:
                    return
                seen_pure_hangul.add(value)
                add_predictive_choice(value)

            # For predictive/unmarked menus, keep the raw Hangul prefix first.
            # Explicitly toned prefixes still keep TSV candidates first.
            if not reading_has_tones(matched_text):
                add_pure_hangul_choice(matched_text)

            predictive_typed_has_tones = reading_has_tones(matched_text)

            def predictive_tone_variants(value: str) -> list[str]:
                """Return toneless/toned variants in the same order as exact menus.

                Predictive menus are shown while the user is still composing the
                final syllable, e.g. 고빋 before 고비댬.  They should still show
                the same visible output variants as exact menus: untoned input
                offers toneless candidates first, then tone-marked candidates;
                tone-explicit input keeps tone-marked candidates first.
                """
                toned = format_text_tones_for_output(value, True)
                toneless = format_text_tones_for_output(value, False)
                ordered = [toned, toneless] if predictive_typed_has_tones else [toneless, toned]
                result: list[str] = []
                for item in ordered:
                    if item and item not in result:
                        result.append(item)
                return result

            for reading, entry in raw_items:
                if not should_display_hanri_entry(entry, reading):
                    # Hide the non-Hanri hanri column, but keep the row useful as a
                    # pure-Hangul/tone suggestion during predictive lookup.
                    add_pure_hangul_choice(entry.get('reading', reading))
                    continue

                hanri = entry['hanri']
                variants = predictive_tone_variants(hanri)

                if is_hangul_only_field(hanri) and not field_has_hanri(hanri):
                    detail = self.format_entry_label_detail(entry, reading) if entry.get('nonstandard') else ''
                    for variant in variants:
                        if not variant:
                            continue
                        dedupe_key = (variant, entry.get('reading', reading), entry.get('form', ''), 'hangul_replacement', detail)
                        if dedupe_key in seen_candidates:
                            continue
                        seen_candidates.add(dedupe_key)
                        add_predictive_choice(variant, f'{variant}{detail}', entry.get('reading', reading), bool(entry.get('auto_sandhi')))
                    continue

                has_hanri_tone_variants = len(variants) > 1
                reading_value = entry.get('reading', reading)
                reading_detail_toned = is_fully_toned_reading(reading_value)
                corrected_detail = self.format_entry_label_detail(entry, reading) if entry.get('nonstandard') else ''

                for variant in variants:
                    if has_hanri_tone_variants:
                        label_text = variant
                        if corrected_detail:
                            label_text = f'{variant}{corrected_detail}'
                        elif reading_detail_toned and reading_detail_toned != variant:
                            label_text = f'{variant}  {reading_detail_toned}'
                        dedupe_key = (variant, reading_value, entry.get('form', ''), label_text)
                    else:
                        detail = self.format_entry_label_detail(entry, reading)
                        label_text = f'{variant}{detail}'
                        dedupe_key = (variant, reading_value, entry.get('form', ''), detail)

                    if dedupe_key in seen_candidates:
                        continue
                    seen_candidates.add(dedupe_key)
                    add_predictive_choice(variant, label_text, reading_value, bool(entry.get('auto_sandhi')))

            # Final alternative keeps exactly what the user has typed so far.
            # This is still shown even when all TSV hanri fields for this match are
            # Hangul-only and therefore hidden from the candidate list.
            add_pure_hangul_choice(matched_text)

            real_start = real_start_for_loose_suffix(len(remove_apostrophes_for_lookup(matched_text)))
            predictive_candidate = {
                'prefix': before_cursor[:real_start],
                'suffix': after_cursor,
                'matched_text': matched_text,
                'reading': matched_text,
                'choices': choices,
                'labels': labels,
                'choice_readings': choice_readings,
                'choice_auto_sandhi': choice_auto_sandhi,
            }
            predictive_score = match_score(matched_text, 5)

        if best_exact is not None and predictive_candidate is not None and predictive_score is not None:
            if predictive_score > best_exact[0]:
                return self.with_lomari_key_style_alternate_candidates(predictive_candidate)
            return self.with_lomari_key_style_alternate_candidates(best_exact[1])

        if best_exact is not None:
            return self.with_lomari_key_style_alternate_candidates(best_exact[1])

        if predictive_candidate is not None:
            return self.with_lomari_key_style_alternate_candidates(predictive_candidate)

        return self.with_lomari_key_style_alternate_candidates(None)

    def maybe_show_hanri_candidates(self, force: bool = False) -> bool:
        """Show a small IME-style candidate popup when a dictionary item matches."""
        candidate = self.find_hanri_candidate(force=force)
        if not candidate:
            self.close_candidate_popup()
            return False

        # Do not recreate the same popup repeatedly.
        if (
            self.candidate
            and self.candidate.get('prefix') == candidate['prefix']
            and self.candidate.get('reading') == candidate['reading']
            and self.candidate.get('matched_text') == candidate.get('matched_text')
            and self.candidate.get('labels') == candidate.get('labels')
            and self.candidate.get('choice_readings') == candidate.get('choice_readings')
            and self.candidate.get('choice_auto_sandhi') == candidate.get('choice_auto_sandhi')
        ):
            return True

        self.candidate = candidate
        self.candidate_index = 0
        self.show_candidate_popup()
        return True

    def show_candidate_popup(self) -> None:
        self.close_candidate_popup(destroy_candidate=False)
        if not self.candidate:
            return

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes('-topmost', True)
        popup.configure(borderwidth=1, relief='solid')

        # Use a Text widget instead of a Listbox so tone marks can keep
        # their own Calibri font while Hanri/Hangul stay in Noto Sans.
        candidate_box = tk.Text(
            popup,
            height=min(len(self.candidate['labels']), 8),
            width=max(24, min(64, int((max(len(label) for label in self.candidate['labels']) + 10) * 2 / 3))),
            font=self.candidate_font,
            bd=0,
            highlightthickness=0,
            padx=6,
            pady=3,
            wrap='none',
            cursor='arrow',
        )
        candidate_box.pack(fill='both', expand=True)
        candidate_box.tag_configure('hanri_char', font=self.candidate_hanri_font)
        candidate_box.tag_configure('extension_b_hanri_char', font=self.candidate_extension_b_hanri_font)
        candidate_box.tag_configure('sc_hanri_char', font=self.candidate_sc_hanri_font)
        candidate_box.tag_configure('tone_mark', font=self.candidate_tone_font)
        candidate_box.tag_configure('selected_candidate', background='#3875d6', foreground='white')
        candidate_box.tag_raise('extension_b_hanri_char', 'hanri_char')
        candidate_box.tag_raise('sc_hanri_char', 'hanri_char')
        candidate_box.bind('<ButtonRelease-1>', self.on_candidate_click)

        self.candidate_popup = popup
        self.candidate_listbox = candidate_box
        self.refresh_candidate_popup_text()
        self.position_candidate_popup()
        self.start_candidate_visibility_monitor()
        self.text.focus_set()

    def position_candidate_popup(self) -> None:
        if not self.candidate_popup:
            return
        self.root.update_idletasks()
        bbox = self.text.bbox('insert')
        if bbox:
            x = self.text.winfo_rootx() + bbox[0]
            y = self.text.winfo_rooty() + bbox[1] + bbox[3] + 4
        else:
            x = self.text.winfo_rootx() + 8
            y = self.text.winfo_rooty() + self.text.winfo_height() - 8
        self.candidate_popup.geometry(f'+{x}+{y}')

    def close_candidate_popup(self, destroy_candidate: bool = True) -> None:
        if self.candidate_visibility_after_id is not None:
            try:
                self.root.after_cancel(self.candidate_visibility_after_id)
            except tk.TclError:
                pass
            self.candidate_visibility_after_id = None
        if self.candidate_popup is not None:
            try:
                self.candidate_popup.destroy()
            except tk.TclError:
                pass
        self.candidate_popup = None
        self.candidate_listbox = None
        if destroy_candidate:
            self.candidate = None
            self.candidate_index = 0

    def refresh_candidate_popup_text(self) -> None:
        if not self.candidate or self.candidate_listbox is None:
            return

        box = self.candidate_listbox
        box.configure(state='normal')
        box.delete('1.0', 'end')

        visible_tone_marks = set('ˆˋˊˉꞈˎˏˍ')
        for row, label in enumerate(self.candidate['labels']):
            line_start = box.index('end-1c')
            box.insert('end', label)
            line_end = box.index('end-1c')

            if row == self.candidate_index:
                box.tag_add('selected_candidate', line_start, line_end)

            # Use Noto Sans TC for Hanri/Chinese characters and Calibri for tone marks.
            tk_col = 0
            for ch in label:
                column_units = tk_text_column_units(ch)
                start = f'{row + 1}.{tk_col}'
                end = f'{row + 1}.{tk_col + column_units}'
                if is_hanri_char(ch):
                    box.tag_add('hanri_char', start, end)
                if is_cjk_extension_b_char(ch):
                    box.tag_add('extension_b_hanri_char', start, end)
                if ch in SC_FONT_HANRI_CHARS:
                    box.tag_add('sc_hanri_char', start, end)
                if ch in visible_tone_marks:
                    box.tag_add('tone_mark', start, end)
                tk_col += column_units

            if row != len(self.candidate['labels']) - 1:
                box.insert('end', '\n')

        box.configure(state='disabled')

    def set_candidate_index(self, index: int) -> None:
        if not self.candidate:
            return
        self.candidate_index = index % len(self.candidate['choices'])
        self.refresh_candidate_popup_text()

    def commit_candidate(self, index: int | None = None) -> None:
        if not self.candidate:
            return
        if index is None:
            index = self.candidate_index
        choice = self.candidate['choices'][index]
        choice_readings = self.candidate.get('choice_readings', [])
        choice_reading = choice_readings[index] if index < len(choice_readings) else None
        choice_auto_sandhi_flags = self.candidate.get('choice_auto_sandhi', [])
        choice_auto_sandhi = bool(choice_auto_sandhi_flags[index]) if index < len(choice_auto_sandhi_flags) else False
        self.push_undo_state()
        # There may now be more than one pure-Hangul option, e.g. a toneless
        # form and a toned form.  Treat choices without real Hanri/CJK as
        # pure-Hangul choices for suppression purposes, instead of assuming
        # only the final item is pure Hangul.
        chose_pure_hangul = not field_has_hanri(choice)

        prefix = self.candidate.get('prefix', '')
        suffix = self.candidate.get('suffix', '')
        replacement = prefix + choice

        self.composer.output = replacement + suffix
        self.composer.cursor_pos = len(replacement)
        self.composer.initial = self.composer.medial = self.composer.final = ''
        if choice_reading and field_is_plain_hanri(choice):
            self.remember_hanri_instance_reading(len(prefix), choice, choice_reading, auto_sandhi=choice_auto_sandhi)
        else:
            self.sync_hanri_instance_readings()
        self.key_history = []
        self.reset_lomari_buffer()
        # After any candidate is committed, do not immediately reopen another
        # Hanri menu for the resulting text when the next key is Space.
        # This matters for mixed Hanri+Hangul candidates: after converting a
        # longer word such as 림롷킈, the committed result may still end in a
        # shorter Hangul suffix such as 킈.  Pressing Space should continue
        # typing, not reopen 킈's menu.
        self.suppress_current_hanri_candidate_once()
        self.close_candidate_popup()

    def cancel_candidate_keep_hangul(self) -> None:
        # The text is already still Hangul; just dismiss the popup.
        self.close_candidate_popup()

    def on_candidate_click(self, event: tk.Event) -> str:
        if self.candidate_listbox is not None and self.candidate:
            try:
                index_text = self.candidate_listbox.index(f'@{event.x},{event.y}')
                line = int(index_text.split('.')[0]) - 1
            except Exception:
                line = self.candidate_index
            line = max(0, min(line, len(self.candidate['choices']) - 1))
            self.commit_candidate(line)
            self.render()
            self.text.focus_set()
        return 'break'

    def handle_candidate_key(self, key: str, char: str) -> str | None:
        """Handle keyboard choice when the Hanri popup is visible."""
        if not self.candidate:
            return None

        if key in {'Escape'}:
            self.cancel_candidate_keep_hangul()
            self.render()
            return 'break'
        # Only Up/Down/Tab navigate the Hanri candidate menu.
        # Physical Left/Right are handled before this function is called.
        if key == 'Up':
            self.set_candidate_index(self.candidate_index - 1)
            return 'break'
        if key in {'Down', 'Tab'}:
            self.set_candidate_index(self.candidate_index + 1)
            return 'break'
        if key == 'Return':
            self.commit_candidate()
            self.render()
            return 'break'
        # Number keys are reserved for Hokkien tone input, not candidate selection.
        # When a candidate popup is open and the user presses 1–5, dismiss the
        # old popup first, then let normal typing continue so the digit becomes
        # part of the reading, e.g. 랑 -> 랑4.  After insertion, on_keypress()
        # will run maybe_show_hanri_candidates() and rebuild the menu for 랑4.
        if char.isdigit():
            self.close_candidate_popup()
            return None
        if char == ' ':
            # Space means "keep the Hangul as typed" and continue typing.
            # It should not accept the highlighted Hanri candidate and should
            # not reopen/force the same menu again.
            self.cancel_candidate_keep_hangul()
            self.key_history = []
            self.push_undo_state()
            if not self.maybe_commit_lomari_pronoun_li_before_delimiter(char):
                self.reset_lomari_buffer()
            self.composer.insert_literal(' ')
            self.render()
            return 'break'

        # Continuing to type does not accept the default candidate automatically.
        # The popup is dismissed, the Hangul reading stays as-is, and normal
        # typing continues. A longer reading can then show its own popup.
        if char:
            self.cancel_candidate_keep_hangul()
            return None

        return 'break'

    def toggle_ime(self) -> str:
        self.ime_on.set(not self.ime_on.get())
        self.key_history = []
        self.close_candidate_popup()
        self.render()
        return 'break'

    def composer_snapshot(self) -> tuple[str, int, str, str, str, bool]:
        """Return the current composer state so a just-typed shortcut can be rewritten."""
        return (
            self.composer.output,
            self.composer.cursor_pos,
            self.composer.initial,
            self.composer.medial,
            self.composer.final,
            self.composer.e_to_ye_autocorrected,
        )

    def restore_composer_snapshot(self, snapshot: tuple[str, int, str, str, str] | tuple[str, int, str, str, str, bool]) -> None:
        (
            self.composer.output,
            self.composer.cursor_pos,
            self.composer.initial,
            self.composer.medial,
            self.composer.final,
            *rest,
        ) = snapshot
        self.composer.e_to_ye_autocorrected = bool(rest[0]) if rest else False
        self.composer.clamp_cursor()

    def raw_sequence_for_special_medial(self, initial: str, special_medial: str) -> str | None:
        """Return the raw Hokkien shortcut sequence for an initial+special vowel."""
        if special_medial in {'ᅷ', 'ᆤ'}:
            return None
        target = str(initial or '') + str(special_medial or '')
        for seq, mapped in HOKKIEN_SEQUENCE_MAP.items():
            if mapped == target:
                return seq
        return None

    def prepare_special_backspace_reinflate(self, info) -> None:
        """Let a peeled special vowel re-form when its last shortcut key is retyped.

        This remains for multi-key special-vowel shortcuts such as d+m+p -> ᄋힻ.
        k+n / i+n vowels deliberately do not reinflate here after Backspace;
        the user is left with the initial, matching the full-letter behavior.
        """
        if not isinstance(info, dict) or info.get('kind') != 'special_medial_peel':
            self.key_history = []
            return

        initial = str(info.get('initial', '') or '')
        special_medial = str(info.get('special_medial', '') or '')
        seq = self.raw_sequence_for_special_medial(initial, special_medial)
        if not seq or len(seq) < 2:
            self.key_history = []
            return

        # Only seed the already-typed prefix.  The next keypress supplies the
        # final shortcut key and process_hokkien_sequence_or_standard() will do
        # the normal restore+replace operation.
        base_output = self.composer.output
        base_cursor = self.composer.cursor_pos
        before_first = (base_output, base_cursor, '', '', '', False)
        history = [(seq[0], before_first)]
        if len(seq) >= 3:
            before_second = (base_output, base_cursor, initial, '', '', False)
            history.append((seq[1], before_second))
        self.key_history = history[-max(1, len(seq) - 1):]

    def apply_main_text_tone_font(self, content: str) -> None:
        # Main input uses Noto Sans KR by default for Hangul/Hokkien-Hangul,
        # Noto Sans TC for Hanri/Chinese characters, and Calibri for tone marks.
        self.text.tag_configure('hanri_char', font=self.hanri_font)
        self.text.tag_configure('extension_b_hanri_char', font=self.extension_b_hanri_font)
        self.text.tag_configure('sc_hanri_char', font=self.sc_hanri_font)
        self.text.tag_configure('tone_mark', font=self.tone_font)
        self.text.tag_remove('hanri_char', '1.0', 'end')
        self.text.tag_remove('extension_b_hanri_char', '1.0', 'end')
        self.text.tag_remove('sc_hanri_char', '1.0', 'end')
        self.text.tag_remove('tone_mark', '1.0', 'end')
        self.text.tag_raise('extension_b_hanri_char', 'hanri_char')
        self.text.tag_raise('sc_hanri_char', 'hanri_char')
        for idx, ch in enumerate(content):
            start = f'1.0+{idx}c'
            end = f'1.0+{idx + 1}c'
            if is_hanri_char(ch):
                self.text.tag_add('hanri_char', start, end)
            if is_cjk_extension_b_char(ch):
                self.text.tag_add('extension_b_hanri_char', start, end)
            if ch in SC_FONT_HANRI_CHARS:
                self.text.tag_add('sc_hanri_char', start, end)
            if ch in 'ˆˋˊˉꞈˎˏˍ':
                self.text.tag_add('tone_mark', start, end)

    def update_lomari_rules_visibility(self) -> None:
        """Keep the keyboard guide visible and positioned without repainting every keystroke."""
        self.update_keyboard_help_button_visibility()
        if self.keyboard_help_open:
            self.show_keyboard_help_for_current_window_state()

    def render(self) -> None:
        self.update_lomari_rules_visibility()
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        content = self.composer.text()
        self.text.insert('1.0', content)
        self.apply_main_text_tone_font(content)
        self.text.mark_set('insert', f'1.0+{self.composer.display_cursor_pos()}c')
        self.text.see('insert')
        self.update_roman_preview(content)
        self.refresh_modern_control_states()

    def flush_sequence_buffer(self, cancel_timer: bool = True) -> None:
        """Compatibility no-op: v0.4 has no delayed shortcut buffer."""
        self.key_history = []

    def render_lomari_raw_run(self) -> None:
        self.restore_composer_snapshot(self.lomari_start_snapshot)
        self.composer.insert_literal(
            convert_lomari_raw_to_hangul(
                self.lomari_raw,
                e_to_ye_autocorrect=self.e_to_ye_autocorrect_on.get(),
                lomari_key_style=self.lomari_key_style.get(),
            )
        )

    def maybe_commit_lomari_pronoun_li_before_delimiter(self, delimiter: str) -> bool:
        """Commit standalone Lomari li as pronoun 릐 before space/apostrophe."""
        if self.input_mode.get() != 'lomari' or self.lomari_start_snapshot is None:
            return False
        if delimiter not in {' ', "'", '’', '‘'}:
            return False

        raw = normalize_lomari_raw_for_matching(self.lomari_raw)
        if LOMARI_BOUNDARY_MARK in raw:
            return False

        standard_raw = apply_lomari_key_style_aliases(raw, self.lomari_key_style.get())
        if strip_reading_tones(standard_raw) != 'li':
            return False

        tone_suffix = ''.join(ch for ch in standard_raw[2:] if ch in TONE_DIGITS)
        self.restore_composer_snapshot(self.lomari_start_snapshot)
        self.composer.insert_literal(
            convert_lomari_raw_to_hangul(
                'lI' + tone_suffix,
                e_to_ye_autocorrect=self.e_to_ye_autocorrect_on.get(),
                lomari_key_style=LOMARI_KEY_STYLE_STANDARD,
            )
        )
        self.reset_lomari_buffer()
        return True

    def process_lomari_mode_char(self, char: str) -> None:
        """Process one QWERTY/Lomari key and convert the current roman run live."""
        if not char:
            return
        if char == '-':
            char = LOMARI_BOUNDARY_MARK

        is_lomari_unit = (
            (len(char) == 1 and char.isascii() and char.isalpha())
            or char in TONE_DIGITS
            or char in LOMARI_INPUT_TONE_SYMBOLS
            or char == LOMARI_BOUNDARY_MARK
        )

        if not is_lomari_unit:
            # Punctuation/space ends the current roman run.  The already-rendered
            # Hangul stays in the buffer, then the delimiter is inserted normally.
            if not self.maybe_commit_lomari_pronoun_li_before_delimiter(char):
                self.reset_lomari_buffer()
            self.composer.insert_literal(char)
            return

        if self.lomari_start_snapshot is None:
            self.lomari_start_snapshot = self.composer_snapshot()
            self.lomari_raw = ''

        self.lomari_raw += char

        # Re-render the whole active Lomari run from its starting point.
        # This lets a later letter refine an earlier temporary form while
        # preserving Shifted vowels for literal standalone vowel letters.
        self.render_lomari_raw_run()

    def process_bopomofo_mode_char(self, char: str) -> None:
        """Process one Bopomofo-style key and convert it into Tangliengim."""
        if not char:
            return
        if char in BOPOMOFO_SHIFT_VOWEL_KEYS:
            self.handle_bopomofo_vowel(BOPOMOFO_SHIFT_VOWEL_KEYS[char])
            return
        key = char.lower()

        if key == '-':
            self.insert_bopomofo_boundary()
            return

        self.reset_bopomofo_boundary()

        if key in BOPOMOFO_TONE_KEYS:
            digit = BOPOMOFO_TONE_KEYS[key]
            self.composer.insert_literal(digit)
            self.apply_tone_digit_display_to_latest_input(digit)
            return

        if key in BOPOMOFO_INITIAL_KEYS:
            self.handle_korean_key(BOPOMOFO_INITIAL_KEYS[key])
            return

        if key in BOPOMOFO_SYLLABIC_KEYS:
            self.handle_bopomofo_syllabic_key(BOPOMOFO_SYLLABIC_KEYS[key])
            return

        if key in BOPOMOFO_LITERAL_KEYS:
            self.handle_bopomofo_literal(BOPOMOFO_LITERAL_KEYS[key])
            return

        if key in BOPOMOFO_VOWEL_KEYS:
            self.handle_bopomofo_vowel(BOPOMOFO_VOWEL_KEYS[key])
            return

        if key in BOPOMOFO_RIME_KEYS:
            self.handle_bopomofo_rime(*BOPOMOFO_RIME_KEYS[key])
            return

        if key in BOPOMOFO_FINAL_KEYS:
            self.handle_bopomofo_final(BOPOMOFO_FINAL_KEYS[key])
            return

        if len(key) == 1 and key.isdigit():
            return

        self.composer.insert_literal(char)

    def handle_bopomofo_syllabic_key(self, compat: str) -> None:
        """Bopomofo y/h/n type 즈/츠/스 but remain open for later vowel combines."""
        initial = COMPAT_TO_L.get(compat, '')
        if not initial:
            self.composer.insert_literal(compat)
            return

        if self.composer.has_buffer():
            self.composer.commit()
        self.composer.add_initial(initial, source_compat=compat)
        self.composer.add_vowel('ᅳ')

    def handle_bopomofo_literal(self, text: str) -> None:
        """Insert a complete Bopomofo key value that should not compose further."""
        if self.composer.has_buffer():
            self.composer.commit()
        self.composer.insert_literal(text)

    def insert_bopomofo_boundary(self) -> None:
        """Insert a temporary syllable break for ambiguous Bopomofo input."""
        if self.bopomofo_boundary_marker_pos is not None:
            return
        if not self.composer.has_buffer() and not self.composer.output:
            return
        self.composer.commit()
        self.composer.insert_literal('-')
        self.bopomofo_boundary_marker_pos = self.composer.cursor_pos - 1

    def handle_bopomofo_vowel(self, compat: str) -> None:
        """Bopomofo vowel keys type full ㅇ-initial syllables when standalone."""
        medial = compat if compat in SPECIAL_MEDIALS else COMPAT_TO_V.get(compat, '')
        if not medial:
            self.composer.insert_literal(compat)
            return

        if compat == 'ᅷ' and self.composer.medial == 'ᅵ' and not self.composer.final:
            self.composer.medial = 'ᆤ'
            self.composer.e_to_ye_autocorrected = False
            return
        if compat == 'ㅏ' and self.composer.medial == 'ᅵ' and not self.composer.final:
            self.composer.medial = 'ᅣ'
            self.composer.e_to_ye_autocorrected = False
            return
        if compat == 'ㅔ' and self.composer.medial == 'ᅵ' and not self.composer.final:
            self.composer.medial = 'ᅨ'
            self.composer.e_to_ye_autocorrected = False
            return
        if compat == 'ㅏ' and self.composer.medial == 'ᅮ' and not self.composer.final:
            self.composer.medial = 'ᅪ'
            self.composer.e_to_ye_autocorrected = False
            return
        if compat == 'ㅐ' and self.composer.medial == 'ᅮ' and not self.composer.final:
            self.composer.medial = 'ᅫ'
            self.composer.e_to_ye_autocorrected = False
            return
        if compat == 'ㅓ' and self.composer.medial == 'ᅵ' and not self.composer.final:
            self.composer.medial = 'ᅧ'
            self.composer.e_to_ye_autocorrected = False
            return
        if compat == 'ㅗ' and self.composer.medial == 'ᅵ' and not self.composer.final:
            self.composer.medial = 'ᅭ'
            self.composer.e_to_ye_autocorrected = False
            return
        if compat == 'ㅜ' and self.composer.medial == 'ᅵ' and not self.composer.final:
            self.composer.medial = 'ᅲ'
            self.composer.e_to_ye_autocorrected = False
            return
        if (
            compat == 'ㅔ'
            and self.composer.initial in {'ᄌ', 'ᄎ', 'ᄉ'}
            and self.composer.medial == 'ᅳ'
            and not self.composer.final
        ):
            self.composer.medial = 'ힻ'
            self.composer.e_to_ye_autocorrected = False
            return
        if (
            self.composer.initial in {'ᄌ', 'ᄎ', 'ᄉ'}
            and self.composer.medial == 'ᅳ'
            and not self.composer.final
            and compat != 'ㅡ'
        ):
            combined = V_COMBINE.get((self.composer.medial, medial))
            self.composer.medial = combined or medial
            self.composer.e_to_ye_autocorrected = False
            return
        if self.composer.initial and self.composer.medial and not self.composer.final:
            blocked_bopomofo_combine = self.composer.medial == 'ᅩ' and medial in {'ᅡ', 'ᅢ'}
            combined = None if blocked_bopomofo_combine else V_COMBINE.get((self.composer.medial, medial))
            if combined:
                self.composer.medial = combined
                self.composer.e_to_ye_autocorrected = False
                return

        if not self.composer.has_buffer():
            self.composer.add_initial('ᄋ', source_compat='ㅇ')
            self.composer.add_vowel(medial)
            return

        if self.composer.initial and not self.composer.medial:
            self.composer.add_vowel(medial)
            return

        if self.composer.initial and self.composer.medial and self.composer.final:
            self.composer.add_vowel(medial)
            return

        self.composer.commit()
        self.composer.add_initial('ᄋ', source_compat='ㅇ')
        self.composer.add_vowel(medial)

    def handle_bopomofo_rime(self, medial: str, final: str) -> None:
        """Bopomofo rime keys type full rimes alone or attach to an initial."""
        if (
            self.composer.initial in {'ᄌ', 'ᄎ', 'ᄉ'}
            and self.composer.medial == 'ᅳ'
            and not self.composer.final
        ):
            self.composer.medial = medial
            self.composer.final = final
            self.composer.e_to_ye_autocorrected = False
            return

        if not self.composer.has_buffer():
            self.composer.add_initial('ᄋ', source_compat='ㅇ')
            self.composer.medial = medial
            self.composer.final = final
            self.composer.e_to_ye_autocorrected = False
            return

        if self.composer.initial and not self.composer.medial:
            self.composer.medial = medial
            self.composer.final = final
            self.composer.e_to_ye_autocorrected = False
            return

        if self.composer.initial and self.composer.medial and self.composer.final:
            self.composer.add_vowel(medial)
            self.set_bopomofo_current_final(final)
            return

        self.composer.commit()
        self.composer.add_initial('ᄋ', source_compat='ㅇ')
        self.composer.medial = medial
        self.composer.final = final
        self.composer.e_to_ye_autocorrected = False

    def handle_bopomofo_final(self, compat: str) -> None:
        """Bopomofo final keys attach as batchim, or type 은/음/응/을 alone."""
        final = COMPAT_TO_T.get(compat, '')
        if not final:
            self.composer.insert_literal(compat)
            return

        if not self.composer.has_buffer():
            if compat == 'ㄹ':
                self.composer.insert_literal('ㄹ')
                return
            self.start_bopomofo_standalone_final(final)
            return

        if self.composer.initial and not self.composer.medial:
            self.composer.medial = 'ᅳ'
            self.set_bopomofo_current_final(final)
            return

        if self.composer.initial and self.composer.medial and not self.composer.final:
            self.adjust_bopomofo_ng_medial(final)
            self.set_bopomofo_current_final(final)
            return

        self.composer.commit()
        self.start_bopomofo_standalone_final(final)

    def start_bopomofo_standalone_final(self, final: str) -> None:
        self.composer.add_initial('ᄋ', source_compat='ㅇ')
        self.composer.medial = 'ᅳ'
        self.set_bopomofo_current_final(final)

    def set_bopomofo_current_final(self, final: str) -> None:
        self.composer.final = final
        if (
            self.composer.should_use_e_to_ye_autocorrect()
            and should_autocorrect_e_to_ye_before_final(self.composer.initial, self.composer.medial, self.composer.final)
        ):
            self.composer.medial = 'ᅨ'
            self.composer.e_to_ye_autocorrected = True
        else:
            self.composer.e_to_ye_autocorrected = False

    def adjust_bopomofo_ng_medial(self, final: str) -> None:
        """ㄥ-style final makes ㄨㄥ/ㄜㄥ -> 엉 and ㄩㄥ -> 영."""
        if final != 'ᆼ':
            return
        if self.composer.medial in {'ᅮ', 'ᅥ'}:
            self.composer.medial = 'ᅥ'
        elif self.composer.medial == 'ᅲ':
            self.composer.medial = 'ᅧ'

    def backspace_lomari_mode(self) -> bool:
        """Backspace one raw Lomari character when a Lomari run is active."""
        if self.input_mode.get() != 'lomari' or self.lomari_start_snapshot is None:
            return False

        self.lomari_raw = self.lomari_raw[:-1]
        self.restore_composer_snapshot(self.lomari_start_snapshot)
        if self.lomari_raw:
            self.composer.insert_literal(
                convert_lomari_raw_to_hangul(
                    self.lomari_raw,
                    e_to_ye_autocorrect=self.e_to_ye_autocorrect_on.get(),
                    lomari_key_style=self.lomari_key_style.get(),
                )
            )
        else:
            self.reset_lomari_buffer()
        return True

    def process_standard_ime_char(self, char: str) -> None:
        """Process one printable key without checking raw Hokkien shortcut sequences."""
        if char in KEY_TO_JAMO:
            self.handle_korean_key(KEY_TO_JAMO[char])
            return

        # Tone digits, punctuation, spaces, Chinese characters, etc. are inserted literally.
        self.composer.insert_literal(char)

    def start_mapped_cluster_as_buffer(self, mapped: str) -> None:
        """Start a Hokkien shortcut result as the active composing buffer.

        Older versions inserted shortcut results literally.  That made mdkf
        become ᅙᅡㄹ, because ᅙᅡ had already been committed and ㄹ became a
        standalone compatibility jamo.  Keeping a mapped initial+medial cluster
        in the composer buffer lets the next consonant become batchim, e.g.
        mdkf -> ᅙᅡᆯ and dmpf -> ᄋힻᆯ.
        """
        self.composer.commit()

        if len(mapped) >= 2 and is_initial_jamo(mapped[0]) and is_vowel_jamo(mapped[1]):
            self.composer.initial = mapped[0]
            self.composer.medial = mapped[1]
            if len(mapped) >= 3 and mapped[2] in T_INDEX:
                self.composer.final = mapped[2]
            else:
                self.composer.final = ''
            if len(mapped) > 3:
                self.composer.commit()
                self.composer.insert_literal(mapped[3:])
            return

        self.composer.insert_literal(mapped)

    def process_hokkien_sequence_or_standard(self, char: str) -> None:
        """
        Process normal Korean input immediately.

        If the most recent raw keys complete a Hokkien shortcut such as dmp,
        restore the composer to the state before that sequence and start the
        special cluster as the current composing syllable. This means fkd
        becomes 랑 immediately, while dmp becomes ᄋힻ and dmpf can continue
        as ᄋힻᆯ.
        """
        char = normalize_keyboard_char(char)

        if char not in KEY_TO_JAMO:
            self.process_standard_ime_char(char)
            self.key_history = []
            return

        before = self.composer_snapshot()
        self.process_standard_ime_char(char)
        self.key_history.append((char, before))

        max_len = max(len(seq) for seq in HOKKIEN_SEQUENCE_MAP)
        if len(self.key_history) > max_len:
            self.key_history = self.key_history[-max_len:]

        raw_tail = ''.join(ch for ch, _snapshot in self.key_history)
        for seq, mapped in sorted(HOKKIEN_SEQUENCE_MAP.items(), key=lambda item: -len(item[0])):
            if raw_tail.endswith(seq):
                start_index = len(self.key_history) - len(seq)
                restore_snapshot = self.key_history[start_index][1]
                self.restore_composer_snapshot(restore_snapshot)
                # Start mapped initial+medial clusters as a composing buffer so
                # a following consonant can become batchim.
                self.start_mapped_cluster_as_buffer(mapped)
                self.key_history = []
                return

    def event_has_alt_modifier(self, event: tk.Event) -> bool:
        """Return True only for a real Alt/Mod1 digit shortcut.

        v2.12 treated several Tk modifier bits as Alt.  On some Windows/Tk
        setups those bits can appear on ordinary number-key events, making
        normal Hangul+1/2/3/4/5 become literal numbers instead of tone marks.
        Windows reliably reports the high Alt bit; non-Windows builds can keep
        using the normal Mod1 bit.
        """
        state = int(getattr(event, 'state', 0) or 0)
        if sys.platform.startswith('win'):
            return bool(state & 0x20000)
        return bool(state & 0x0008)

    def literal_digit_from_event(self, event: tk.Event) -> str | None:
        """Return the digit requested by Alt+digit, if any."""
        if not self.event_has_alt_modifier(event):
            return None
        key = str(getattr(event, 'keysym', '') or '')
        char = str(getattr(event, 'char', '') or '')
        if len(char) == 1 and char in ARABIC_NUMERAL_DIGITS:
            return char
        if len(key) == 1 and key in ARABIC_NUMERAL_DIGITS:
            return key
        if key.startswith('KP_') and key[3:] in ARABIC_NUMERAL_DIGITS:
            return key[3:]
        return None

    def insert_literal_arabic_digit(self, digit: str) -> None:
        """Insert a visible Arabic numeral that is not a tone marker."""
        self.close_candidate_popup()
        self.key_history = []
        self.reset_lomari_buffer()
        self.composer.commit()
        self.composer.insert_literal(LITERAL_DIGIT_MARK + str(digit))

    def on_alt_digit_keypress(self, event: tk.Event) -> str:
        """Insert Alt+digit as a pronounceable literal Arabic numeral.

        This exact binding is the preferred path for Alt+digit.  The generic
        handler still has a fallback, but ordinary digit keys must never pass
        through this path unless Alt was actually part of the key sequence.
        """
        self.set_keyboard_guide_physical_key_pressed(self.keyboard_guide_key_from_event(event), True)
        if self.input_mode.get() == 'bopomofo':
            return 'break'
        digit = self.literal_digit_from_event(event)
        if digit is None:
            key = str(getattr(event, 'keysym', '') or '')
            char = str(getattr(event, 'char', '') or '')
            if len(char) == 1 and char in ARABIC_NUMERAL_DIGITS:
                digit = char
            elif len(key) == 1 and key in ARABIC_NUMERAL_DIGITS:
                digit = key
            elif key.startswith('KP_') and key[3:] in ARABIC_NUMERAL_DIGITS:
                digit = key[3:]
        if digit is None:
            return 'break'

        replacing_selection = self.selected_offsets() is not None
        if replacing_selection:
            self.push_undo_state()
            self.delete_selection_if_any(push_undo=False)
        else:
            self.push_undo_state()
        self.insert_literal_arabic_digit(digit)
        self.render()
        self.maybe_show_hanri_candidates()
        return 'break'

    def bopomofo_ctrl_punctuation(self, event: tk.Event) -> str | None:
        """Ctrl+punctuation inserts literal punctuation in Bopomofo mode."""
        if self.input_mode.get() != 'bopomofo':
            return None
        if not (int(getattr(event, 'state', 0) or 0) & 0x4):
            return None

        key = str(getattr(event, 'keysym', '') or '')
        char = str(getattr(event, 'char', '') or '')
        punctuation_by_key = {
            'comma': ',',
            'period': '.',
            'slash': '/',
            'semicolon': ';',
        }
        punctuation = punctuation_by_key.get(key)
        if punctuation is None and char in {',', '.', '/', ';'}:
            punctuation = char
        if punctuation is None:
            return None

        replacing_selection = self.selected_offsets() is not None
        if replacing_selection:
            self.push_undo_state()
            self.delete_selection_if_any(push_undo=False)
        else:
            self.push_undo_state()
        self.close_candidate_popup()
        self.key_history = []
        self.reset_lomari_buffer()
        self.reset_bopomofo_boundary()
        self.composer.insert_literal(punctuation)
        self.render()
        self.maybe_show_hanri_candidates()
        return 'break'

    def on_keypress(self, event: tk.Event) -> str | None:
        key = event.keysym
        char = event.char
        self.keep_text_cursor_steady_while_typing()
        guide_key = self.keyboard_guide_key_from_event(event)
        self.set_keyboard_guide_physical_key_pressed(guide_key, True)
        if guide_key == 'Shift':
            self.set_keyboard_guide_shifted(True)
        if guide_key == 'Ctrl':
            self.set_keyboard_guide_ctrled(True)

        if key == 'Alt_R':
            return self.toggle_ime()

        if key in {'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L'}:
            return None

        # Keyboard shortcuts must work even when the candidate popup is open.
        if (event.state & 0x4) and key.lower() == 'z':
            return self.undo_last_action()
        if (event.state & 0x4) and key.lower() == 'y':
            return self.redo_last_action()
        if (event.state & 0x4) and key.lower() == 'x':
            return self.cut_selection()
        if (event.state & 0x4) and key.lower() == 'c':
            return self.copy_selection_or_all(event)
        if (event.state & 0x4) and key.lower() == 'a':
            return self.select_all_main_text(event)
        if (event.state & 0x4) and key.lower() == 'v':
            return self.paste_raw_clipboard()
        ctrl_punctuation_result = self.bopomofo_ctrl_punctuation(event)
        if ctrl_punctuation_result == 'break':
            return 'break'

        # Left/Right always control the IME text cursor, even while the
        # Hanri candidate popup is open.  Handle them before candidate-menu
        # dispatch so no popup fallback can swallow the arrow event.
        if key == 'Left':
            self.close_candidate_popup()
            self.key_history = []
            self.reset_lomari_buffer()
            self.composer.move_left()
            self.render()
            return 'break'
        if key == 'Right':
            self.close_candidate_popup()
            self.key_history = []
            self.reset_lomari_buffer()
            self.composer.move_right()
            self.render()
            return 'break'

        candidate_result = self.handle_candidate_key(key, char)
        if candidate_result == 'break':
            return 'break'

        literal_digit = self.literal_digit_from_event(event)
        if literal_digit is not None and self.input_mode.get() != 'bopomofo':
            replacing_selection = self.selected_offsets() is not None
            if replacing_selection:
                self.push_undo_state()
                self.delete_selection_if_any(push_undo=False)
            else:
                self.push_undo_state()
            self.insert_literal_arabic_digit(literal_digit)
            self.render()
            self.maybe_show_hanri_candidates()
            return 'break'

        if key == 'F6':
            self.copy_text()
            return 'break'
        if key == 'F7':
            self.clear()
            return 'break'
        if key == 'F8':
            self.toggle_hanri()
            return 'break'
        if key == 'BackSpace':
            if self.delete_selection_if_any():
                self.reset_lomari_buffer()
                self.render()
                return 'break'
            self.close_candidate_popup()
            self.key_history = []
            self.push_undo_state()
            if self.backspace_lomari_mode():
                self.render()
                self.maybe_show_hanri_candidates()
                return 'break'
            self.reset_lomari_buffer()
            backspace_info = self.composer.backspace()
            self.prepare_special_backspace_reinflate(backspace_info)
            self.render()
            return 'break'
        if key == 'Up':
            if self.candidate:
                self.set_candidate_index(self.candidate_index - 1)
            else:
                self.close_candidate_popup()
                self.key_history = []
                self.reset_lomari_buffer()
                self.move_cursor_vertically(-1)
                self.render()
            return 'break'
        if key == 'Down':
            if self.candidate:
                self.set_candidate_index(self.candidate_index + 1)
            else:
                self.close_candidate_popup()
                self.key_history = []
                self.reset_lomari_buffer()
                self.move_cursor_vertically(1)
                self.render()
            return 'break'
        if char == '<' and self.input_mode.get() != 'bopomofo':
            self.close_candidate_popup()
            self.key_history = []
            self.reset_lomari_buffer()
            self.composer.move_left()
            self.render()
            return 'break'
        if char == '>' and self.input_mode.get() != 'bopomofo':
            self.close_candidate_popup()
            self.key_history = []
            self.reset_lomari_buffer()
            self.composer.move_right()
            self.render()
            return 'break'
        if key == 'Return':
            # Enter inserts a line break in the typing box.
            # If a Hanri candidate popup is already open, handle_candidate_key()
            # above still lets Enter choose the highlighted candidate.
            self.close_candidate_popup()
            self.flush_sequence_buffer()
            self.reset_lomari_buffer()
            self.push_undo_state()
            self.composer.insert_literal('\n')
            self.render()
            return 'break'
        if key == 'Escape':
            self.close_candidate_popup()
            self.key_history = []
            self.reset_lomari_buffer()
            self.push_undo_state()
            self.composer.commit()
            self.render()
            return 'break'

        # Let copy/select shortcuts work normally. Paste/cut/undo are handled above.
        if (event.state & 0x4) and key.lower() in {'c', 'a'}:
            return None

        if not char:
            return 'break'

        # If the user selected text with the mouse, normal typing replaces it.
        replacing_selection = self.selected_offsets() is not None
        if replacing_selection:
            self.push_undo_state()
            self.delete_selection_if_any(push_undo=False)

        char = self.normalize_apostrophe_input(char)

        # Space keeps the current Hangul text as typed.  Candidate conversion
        # is handled by Enter/clicking the popup; Space must not force-open or
        # accept the Hanri menu.

        if not self.ime_on.get():
            self.close_candidate_popup()
            self.key_history = []
            self.reset_lomari_buffer()
            if not replacing_selection:
                self.push_undo_state()
            self.composer.insert_literal(char)
            self.render()
            return 'break'

        if not replacing_selection:
            self.push_undo_state()
        if self.input_mode.get() == 'lomari':
            self.key_history = []
            self.process_lomari_mode_char(char)
        elif self.input_mode.get() == 'bopomofo':
            self.key_history = []
            self.reset_lomari_buffer()
            self.process_bopomofo_mode_char(char)
        else:
            self.reset_lomari_buffer()
            self.process_hokkien_sequence_or_standard(char)
            if char in TONE_DIGITS:
                self.apply_tone_digit_display_to_latest_input(char)
        self.render()
        self.maybe_show_hanri_candidates()
        return 'break'

    def handle_korean_key(self, compat: str) -> None:
        if compat in COMPAT_TO_V:
            self.composer.add_vowel(COMPAT_TO_V[compat])
        elif compat in SPECIAL_MEDIALS:
            if not self.composer.has_buffer():
                self.composer.insert_literal('\u115F' + compat)
            else:
                self.composer.add_vowel(compat)
        elif compat in COMPAT_TO_L:
            self.composer.add_initial(COMPAT_TO_L[compat], source_compat=compat)
        else:
            self.composer.insert_literal(compat)

    def handle_special_mapped(self, mapped: str) -> None:
        if mapped in SPECIAL_MEDIALS:
            self.composer.add_vowel(mapped)
        elif mapped in EXTRA_INITIALS:
            self.composer.add_initial(mapped)
        else:
            # Direct clusters should not merge into the current composing syllable.
            self.composer.insert_literal(mapped)

    def insert_custom(self, value: str) -> None:
        self.push_undo_state()
        self.flush_sequence_buffer()
        if value in SPECIAL_MEDIALS:
            self.composer.add_vowel(value)
        elif value in EXTRA_INITIALS:
            self.composer.add_initial(value)
        else:
            self.composer.insert_literal(value)
        self.render()
        self.text.focus_set()

    def commit_buffer(self) -> None:
        self.push_undo_state()
        self.flush_sequence_buffer()
        self.composer.commit()
        self.render()
        self.text.focus_set()

    def copy_text(self) -> str:
        self.close_candidate_popup()
        self.flush_sequence_buffer()
        self.reset_lomari_buffer()
        self.composer.commit()
        content = self.clipboard_plain_text(self.composer.text())
        self.set_system_clipboard_text(content)
        self.render()
        self.status.configure(text=self.tr('copied'))
        self.text.focus_set()
        return 'break'

    def choose_ambiguous_reverse_sandhi_reading(self, hanri: str, item: dict) -> str | None:
        """Ask whether ambiguous surface tone 3 came from citation tone 4 or 5.

        Returns the selected TSV reading.  None means "No": skip this TSV row
        but continue the HTML-copy workflow.
        """
        options = item.get('reverse_sandhi_options') or []
        by_tone = {str(option.get('tone', '')): option.get('reading', '') for option in options}
        if '4' not in by_tone or '5' not in by_tone:
            return item.get('reading', '')

        result = {'reading': None}
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr('confirm_hanri'))
        dialog.transient(self.root)
        dialog.resizable(False, False)

        surface_display = item.get('surface_display') or item.get('surface_reading') or ''
        prompt = (
            f'{hanri} ({surface_display})\n\n'
            f'{self.tr("ambiguous_prompt")}'
        )
        ttk.Label(
            dialog,
            text=prompt,
            justify='left',
            padding=(18, 16, 18, 12),
        ).pack(fill='x')

        button_row = ttk.Frame(dialog, padding=(12, 0, 12, 14))
        button_row.pack(fill='x')

        def finish(reading: str | None) -> None:
            result['reading'] = reading
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        ttk.Button(
            button_row,
            text=self.tr('yes_tone_4'),
            command=lambda: finish(by_tone['4']),
        ).pack(side='left', padx=(0, 6))
        ttk.Button(
            button_row,
            text=self.tr('yes_tone_5'),
            command=lambda: finish(by_tone['5']),
        ).pack(side='left', padx=6)
        ttk.Button(
            button_row,
            text=self.tr('no'),
            command=lambda: finish(None),
        ).pack(side='left', padx=(6, 0))

        dialog.protocol('WM_DELETE_WINDOW', lambda: finish(None))
        dialog.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_reqheight()) // 2)
            dialog.geometry(f'+{x}+{y}')
        except Exception:
            pass

        dialog.grab_set()
        dialog.wait_window()
        return result['reading']

    def ask_add_tsv_confirmation(self, hanri: str, display: str, message: str | None = None) -> bool:
        """Ask whether to append a bracketed Hanri reading, using larger text."""
        result = {'confirmed': False}
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr('confirm_hanri'))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=getattr(self, 'surface_bg', '#f8fafd'))

        prompt = f'{hanri} ({display})\n\n{message or self.tr("add_tsv")}'
        tk.Label(
            dialog,
            text=prompt,
            justify='left',
            bg=getattr(self, 'surface_bg', '#f8fafd'),
            fg='#202124',
            font=(self.hangul_font_family, 14),
            padx=22,
            pady=18,
        ).pack(fill='x')

        button_row = ttk.Frame(dialog, padding=(14, 0, 14, 16))
        button_row.pack(fill='x')

        def finish(confirmed: bool) -> None:
            result['confirmed'] = confirmed
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        ttk.Button(
            button_row,
            text=self.tr('yes'),
            command=lambda: finish(True),
        ).pack(side='left', padx=(0, 8))
        ttk.Button(
            button_row,
            text=self.tr('no'),
            command=lambda: finish(False),
        ).pack(side='left', padx=(8, 0))

        dialog.protocol('WM_DELETE_WINDOW', lambda: finish(False))
        dialog.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_reqheight()) // 2)
            dialog.geometry(f'+{x}+{y}')
        except Exception:
            pass

        dialog.grab_set()
        dialog.wait_window()
        return bool(result['confirmed'])

    def split_converter_hanri_hangul_bracket(self, converter, inner: str):
        if hasattr(converter, 'split_hanri_hangul_bracket'):
            try:
                return converter.split_hanri_hangul_bracket(inner)
            except Exception:
                return None
        return split_hanri_hangul_bracket_inner(inner)

    def converter_existing_hanri_readings(self, converter, hanri: str) -> list[str]:
        if not hanri or not hasattr(converter, 'existing_hanri_readings'):
            return []
        try:
            return [
                normalize_tone_symbols_to_digits(str(reading or ''))
                for reading in converter.existing_hanri_readings(hanri)
                if str(reading or '').strip()
            ]
        except Exception:
            return []

    def suffix_join_reading_proposal(self, converter, hanri: str, reading: str, suffix: str):
        combined_hanri = f'{hanri}{suffix}'
        combined_readings = self.converter_existing_hanri_readings(converter, combined_hanri)
        suffix_readings = self.converter_existing_hanri_readings(converter, suffix)
        if not suffix_readings:
            return None

        suffix_reading = suffix_readings[0]
        if combined_readings:
            combined_reading = combined_readings[0]
        else:
            combined_reading = normalize_tone_symbols_to_digits(reading) + suffix_reading

        if not combined_reading:
            return None
        return combined_hanri, combined_reading, suffix_reading

    def raw_hanri_suffix_join_match(self, converter, source: str, index: int):
        if index >= len(source) or not is_hanri_char(source[index]):
            return None
        if not hasattr(converter, 'tsv_hanri_match_info'):
            return None
        try:
            match = converter.tsv_hanri_match_info(source, index)
        except Exception:
            match = None
        if not match:
            return None

        hanri, surface_reading, _sandhi_applied = match
        if not hanri:
            return None
        suffix_index = index + len(hanri)
        if suffix_index >= len(source):
            return None
        suffix = source[suffix_index]
        if suffix not in HTML_JOINABLE_SUFFIX_HANRI:
            return None
        if not is_html_joinable_suffix_boundary(source, suffix_index):
            return None

        surface_reading = normalize_tone_symbols_to_digits(surface_reading)
        if not surface_reading:
            return None
        proposal = self.suffix_join_reading_proposal(converter, hanri, surface_reading, suffix)
        if not proposal:
            return None
        return hanri, surface_reading, suffix, proposal

    def ask_join_suffix_confirmation(
        self,
        hanri: str,
        reading: str,
        suffix: str,
        suffix_reading: str,
        combined_hanri: str,
        combined_reading: str,
    ) -> bool:
        message = self.tr(
            'join_suffix_tsv',
            hanri=hanri,
            reading=format_text_tones_for_output(reading, True),
            suffix=suffix,
            suffix_reading=format_text_tones_for_output(suffix_reading, True),
            combined_hanri=combined_hanri,
            combined_reading=format_text_tones_for_output(combined_reading, True),
        )
        return bool(messagebox.askyesno(self.tr('copy_html_dialog'), message, parent=self.root))

    def resolve_suffix_join_annotations(
        self,
        converter,
        content: str,
        decisions: dict | None = None,
        prompt: bool = True,
    ) -> tuple[str, set[tuple[str, str]], dict]:
        decisions = {} if decisions is None else decisions
        source = str(content or '')
        generated_readings: set[tuple[str, str]] = set()
        out: list[str] = []
        i = 0

        def compatible_prior_decision(hanri: str, suffix: str, combined_hanri: str):
            for prior_key, prior_decision in decisions.items():
                if (
                    isinstance(prior_key, tuple)
                    and len(prior_key) >= 5
                    and prior_key[0] == hanri
                    and prior_key[2] == suffix
                    and prior_key[3] == combined_hanri
                ):
                    return bool(prior_decision), str(prior_key[4] or '')
            return None

        while i < len(source):
            if source[i] == '[':
                closing = source.find(']', i + 1)
                if closing == -1:
                    out.append(source[i])
                    i += 1
                    continue

                if closing + 1 >= len(source):
                    out.append(source[i:closing + 1])
                    i = closing + 1
                    continue

                suffix = source[closing + 1]
                if suffix not in HTML_JOINABLE_SUFFIX_HANRI:
                    out.append(source[i:closing + 1])
                    i = closing + 1
                    continue
                if not is_html_joinable_suffix_boundary(source, closing + 1):
                    out.append(source[i:closing + 1])
                    i = closing + 1
                    continue

                parsed = self.split_converter_hanri_hangul_bracket(converter, source[i + 1:closing])
                if not parsed:
                    out.append(source[i:closing + 1])
                    i = closing + 1
                    continue

                hanri, reading = parsed
                proposal = self.suffix_join_reading_proposal(converter, hanri, reading, suffix)
                if not proposal:
                    out.append(source[i:closing + 1])
                    i = closing + 1
                    continue

                combined_hanri, combined_reading, suffix_reading = proposal
                advance_to = closing + 2
            else:
                raw_match = self.raw_hanri_suffix_join_match(converter, source, i)
                if not raw_match:
                    out.append(source[i])
                    i += 1
                    continue
                hanri, reading, suffix, proposal = raw_match
                combined_hanri, combined_reading, suffix_reading = proposal
                advance_to = i + len(hanri) + 1

            key = (
                hanri,
                normalize_tone_symbols_to_digits(reading),
                suffix,
                combined_hanri,
                normalize_tone_symbols_to_digits(combined_reading),
            )
            if key not in decisions:
                prior = compatible_prior_decision(hanri, suffix, combined_hanri)
                if prior is not None:
                    prior_decision, prior_combined_reading = prior
                    decisions[key] = prior_decision
                    if prior_decision and prior_combined_reading:
                        combined_reading = prior_combined_reading
                else:
                    decisions[key] = (
                        self.ask_join_suffix_confirmation(
                            hanri,
                            reading,
                            suffix,
                            suffix_reading,
                            combined_hanri,
                            combined_reading,
                        )
                        if prompt else False
                    )

            if decisions.get(key):
                display_reading = format_text_tones_for_output(combined_reading, True)
                out.append(f'[{combined_hanri}{display_reading}]')
                generated_readings.add((combined_hanri, normalize_tone_symbols_to_digits(combined_reading)))
                i = advance_to
                continue

            if source[i] == '[':
                out.append(source[i:closing + 1])
                i = closing + 1
            else:
                out.append(source[i])
                i += 1

        return ''.join(out), generated_readings, decisions

    def confirm_and_save_bracketed_hanri_annotations(
        self,
        converter,
        content: str,
        skip_generated_readings: set[tuple[str, str]] | None = None,
    ) -> bool:
        if not hasattr(converter, 'hanri_hangul_bracket_annotations'):
            self.last_identical_tsv_detected = False
            return True

        annotations = converter.hanri_hangul_bracket_annotations(content)
        if not annotations:
            self.last_identical_tsv_detected = False
            return True

        identical_entry_detected = False
        skip_generated_readings = skip_generated_readings or set()

        for item in annotations:
            hanri = item.get('hanri', '')
            reading = item.get('reading', '')
            display = item.get('display', reading)
            reverse_options = item.get('reverse_sandhi_options') or []
            confirmed_by_disambiguation = False
            normalized_reading = normalize_tone_symbols_to_digits(reading)
            normalized_surface = normalize_tone_symbols_to_digits(str(item.get('surface_reading', '') or ''))

            if (
                (hanri, normalized_reading) in skip_generated_readings
                or (hanri, normalized_surface) in skip_generated_readings
            ):
                continue

            if (
                hasattr(converter, 'hanri_reading_entry_exists')
                and converter.hanri_reading_entry_exists(hanri, reading)
            ):
                identical_entry_detected = True
                continue

            existing_readings = []
            if hasattr(converter, 'existing_hanri_readings'):
                try:
                    existing_readings = converter.existing_hanri_readings(hanri)
                except Exception:
                    existing_readings = []

            ambiguous_tones = {str(option.get('tone', '')) for option in reverse_options}
            if reverse_options and hasattr(converter, 'hanri_reading_entry_exists'):
                reverse_existing = any(
                    converter.hanri_reading_entry_exists(hanri, option.get('reading', ''))
                    for option in reverse_options
                )
                if reverse_existing:
                    identical_entry_detected = True
                    continue
            if reverse_options and existing_readings and hasattr(converter, 'citation_to_sandhi_reading'):
                surface_reading = normalize_tone_symbols_to_digits(str(item.get('surface_reading', '') or ''))

                def sandhi_surface_matches(existing_sandhi: str, surface: str) -> bool:
                    existing_norm = normalize_tone_symbols_to_digits(existing_sandhi)
                    surface_norm = normalize_tone_symbols_to_digits(surface)
                    if existing_norm == surface_norm:
                        return True
                    # Tone 3 is normally unmarked in bracket input.  Therefore
                    # an existing citation reading whose sandhi is 함3 should
                    # match a bracketed surface reading written as plain 함.
                    return (
                        not reading_has_tones(surface_norm)
                        and existing_norm == surface_norm + '3'
                    )

                existing_sandhi_matches_surface = False
                for existing_reading in existing_readings:
                    try:
                        existing_sandhi = converter.citation_to_sandhi_reading(existing_reading) or ''
                    except Exception:
                        existing_sandhi = ''
                    if sandhi_surface_matches(existing_sandhi, surface_reading):
                        existing_sandhi_matches_surface = True
                        break
                if existing_sandhi_matches_surface:
                    identical_entry_detected = True
                    continue

            if {'4', '5'}.issubset(ambiguous_tones):
                reading = self.choose_ambiguous_reverse_sandhi_reading(hanri, item)
                if not reading:
                    # "No" means do not save this row.  HTML conversion/copy
                    # must still continue.
                    continue
                confirmed_by_disambiguation = True
            else:
                pass

            if (
                hasattr(converter, 'hanri_reading_entry_exists')
                and converter.hanri_reading_entry_exists(hanri, reading)
            ):
                identical_entry_detected = True
                continue

            if existing_readings:
                existing_display = ', '.join(
                    format_text_tones_for_output(value, True)
                    for value in existing_readings[:6]
                )
                if len(existing_readings) > 6:
                    existing_display += f', ... +{len(existing_readings) - 6}'
                message = self.tr('different_tsv', existing=existing_display)
                if not self.ask_add_tsv_confirmation(hanri, display, message=message):
                    continue
            elif not confirmed_by_disambiguation and not self.ask_add_tsv_confirmation(hanri, display):
                # Skip only the TSV append; do not cancel HTML copying.
                continue

            if hasattr(converter, 'append_hanri_reading_to_tsv'):
                if converter.append_hanri_reading_to_tsv(hanri, reading):
                    reload_hanri_resources()

        self.last_identical_tsv_detected = identical_entry_detected
        return True

    def copy_as_html(self) -> str:
        self.close_candidate_popup()
        self.flush_sequence_buffer()
        self.reset_lomari_buffer()
        self.composer.commit()

        content = format_text_tones_for_output(
            self.composer.text(),
            True,
            keep_literal_digit_markers=True,
        ).replace(LITERAL_DIGIT_MARK, '')

        try:
            converter = self.load_tone_marker_module()
            suffix_join_decisions = {}
            if self.html_style.get() == 'lomari_next_line':
                self.last_identical_tsv_detected = False
            elif not self.confirm_and_save_bracketed_hanri_annotations(
                converter,
                content,
            ):
                self.text.focus_set()
                return 'break'
            elif self.html_style.get() != 'lomari_next_line':
                _conversion_content, _generated_suffix_readings, suffix_join_decisions = (
                    self.resolve_suffix_join_annotations(converter, content)
                )
            html_content = format_text_tones_for_output(
                self.text_with_hanri_instance_readings(self.composer.text()),
                True,
                keep_literal_digit_markers=True,
            ).replace(LITERAL_DIGIT_MARK, '')
            if self.html_style.get() != 'lomari_next_line':
                html_content, _, suffix_join_decisions = self.resolve_suffix_join_annotations(
                    converter,
                    html_content,
                    decisions=suffix_join_decisions,
                    prompt=False,
                )
            result = converter.convert_hangul_to_html(html_content, self.html_style.get())
            self.set_system_clipboard_text(result['html'])
            style_label = {
                'plain': self.tr('html_plain'),
                'lomari_ruby_below': self.tr('html_lomari_ruby_below'),
                'lomari_next_line': self.tr('html_lomari_next_line'),
                'song': self.tr('html_song'),
                'novel': self.tr('html_novel'),
                'novel_first': self.tr('html_novel_first'),
                'title': self.tr('html_title'),
            }.get(self.html_style.get(), 'HTML')
            if getattr(self, 'last_identical_tsv_detected', False):
                status = self.tr('copied_html_identical_tsv')
                self.last_identical_tsv_detected = False
            else:
                status = self.tr('copied_html', style=style_label)
            if result.get('tone_autocorrected'):
                status += self.tr('tone_autocorrected')
            self.status.configure(text=status)
        except Exception as exc:
            self.status.configure(text=self.tr('html_error', error=exc))
            try:
                messagebox.showerror(self.tr('copy_html_dialog'), str(exc))
            except Exception:
                pass

        self.text.focus_set()
        return 'break'

    def paste_raw_clipboard(self) -> str:
        content = ''
        try:
            content = self.root.clipboard_get()
        except tk.TclError:
            content = ''
        except Exception:
            content = ''

        # On Windows, the persistent clipboard handoff may be owned by
        # PowerShell/clip after Ctrl+C.  Tk can occasionally fail to read it
        # back immediately inside the same app, so keep an IME-local fallback
        # for the common Ctrl+C -> Ctrl+V workflow.
        if not content and getattr(self, 'last_clipboard_plain_text', ''):
            content = self.last_clipboard_plain_text

        if content:
            content = str(content).replace('\r\n', '\n').replace('\r', '\n')
            # Keep pasted text consistent with live typing: a straight
            # apostrophe immediately after ] is a curly connector apostrophe.
            content = content.replace("]'", "]’")
            self.push_undo_state()
            self.close_candidate_popup()
            self.flush_sequence_buffer()
            self.reset_lomari_buffer()
            if self.selected_offsets() is not None:
                self.delete_selection_if_any(push_undo=False)
            else:
                self.sync_cursor_from_text_widget()
            self.composer.insert_literal(content)
            self.render()
            self.maybe_show_hanri_candidates()
        self.text.focus_set()
        return 'break'

    def update_audio_button_label(self) -> None:
        """Show the audio icon when idle and the stop icon during playback."""
        if self.audio_button is None:
            return
        try:
            icon_name = 'stop' if self.audio_playing else 'audio'
            icon = self.icon_images.get(icon_name)
            fallback_text = self.tr('stop' if self.audio_playing else 'play')
            self.audio_button.configure(
                image=icon,
                text='' if icon is not None else fallback_text,
            )
            if self.audio_tooltip is not None:
                self.audio_tooltip.set_text(self.tr('stop' if self.audio_playing else 'listen'))
        except tk.TclError:
            pass

    def cancel_audio_finish_timer(self) -> None:
        """Cancel the scheduled async-playback cleanup callback, if any."""
        if self.audio_after_id is not None:
            try:
                self.root.after_cancel(self.audio_after_id)
            except tk.TclError:
                pass
            self.audio_after_id = None

    def stop_windows_async_audio(self) -> None:
        """Stop winsound audio without blocking the Tkinter UI thread."""
        def stopper() -> None:
            try:
                import winsound
                # This is intentionally run in a tiny background thread.  Some
                # Windows/winsound combinations freeze Tk if PlaySound(None, ...)
                # is called from the button callback while another sound is active.
                winsound.PlaySound(None, winsound.SND_ASYNC)
            except Exception:
                pass

        threading.Thread(target=stopper, daemon=True).start()

    def stop_recorded_audio(self) -> str:
        """Stop recorded audio playback without freezing the IME."""
        self.audio_playback_id += 1
        self.audio_stop_requested = True
        self.cancel_audio_finish_timer()
        self.stop_windows_async_audio()

        self.audio_playing = False
        self.audio_thread = None
        self.update_audio_button_label()
        self.text.focus_set()
        return 'break'

    def start_async_recorded_audio(self, temp_path: Path, duration_ms: int, playback_id: int) -> None:
        """Start the already-prepared WAV with winsound async playback."""
        if playback_id != self.audio_playback_id or self.audio_stop_requested:
            self._recorded_audio_finished(playback_id)
            return

        try:
            import winsound
            winsound.PlaySound(str(temp_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.cancel_audio_finish_timer()
            self.audio_after_id = self.root.after(duration_ms + 200, lambda pid=playback_id: self._recorded_audio_finished(pid))
        except Exception as exc:
            messagebox.showerror('Audio playback error', str(exc))
            self.status.configure(text='Audio playback failed.')
            self._recorded_audio_finished(playback_id)

    def play_recorded_audio(self) -> str:
        """Play recorded syllable audio from audio_files, or stop it if already playing."""
        if self.audio_playing:
            return self.stop_recorded_audio()

        self.audio_playback_id += 1
        playback_id = self.audio_playback_id
        self.audio_stop_requested = False
        self.close_candidate_popup()
        self.flush_sequence_buffer()
        self.reset_lomari_buffer()
        self.composer.commit()
        content = format_text_tones_for_output(self.composer.text(), True, keep_literal_digit_markers=True)
        audio_content = format_text_tones_for_output(
            self.text_with_hanri_instance_readings(self.composer.text()),
            True,
            keep_literal_digit_markers=True,
        )
        audio_units, unknown_hanri = visible_text_to_audio_segments(audio_content, self.audio_mode.get())

        if not content.strip() or (not audio_units and not unknown_hanri):
            self.status.configure(text='No pronounceable Hangul/Hanri text found.')
            self.text.focus_set()
            return 'break'

        folder = audio_folder_path()
        if not folder.exists() or not folder.is_dir():
            messagebox.showwarning(
                'Audio files folder not found',
                f'Please create this folder next to the IME:\n\n{folder}'
            )
            self.status.configure(text='audio_files folder not found.')
            self.text.focus_set()
            return 'break'

        audio_segments: list[tuple[Path, bool, bool, bool, bool, bool, str, bool]] = []
        missing: list[str] = []
        for unit_index, (unit, tone, trim_start, trim_end, english_cluster_reduction) in enumerate(audio_units):
            if is_silent_audio_unit(unit, tone):
                continue
            resolved, missing_keys = resolve_audio_files_for_unit(folder, unit, tone)
            fallback_parts = split_untoned_hangul_units(unit) if len(resolved) > 1 else []
            for idx, path in enumerate(resolved):
                # Smoothing rule:
                # - start-trim phrase-internal audio units by 0.20s;
                # - end-trim non-final phrase audio units by 0.15s;
                # - phrase boundaries are comma/period/exclamation/question/
                #   colon/semicolon/hyphen/em-dash, not spaces/apostrophes.
                segment_cluster_reduction = bool(english_cluster_reduction)
                segment_trim_start = bool(trim_start or idx > 0)
                segment_trim_end = bool(trim_end or idx < len(resolved) - 1)
                segment_unit = fallback_parts[idx] if idx < len(fallback_parts) else unit
                # If a missing whole-unit recording is decomposed into smaller
                # fallback parts, only the final fallback part carries the
                # original tone.  Earlier fallback parts stay tone 3, matching
                # resolve_audio_files_for_unit().
                segment_tone = str(tone if (not fallback_parts or idx == len(fallback_parts) - 1) else '3')
                segment_l_final = audio_unit_has_l_final(segment_unit)
                segment_short_overlap_final = audio_unit_has_short_overlap_final(segment_unit)
                audio_segments.append((path, segment_trim_start, segment_trim_end, False, segment_l_final, segment_short_overlap_final, segment_tone, segment_cluster_reduction))
            missing.extend(missing_keys)

        if unknown_hanri:
            for ch in unknown_hanri:
                item = str(ch)
                if item.endswith(')'):
                    missing.append(item)
                else:
                    missing.append(f'{item} (no TSV reading)')

        if missing:
            missing_unique = []
            seen_missing = set()
            for item in missing:
                item_text = str(item)
                if item_text and item_text not in seen_missing:
                    missing_unique.append(item_text)
                    seen_missing.add(item_text)

            shown_missing = missing_unique[:24]
            extra_count = max(0, len(missing_unique) - len(shown_missing))
            missing_lines = '\n'.join(f'• {item}' for item in shown_missing)
            if extra_count:
                missing_lines += f'\n• … and {extra_count} more'

            messagebox.showwarning(
                'Missing audio',
                'The following text has no recorded audio:\n\n' + missing_lines
            )
            if len(missing_unique) <= 3:
                status_missing = ', '.join(missing_unique)
            else:
                status_missing = ', '.join(missing_unique[:3]) + f', … +{len(missing_unique) - 3}'
            self.status.configure(text=f'Missing audio: {status_missing}')
            self.text.focus_set()
            return 'break'

        if not audio_segments:
            self.status.configure(text='No audible syllables to play.')
            self.text.focus_set()
            return 'break'

        speed_all_segments = len(audio_segments) > 1
        if speed_all_segments:
            updated_segments = []
            total_segments = len(audio_segments)
            for idx, (path, trim_start, trim_end, _speed, l_final, short_overlap_final, segment_tone, english_cluster_reduction) in enumerate(audio_segments):
                previous_l_final = idx > 0 and bool(audio_segments[idx - 1][4])
                next_l_final = idx + 1 < total_segments and bool(audio_segments[idx + 1][4])
                l_final_between_l_finals = bool(l_final and (previous_l_final or next_l_final))

                # English-cluster helper syllables such as 브 in 브레 or both
                # 스/흐 in 스흐 are clipped during WAV assembly instead of
                # being globally rushed.
                if english_cluster_reduction:
                    speed_factor = AUDIO_ENGLISH_CLUSTER_SPEED_FACTOR
                # Tone 4 is 214, so it needs a gentler speed-up to preserve
                # the final rise in connected speech.  Keep trim/overlap rules
                # unchanged; only the time-compression factor changes.
                elif str(segment_tone) == '4':
                    speed_factor = AUDIO_TONE4_SPEED_FACTOR
                elif l_final_between_l_finals:
                    speed_factor = AUDIO_L_FINAL_SPEED_FACTOR
                else:
                    speed_factor = AUDIO_MULTI_SYLLABLE_SPEED_FACTOR

                updated_segments.append((
                    path,
                    trim_start,
                    trim_end,
                    speed_factor,
                    l_final,
                    short_overlap_final,
                    english_cluster_reduction,
                ))
            audio_segments = updated_segments
        else:
            audio_segments = [
                (path, trim_start, trim_end, False, _l_final, _short_overlap_final, _english_cluster_reduction)
                for path, trim_start, trim_end, _speed, _l_final, _short_overlap_final, _segment_tone, _english_cluster_reduction in audio_segments
            ]

        self.audio_playing = True
        self.audio_stop_requested = False
        self.update_audio_button_label()

        def worker() -> None:
            try:
                temp_path = Path(tempfile.gettempdir()) / AUDIO_TEMP_FILENAME
                ok = concatenate_wav_segments(audio_segments, temp_path)
                if not ok:
                    self.root.after(0, lambda: messagebox.showerror(
                        'Audio playback error',
                        'Could not combine the WAV files. Please make sure the recordings use the same WAV format/sample rate.'
                    ))
                    self.root.after(0, lambda: self.status.configure(text='Audio playback failed.'))
                    self.root.after(0, lambda pid=playback_id: self._recorded_audio_finished(pid))
                    return

                duration_ms = wav_duration_ms(temp_path)
                self.root.after(0, lambda path=temp_path, ms=duration_ms, pid=playback_id: self.start_async_recorded_audio(path, ms, pid))
            except Exception as exc:
                self.root.after(0, lambda exc=exc: messagebox.showerror('Audio playback error', str(exc)))
                self.root.after(0, lambda: self.status.configure(text='Audio playback failed.'))
                self.root.after(0, lambda pid=playback_id: self._recorded_audio_finished(pid))

        self.audio_thread = threading.Thread(target=worker, daemon=True)
        self.audio_thread.start()
        self.text.focus_set()
        return 'break'

    def _recorded_audio_finished(self, playback_id: int | None = None) -> None:
        """Return the audio button to play mode after playback/stop/failure."""
        if playback_id is not None and playback_id != self.audio_playback_id:
            return
        self.cancel_audio_finish_timer()
        self.audio_playing = False
        self.audio_thread = None
        self.audio_stop_requested = False
        self.update_audio_button_label()

    def clear(self) -> str:
        self.close_candidate_popup()
        self.key_history = []
        self.reset_lomari_buffer()
        if self.composer.text():
            self.push_undo_state()
        self.composer = Composer()
        self.composer.e_to_ye_autocorrect_enabled = self.e_to_ye_autocorrect_on.get
        self.hanri_instance_readings = []
        self.hanri_instance_text_snapshot = ''
        self.suppressed_hanri_contexts.clear()
        self.render()
        self.text.focus_set()
        return 'break'



def relaunch_with_pythonw_if_needed() -> None:
    """Relaunch with pythonw.exe on Windows so no black console window remains.

    Earlier versions tried to resize the console/Windows Terminal window.  On
    some Windows Terminal setups that can leave the title-bar buttons behaving
    badly.  The cleaner fix is to run the Tkinter app with pythonw.exe, which
    launches GUI programs without a console window.
    """
    if os.name != 'nt':
        return
    if os.environ.get('HOKKIEN_IME_PYTHONW_LAUNCHED') == '1':
        return

    exe = Path(sys.executable)
    pythonw = exe.with_name('pythonw.exe')
    if not pythonw.exists():
        return
    if exe.name.lower() == 'pythonw.exe':
        return

    try:
        env = os.environ.copy()
        env['HOKKIEN_IME_PYTHONW_LAUNCHED'] = '1'
        subprocess.Popen(
            [str(pythonw), str(Path(__file__).resolve()), *sys.argv[1:]],
            cwd=str(Path(__file__).resolve().parent),
            env=env,
            close_fds=True,
        )
        sys.exit(0)
    except Exception:
        # Fallback: use only the safe console-size command.  Do not move or
        # restyle the terminal window, so minimise/maximise/close still work.
        try:
            os.system('mode con: cols=48 lines=5 >nul 2>nul')
        except Exception:
            pass

def main() -> None:
    relaunch_with_pythonw_if_needed()
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        style.theme_use('clam')
        surface_bg = '#f8fafd'
        style.configure('.', font=('Segoe UI', 9), background=surface_bg)
        style.configure('App.TFrame', background=surface_bg)
        style.configure('App.TLabel', background=surface_bg, foreground='#202124')
        style.configure('Muted.TLabel', background=surface_bg, foreground='#5f6368')
        style.configure('Section.TLabel', background=surface_bg, foreground='#202124', font=('Segoe UI', 9, 'bold'))
        style.configure('App.TRadiobutton', background=surface_bg, foreground='#202124')
        style.configure('Modern.TButton', padding=(8, 4))
        style.configure('TButton', padding=(6, 3))
        style.configure('TLabelframe.Label', font=('Segoe UI', 9, 'bold'))
    except Exception:
        pass
    app = HokkienIMEPad(root)
    root.mainloop()


if __name__ == '__main__':
    main()
