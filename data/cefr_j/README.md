# CEFR-J English Profile (vocabulary + grammar), English-only pilot

Source: https://github.com/openlanguageprofiles/olp-en-cefrj (mirror of
http://www.cefr-j.org/ downloads).

Files:
- `cefrj-vocabulary-profile-1.5.csv` — headword, part of speech, CEFR level (A1-B2).
- `octanove-vocabulary-profile-c1c2-1.0.csv` — same format, C1/C2 supplement
  by Octanove Labs.
- `cefrj-grammar-profile-20180315.csv` — ~250 grammar structures tagged with
  CEFR-J level (and cross-references to EGP/GSELO/Core Inventory).

## License

- CEFR-J vocabulary + grammar profiles: free for research and commercial use
  with attribution. Copyright Tono Laboratory, Tokyo University of Foreign
  Studies (TUFS).
- Octanove C1/C2 vocabulary supplement: CC BY-SA 4.0
  (https://creativecommons.org/licenses/by-sa/4.0/).

Attribution (keep when redistributing or citing):
> The CEFR-J Wordlist Version 1.5. Compiled by Yukio Tono, Tokyo University
> of Foreign Studies. http://www.cefr-j.org/download.html
> The CEFR-J Grammar Profile Version 20180315. http://www.cefr-j.org/download.html

## Why this exists

Chosen 2026-08-21 as the English pilot source for two things (see CLAUDE.md):
1. **Vocabulary substitution pool** for `engine/cefr_wordlist.py` — filtering
   words by CEFR level + part of speech to fill grammar-construction drills
   (e.g. "Second Conditional, using only A2-level nouns/adjectives").
2. **Grammar gap audit** against `imlls_database_with_titles.xlsx`'s 173
   topics — see the CLAUDE.md gap list.

English-only for now — no equivalent CEFR+POS-tagged open source was found
for Ukrainian/Spanish/Korean during this pass. Extend to those languages only
after the English pilot is validated (same pattern as the YouTube-links pilot
in Phase C).
