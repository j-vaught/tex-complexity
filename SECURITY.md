# Security policy

## Supported versions

Security fixes are provided for the latest released minor version.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Earlier versions | No |

## Reporting a vulnerability

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/j-vaught/tex-complexity/security/advisories/new). Include the affected version, operating system, impact, and a minimal reproduction. Please allow a reasonable period for investigation before public disclosure.

Do not open a public issue for a suspected vulnerability. Do not attach private manuscripts, credentials, or unrelated local files to a report. Synthetic TeX input that demonstrates the behavior is preferred.

## Input boundary

LaTeX documents can reference other local files. `texstats` confines literal `\input` and `\include` expansion to the main document directory by default, resolves symlinks before checking the boundary, rejects cycles, and limits nesting. The `--allow-outside-includes` option intentionally relaxes this protection and should be used only with trusted projects.

The analyzer does not execute TeX or arbitrary document macros. It invokes Typst only when PDF highlighting is requested and generates a temporary Typst document without remote package imports.
