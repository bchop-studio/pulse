# Contributing

Keep it simple and keep it safe.

## The one hard rule

**Never print, log, or commit a secret.** Pulse reads credentials from local
config to do its job, but no key, token, or Authorization header may ever
appear in output, errors, or the repo. If you touch anything near the network
or config code, grep your diff for leaks before opening a PR.

## Ground rules

- Standard library only. No new dependencies without a very good reason.
- One file if you can. `pulse` is a single script on purpose.
- Secrets stay in memory. Show a fingerprint (`…a1b2`) at most.
- Keep output clean and grouped by provider: green alive, red refused,
  yellow limited.
- Test against a real provider if you can, but never commit a real key to do it.

## Setup

```bash
git clone https://github.com/BeardedChop/pulse
cd pulse
./pulse --help
```

No build step. Edit `pulse`, run it, done.
