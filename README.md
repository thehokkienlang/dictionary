> **Archived: development has moved.**
>
> The dictionary and IME now share one repository:
> [thehokkienlang.github.io](https://github.com/thehokkienlang/thehokkienlang.github.io).
> Edit the [canonical TSV](https://github.com/thehokkienlang/thehokkienlang.github.io/blob/main/data/hokkien_hanri_dict.tsv)
> there. Both website interfaces are built together, including automatic JSON generation.
>
> Live interfaces: [Dictionary](https://thehokkienlang.github.io/dictionary/) and
> [IME Pad](https://thehokkienlang.github.io/ime/).
> This repository's files and history remain available for reference; its separate Pages deployment is retired.

---

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
web-hangul-ime.js     Browser Tangliengim Hangul composer
web-ime-core.js       Shared web IME controller used by dictionary search and /ime/
```

Rebuild the web dictionary data:

```powershell
python tools/build_dictionary_json.py
```

Run the dictionary MVP locally:

```powershell
python -m http.server 8000
```

Then open `http://localhost:8000/`.
