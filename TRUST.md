# Correction trust: how it works now, and how to harden it

Two stages. Stage 1 is built and working today. Stage 2 replaces its weakest
assumption and is the thing to do next.

---

## Stage 1 — the token whitelist (built)

Submissions arrive through the public form like everyone else's. Contributors
on a local whitelist get `status: "accepted"` instead of `status: "pending"`,
so they skip review.

### Whitelist yourself

1. Open any transcript page on the live site.
2. Right-click a line → **Your contributor ID…**
3. Copy the token. If you have set a display name the menu shows
   `Name/3a7f91c2d4e5b608` — **copy only the part after the slash.**
4. Create the whitelist from the template:

   ```
   cp trusted_contributors.example.json trusted_contributors.json
   ```

   and replace `REPLACE_WITH_YOUR_TOKEN` with your token.

`trusted_contributors.json` is gitignored. Do not commit it: it holds bearer
tokens and this repository is public, so committing it publishes the exact
value that grants the privilege.

### Ingest

```
python ingest_corrections.py --url "https://docs.google.com/spreadsheets/d/<ID>/export?format=csv"
python ingest_corrections.py --url "<...>" --dry-run     # inspect, write nothing
python ingest_corrections.py --url "<...>" --no-trust    # queue everything for review
```

The run reports how many rows were auto-accepted and under which label.

### What auto-accept does and does not do

Trust is about **who**, never about whether the edit is well formed. A trusted
submission that does not parse, or that changes nothing, still queues for
review — auto-applying a broken edit with nobody looking is exactly the
failure to avoid.

Matching is on the **token only**. The display name is typed by the submitter
and anyone can type any name, so matching on it would let a stranger inherit
your standing by choosing your name. `test_ingest_trust.py` asserts that
directly (`test_nick_alone_is_not_trust`).

A missing or malformed whitelist trusts nobody and says so. It never degrades
to allow-all.

### The honest limitation

**A token is not authentication.** It is a random value in a browser's
localStorage, sent with the submission. Anyone who sees a token can submit as
its owner, exactly rather than approximately. And every token ever submitted is
recorded in the responses sheet — so *anyone who can read that sheet can read
the tokens in it*.

While the sheet is link-shared, this whitelist is exactly as strong as the
secrecy of that link. That is obscurity, not access control. It is a reasonable
short-term trade for a small archive where the link has not been published, and
it is not something to leave in place indefinitely — which is Stage 2.

Whatever the stage, every applied correction must land in its own revertible,
attributed commit. A bad auto-accept that can be found and reverted is an
incident; one that cannot is a corrupted archive.

---

## Stage 2 — private sheet + verified identity (next)

This replaces self-asserted tokens with identity asserted by Google, and closes
the bigger problem: a world-readable sheet is an unmoderated public text box at
a stable URL, where anyone can post content naming a real resident.

### A. Turn on sign-in in the form

Google Forms → your form → **Settings**:

- **Responses → Collect email addresses** → *Verified* (not "Responder input";
  responder input is typed and therefore no better than the token).
- **Restrict to users in <domain>** — only if all contributors share a Google
  Workspace domain. For a civic project taking corrections from the public,
  leave this **off**: requiring a specific domain excludes most of the city.

Requiring sign-in is a real trade. It raises the bar for good-faith
contributors, some of whom will not have or want a Google account. Weigh that
against the archive's integrity; a reasonable middle is sign-in required, with
an emailed contact route advertised for anyone who cannot use it.

### B. Make the sheet private

In the responses sheet: **Share → General access → Restricted**.

This breaks `--url`. The `/export?format=csv` endpoint works *only* because the
sheet is open, so do not make this change until step D is ready — otherwise
ingest stops working with no replacement. Test first, switch second.

### C. Create a service account

1. <https://console.cloud.google.com/> → create or pick a project.
2. **APIs & Services → Library** → enable **Google Sheets API**.
3. **APIs & Services → Credentials → Create credentials → Service account**.
   Give it a name; no project role is needed.
4. On the service account → **Keys → Add key → Create new key → JSON**.
   Download it.
5. Save it as `credentials/sheets-service-account.json`.
   `credentials/` is already gitignored — verify before continuing:

   ```
   git check-ignore -v credentials/sheets-service-account.json
   ```

6. Copy the service account's email (it ends `.iam.gserviceaccount.com`) and
   **share the responses sheet with it as Viewer**. This is the step everyone
   forgets; without it the API returns 403 on a sheet you can see yourself.

Treat the JSON key as a password. It grants read access to the sheet to anyone
holding it, and it does not expire on its own.

### D. Read the sheet with credentials

```
pip install google-auth google-api-python-client
```

Add a `--sheet-id` path to `ingest_corrections.py` alongside `--url`:

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

def read_private_sheet(sheet_id, key_path, rng="A:Z"):
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=SCOPES)
    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    values = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=rng).execute().get("values", [])
    if not values:
        return ""
    width = max(len(r) for r in values)
    rows = [r + [""] * (width - len(r)) for r in values]   # pad ragged rows
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()
```

It returns the same CSV text `--url` produced, so `load_rows()` and everything
downstream is unchanged.

Ragged rows are the one gotcha: the Sheets API truncates trailing empty cells
per row, so rows come back at different widths and the CSV parser silently
misaligns columns. The padding above is not optional.

### E. Switch the whitelist to verified email

Once emails are verified, key trust on the email rather than the token:

- add an `email` hint to `COLUMN_HINTS` (`["email address"]`)
- allow `{"email": "you@example.com", "label": "site owner"}` entries in
  `trusted_contributors.json`
- prefer an email match over a token match when both are present

Then the whitelist rests on Google's authentication rather than on a secret
that is printed into a spreadsheet, and Stage 1's limitation is gone.

Keep the token regardless. It still correlates submissions from contributors
who are not signed in, which is what it was built for.

### F. Portability note

The sheet id, the form id and the whitelist are all per-municipality. None of
them belongs in code — they move to `profile.toml` in the Phase 10 split.
A second city needs its own form, its own sheet and its own service account.
