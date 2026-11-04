# Reference documents for a run

Attach PDF, DOCX, TXT, MD, CSV, or JSON files beside the prompt, then start a Codex run. The platform accepts up to three files of 2 MB each. Text extraction is limited to 8,000 characters per file and 20,000 characters total. Scanned PDFs without selectable text are rejected. DOCX and PDF files are converted to text on the API server; other formats must be UTF-8.

The API stores extracted text and a SHA-256 digest under that run's private local data directory. The original binary is not placed in generated source or source ZIP. The browser can display the text that the agents received. References are available only to the run's owner and are deleted with the project.

Coordinator and every selected specialist Codex role receive the extracted text in their prompt. The platform records `references.injected` events for each handoff. For software, after generated tests pass, QA must identify an exact quote from every document and an exact code excerpt from a named generated file. For research reports, QA must identify an exact quote from every document and a matching passage in `REPORT.md`. The runner checks the strings against the stored reference and generated output. A missing or invalid check blocks completion; successful checks appear in the run report and dashboard.

These checks prove delivery and traceable output evidence. They cannot prove that a model interpreted every sentence correctly. Review the QA evidence and inspect the generated app or report before relying on it.
