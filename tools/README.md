# Tools

This folder will hold data conversion and validation scripts, starting with the TSV-to-JSON pipeline for the web dictionary.

`organize_audio_files.py` groups `public/audio_files` into initial-consonant folders using the desktop IME's own Lomari/Hangul audio filename mapping.

`build_dictionary_json.py` converts `data/hokkien_hanri_dict.tsv` into `public/data/hokkien-hanri-dict.json` for the future website.
