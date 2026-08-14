# pulse

![Pulse cover](assets/cover.png)

One tap — see which of your models are actually alive.

You have access to a pile of providers and models. Some are great, some run
out of usage mid-session, and some models on a provider you can't touch at
all (looking at you, Copilot Opus vs Sonnet). Instead of clicking through
each one to see who answers, run `pulse`. It pings every provider you've
configured and every model it can find, then shows you green (alive), red
(refused / no access), or yellow (out of usage / can't tell) in one list.

## What it does

- Reads your [Hermes](https://github.com/NousResearch/hermes-agent) setup:
  the credential pool in `~/.hermes/auth.json`, custom providers from
  `~/.hermes/config.yaml`, and API keys from `~/.hermes/.env`.
- Asks each provider for its real model list (falls back to a default when
  a provider doesn't expose one).
- Sends a tiny "reply with: ok" to each model and records who answered.
- Prints one clean grouped list. Secrets are never printed — keys are read
  from disk, held in memory, and shown only as a fingerprint.

## Install

```bash
git clone https://github.com/BeardedChop/pulse ~/github/pulse
sudo ln -s ~/github/pulse/pulse /usr/local/bin/pulse   # or add the dir to PATH
```

No dependencies. Python 3.8+, standard library only.

## Use

```bash
pulse                      # check everything
pulse --provider copilot   # just one provider
pulse --limit 5            # cap models per provider (default 12)
pulse --list-only          # list models without probing
pulse --json               # machine-readable output
pulse --watch              # live board, refresh liveness every 60s
pulse --watch 20           # live board, refresh every 20s
```

Exit code is `0` when at least one model is alive, `1` when none are — so
you can wire it into scripts.

## Reading the output

```
copilot
  ● claude-sonnet-5          <- green: answered
  ● claude-opus-5  HTTP 400  <- red: you can't use this one
```

Providers that share their quota show it on the header line, so you see a
near-empty balance before you start, not a dead model mid-session:

```
openrouter  usage: $0.41 left of $65 (99% used)
```

- **green** — the model replied. Good to go.
- **red** — the provider refused (no access, or model not found).
- **yellow** — out of usage / rate-limited, or the provider errored.

`--watch` redraws the same board on a loop. It re-probes model liveness on
your beat (default 60s, minimum 15s) but only re-asks each provider for its
model list and usage every 5 minutes, so it stays cheap to run.

## Security & privacy

Pulse reads your local Hermes config to find your providers and keys:
`~/.hermes/auth.json`, `~/.hermes/config.yaml`, and `~/.hermes/.env`. It also
falls back to `gh auth token` for GitHub Copilot. This is read-only, on your
own machine, the same way Hermes itself reads them.

- **Nothing leaves your machine except the health checks.** The only network
  requests are tiny "reply with: ok" calls sent to each provider's own API,
  authorized with that provider's key.
- **Secrets are never printed, logged, or written anywhere.** Keys live only
  in memory for the lifetime of the run. Output shows provider and model
  names and a status, never a credential.
- **No telemetry, no analytics, no third-party calls.**

If you fork or contribute, never commit your own `.env` or `auth.json`. The
`.gitignore` already blocks them.

## Notes

- Anthropic's API isn't key-scoped to a model list, so pulse probes a model
  you name: `pulse --provider anthropic --model claude-sonnet-4-5`.
- OpenRouter lists hundreds of models; pulse caps at 12 per provider unless
  you pass `--limit 0` for all of them.
- GitHub Copilot needs a token. Pulse tries `~/.hermes/.env`, then `gh auth
  token` from the GitHub CLI.
- Only OpenRouter exposes a credit balance over the plain API, so it's the one
  with a number on the usage line. Other providers don't share quota this way,
  so pulse shows nothing rather than guess. As more providers open up a quota
  endpoint, they slot into `get_usage()`.

---

MIT. Do whatever you want with these.

Built by [@BChopLXXXII](https://x.com/BChopLXXXII)

Built for BUILDERS who just want their AI to feel less... corporate.

Ship it. 🚀

If this helped, ⭐ the repo — it helps others find it.
