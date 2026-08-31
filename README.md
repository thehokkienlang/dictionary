# Hokkien Tangliengim

Hokkien Tangliengim is a writing and dictionary toolkit for Hokkien.

The project brings together:

- a Hanri, Tangliengim Hangul, and Lomari dictionary
- a web-based Hokkien IME
- HTML annotation tools for ruby text and lyrics
- audio lookup for pronunciation
- future English ↔ Hokkien translation support

The goal is to build one shared Hokkien data/codebase where dictionary lookup, input, annotation, and translation can all improve together.

## Repository layout

```text
desktop/              Desktop Python IME and HTML annotation tools
data/                 Dictionary and source linguistic data
public/audio_files/   Pronunciation audio assets, grouped by initial consonant
public/data/          Generated JSON data for the website
tools/                Data conversion and validation scripts
```

Rebuild the web dictionary data:

```powershell
python tools/build_dictionary_json.py
```
