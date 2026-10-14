# Colab SBERT evaluation

- Notebook: https://colab.research.google.com/drive/1lRiX1VtO_jG_ds6_SAsN3OosCAfAQIVw
- Drive folder: https://drive.google.com/drive/folders/1aXxpkx1q0XCd-xZvssipK_oqtS3OY21q
- Input: frozen 172 predictions and original 86 gold rows, embedded with SHA-256 checks.
- Model: sentence-transformers/all-MiniLM-L6-v2; resolved model commit and installed package versions are recorded when executed.
- Matching: condition + space + action, normalized embedding cosine; per-document Hungarian maximum-weight assignment followed by >= 0.6 threshold. All 172 predictions are included in the denominator.
- Local preparation: four code cells passed Python syntax compilation. No local packages or model weights installed.
- Cloud preparation: uploaded notebook, verified file metadata and size (139471 bytes).
- Runtime status: COMPLETE in hosted Colab CPU runtime on 2026-10-14 KST. F1_content=0.5193798449612403, precision=0.38953488372093026, recall=0.7790697674418605; 67 accepted matches, 105 unmatched predictions, 19 unmatched gold rows.
- Preserved executed.ipynb, metrics.json, assignments.json, cosine_matrix.npy and imaks_sbert_results.zip. Verified input hashes, 86 unique one-to-one assignments, threshold decisions, and unmatched counts.

Use a hosted Colab runtime, then Run all. The final cell downloads a small results ZIP containing metrics.json, assignments.json and cosine_matrix.npy. Save the executed notebook to retain its output. No OpenAI API key or Drive mount is required.

This notebook contains evaluation inputs. Keep it in private Drive; do not publish it in the GitHub repository. Existing frozen extraction/KG/diagnostic artifacts remain unchanged. The user's 2026-10-14 authorization permits Colab upload and remote installation; it does not authorize local model installation.
