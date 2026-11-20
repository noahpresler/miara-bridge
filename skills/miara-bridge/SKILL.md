---
name: miara-bridge
description: Build a bridge that sends a person's own device or service data (sleep, feeds, diapers, pumps, room readings, vitals) to their Miara log. Use when someone wants data from a baby monitor, tracker, sensor or export file in Miara, or asks to write, test or schedule a Miara bridge.
---

# Build a Miara bridge

You are helping someone send their own data to their family's Miara log with the `miara-bridge` template. If the current folder isn't a copy of it (no `bridge.py` with `fetch` and `map`), clone https://github.com/noahpresler/miara-bridge into a new folder and work there. The template already does batching, retries, rate limits, idempotency keys and the summary. Your job is two functions, `fetch` and `map`, plus testing and scheduling.

Reference: https://getmiara.com/developers/llms.txt (short) and https://getmiara.com/api/v1/openapi.json (full).

## Rules. Never break these.

1. **Never interpret vitals.** Heart rate, oxygen and breathing rate are records. Don't label them normal, high, low or concerning, don't suggest what to do, and don't build alerts from them.
2. **Free text only as a person's note.** Readings are numbers or one of a fixed set of lowercase choices. An entry may carry a `note`, but only what a person typed about that entry in the device's own app, as they wrote it. Never write notes yourself, and never fill one with device messages, errors, ids, or who logged it.
3. **Never ask for the person's Miara password, and never ask them to paste a token.** `setup` connects by having them sign in to Miara in their browser. The token never passes through the chat.
4. **The device login stays local.** It lives only in the person's own environment (a `.env` that is in `.gitignore`, or their system's secret store). Never put it in the repo, in `raw`, in a log, or in any request to Miara. Never print it.
5. **Use the sandbox until the person says go.** Don't send anything real before the sandbox run looks right, and never send real data to the sandbox.
6. **Don't work around `suggested` or `skipped`.** Those are people's answers.

## Steps

### 1. Find out what they have

Ask, one thing at a time:
- Which device or service is it, and which child is it for?
- How does its data come out? An official export (a file or a download), an API they can log in to, or a file or database on their own machine? Prefer the official way over anything that imitates the app.
- What does it record? Sleeps, feeds, diapers, pumps (entries), and room temperature, humidity, sound, sleep stages, heart rate, oxygen, breathing (readings), or something else?
- Where will it run? Their own computer or a small always-on machine is the default. GitHub Actions is possible but puts the device login in GitHub secrets; say so.

Then look at what the service really returns before writing `map`. Add a `probe` command that signs in and prints, without personal data, which calls answer, how many items each returns, and the keys and types they have. Documented or remembered endpoints are often wrong: one may answer 404 or 422 while another holds the data, and one may take a count where you expected a time range. If everything comes back empty, ask whether the device has been used lately before changing code.

### 2. Write `fetch(since)`

In `bridge.py`. Return what's new since `since` (a UTC datetime, `None` on the first run) as plain dicts, each with the service's own id. Read the device login from `os.environ`, and add the variable names to `.env.example` (names only, no values). If the service hands back a session (access and refresh tokens), store that instead of the password: a file outside the repo with mode 600, rewritten after every refresh, because many services rotate the refresh token and the old one stops working.

Bring in everything the service has that Miara can hold, not just the sensor data: diapers, bottles, nursing and pumps that people log in the device's own app are entries too. Fetch a window, not just what's new: `since` already reaches back `LOOKBACK` (6 hours) before the last run, because services finish and correct records after the fact. Unchanged rows aren't resent, so don't filter them yourself. If the service has no official API, say so to the person, point at where the calls were documented, and keep requests few: no polling faster than the data changes. If the person pastes a password or token into the chat, tell them to put it in `.env` and not to share it again. Handle the service's paging and its own errors; if it fails, raise an exception with a plain message (the bridge prints it and doesn't move the last sync time).

### 3. Write `map(items)`

Turn items into entries and readings.

- **Entries**: kinds `sleep`, `bottle`, `nursing`, `diaper`, `pump` only. `source_event_id` always from `event_id(<the service's own id>)`, never from the run time, a counter or a hash of the content. Details follow the API: bottle `volume_ml` and `contents` (`breast_milk`, `formula`, `mixed`); nursing `left_seconds`, `right_seconds`; diaper `diaper` (`wet`, `dirty`, `mixed`, `dry`); pump `total_ml` or `duration_seconds`; sleep `{}` with `started_at` and `ended_at`, or without `ended_at` while it's going on (send it again with the same `source_event_id` once it ends; if the service then gives the finished sleep a new id, keep the first one by matching overlapping times). Convert units yourself. Times are ISO 8601 with an offset; `iso()` does it.
- **Readings**: first look at `GET /metrics`. If a **core** metric fits (`heart_rate`, `spo2`, `breathing_rate`, `room_temp_c`, `humidity`, `sound_db`, `sleep_stage`), use it exactly, in its unit and range. Otherwise declare an `x.<source>.<metric>` in `DECLARED_METRICS`: lowercase letters, digits and underscores, a short plain label, and either `min`/`max`/`unit` for a number or 2 to 12 lowercase `choices`. Never a text field. If the device's score or label can't be a number or a fixed choice, leave it out.
- **Notes**: if the service has a comment a person typed on that record, send it as the entry's `note` (up to 2,000 characters). If it has none, leave `note` out rather than sending it empty: an entry sent without `note` keeps the one someone added in Miara.
- **Sleeps the device splits**: many devices end a sleep at every brief wake. Join pieces less than a few minutes apart into one sleep, and keep the first piece's id.
- **A sleep still going**: if the service has both a history that saves each piece of a sleep as it closes and a live feed (fell asleep, woke up), a sleep that stirred and went on looks finished in the history at its first stir. Let the feed decide: a sleep the feed has open stays open over the history's newest piece until the feed's wake. Over an older piece it doesn't: a later sleep in the history means the device missed the wake, so take the history's end. Test both.
- **What people change stays**: an open sleep runs as the family's timer, and someone may end it, or change its start or wakes, in Miara. Later sends don't move that back. `send()` records it from the result's `kept`; before counting a sleep as still going (a live screen, a loop that waits for the end), check `ended_in_miara(state, source_event_id)`. A result with `joined` means the sleep merged into a timer someone started; your `ended_at` still ends it.
- Leave out anything you can't map cleanly, but don't drop it silently: count what wasn't read by type and show it in the dry run, so the person can ask for it. Print nothing about it that includes personal data. Never put media links (video, photo or clip URLs) in `raw`, and leave who logged it (names, relations) and the note out of `raw`.
- **Several children**: set `child_id` on each row from a mapping the person configures (service id to Miara child id). Never guess, and skip a child that isn't mapped.

Set `SOURCE` to a short lowercase name for this bridge, update the stub's `x.sample.score` declaration or delete it, and set `USING_SAMPLE_DATA = False`.

### 4. Test on the sandbox

```sh
python bridge.py --sandbox --dry-run   # check the printed entries and readings by eye
python bridge.py --sandbox             # sends to the made-up family
python bridge.py --sandbox             # should send nothing new
python -m unittest discover -s tests -t .
```

Read the summary with the person. `saved` and `unchanged` are good. `suggested` means a sleep overlapped one that was already there. `rejected` prints a reason; fix `map` and run again. The sandbox is shared and limited to 30 requests a minute across everyone, so don't loop.

Add a unit test for `map` with a couple of real-shaped sample items (with names and values changed or made up).

### 5. Connect to their family

Only when the sandbox run is right. Give the person one command to run themselves, in their own terminal: an `install.sh` that does everything, in order, and can be run again safely (it keeps what's done and asks before changing it):

1. **Get Python ready.** Find Python 3.10 or newer; if the computer has none that works, offer to install `uv` and use it. Make `.venv` and install `requirements.txt`. No manual `pip` or `venv` steps for the person.
2. **Sign in to the device**, asking for the email, password and any code it sends, in the terminal. Ask for a wrong password again; don't exit. Keep the session, not the password.
3. **Connect to Miara**: `python bridge.py setup --name "<device> bridge"` (add `--read` only if your code reads the log). It opens Miara in their browser (or prints the link and code when no browser can open, e.g. over SSH); they sign in, check the code matches the terminal, choose the children and approve. The page tells them to go back to the terminal, and the bridge picks up the token by itself and saves `MIARA_TOKEN` to `.env` (mode 600).
4. **Match the children.** Match the device's babies to Miara's children by first name and confirm each match; otherwise let them pick from a numbered list. Save the mapping to `.env`.
5. **Show, then ask.** Do a dry run against their family and show what will be added, in words ("2 sleeps, 1 diaper"), then ask before sending. Nothing goes on no.
6. **Offer to keep it running** (step 6).

Load `.env` automatically (without overriding what's already set) and keep state next to the script, so every command works from any folder. Error messages say which command to run next (`Run: ./install.sh`). Add `status` (running or not, last sync, what's left to fix, the log's last lines) and `stop`. Don't run any of it for the person and don't ask for the token.

If the browser sign-in can't work for them, the fallback is the app: **Profile → Siri, assistants and connections → New connection**, allowing it to add entries and add readings, then the token into `.env` as `MIARA_TOKEN`.

Then `python bridge.py --dry-run` and `python bridge.py` against their real family, and check the log in the app shows the entries under the connection's name.

### 6. Schedule it

On a Mac, have setup install and load a LaunchAgent itself (`launchctl bootstrap gui/$UID`, `KeepAlive`, logs next to the script) rather than asking the person to copy a plist. A LaunchAgent runs only while they're logged in, so on an always-on Mac check and tell them, in the System Settings words, what's missing: **Energy → Prevent automatic sleeping when the display is off** (`pmset -g custom` shows AC `sleep`), **Start up automatically after a power failure** (`autorestart`), and **Users & Groups → Automatically log in as** (`defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser`). With FileVault on, automatic login is off, so after a restart someone has to log in; for planned restarts, `sudo fdesetup authrestart` keeps it running. On a laptop, only mention sleep while on the power adapter. Never change these settings yourself.

Elsewhere, pick the file in `schedule/` for where it runs: cron, launchd (macOS), a systemd timer (Linux), or `.github/workflows/bridge.yml` (and explain the trade-off: the device login becomes a GitHub secret). If the person wants it fresh (a sleep showing while it happens), run `python bridge.py --every 120` under `KeepAlive` or `Restart=always` instead: it syncs every 2 minutes, and right away when someone opens Miara. Otherwise every 15 minutes to an hour is plenty. Replace the example paths. Confirm one scheduled run worked by reading its log.

## When something goes wrong

- `token` or `scope` errors: wrong or expired token, or the scope or child wasn't ticked. They make a new connection in the app.
- `daily_limit`: stop. The next day's run picks up.
- Everything `rejected` for one reason: fix `map`, don't retry.
- An entry someone deleted in Miara comes back `skipped` when it's sent again, and stays deleted. Never resend it under a new id.
- A library prints tokens or noisy warnings: turn its logging down to errors.
- Data looks wrong in the app: the person can turn the connection off or undo everything it wrote from the same settings screen. Fix and resend; `source_event_id` makes it update rather than duplicate.
