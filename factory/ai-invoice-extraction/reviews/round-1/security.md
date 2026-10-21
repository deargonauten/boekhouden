VERDICT: PASS
## Summary
Reviewed claude_cli.py, anthropic_api.py, prompt.py, extraction_routes.py, review templates, logging, config.
- Subprocess: argv list (no shell), no injection. Prompt follows `-p`; user filename never enters argv or prompt (generated `document.<ext>`). Tools restricted to Read, `dontAsk`, no session persistence, timeout set.
- Secrets: ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN stripped from the child env. Key not logged (API backend logs only exception type).
- Temp files: mkdtemp (0700), removed in `finally`, so removal also happens on timeout or error.
- Prompt injection: prompt states document is data. Output goes through a JSON schema, then parse_extraction and validation, and a human review step before booking. No write or network tools are available to the CLI.
- XSS: Jinja autoescape on, no `|safe`/Markup in new templates. All attributes are quoted. LLM-derived fields (notes, supplier, etc.) are escaped.
- File serving: no new endpoint; the existing `/inbox/{id}/bestand` is unchanged.
- Logging: logs cost, usage, document id and error type. Does not log invoice content, except up to 200 chars of CLI stderr on a malformed envelope.

## Nice-to-have
- `--allowedTools Read` is unscoped, so under prompt injection the CLI could read files outside the temp dir (e.g. `~/.ssh`) and echo them into extracted text fields shown only to the local user. There is no exfiltration channel, so this is low risk. Scoping to `Read(<workdir>/**)` would tighten it, if the CLI version supports it.
- claude_cli.py `_interpret` logs `stderr[:200]`. Consider dropping it or logging only the length, since stderr could echo document text.
- Opt-in use of the API backend sends invoice content to Anthropic; the `.env.example` could note this.

STATUS: DONE
