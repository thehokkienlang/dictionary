# Public Data

`hokkien-hanri-dict.json` is generated from `data/hokkien_hanri_dict.tsv`.

Rebuild it from the repository root:

```powershell
python tools/build_dictionary_json.py
```

The JSON keeps raw TSV values, effective readings, structural row labels, and lookup indexes for Hanri, Hangul readings, and Lomari.
