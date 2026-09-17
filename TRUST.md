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

The good news is that Stage 2 costs the public nothing: closing the sheet is a
sharing setting that submitters never see. It is not the sign-in requirement an
earlier draft of this document described.

Whatever the stage, every applied correction must land in its own revertible,
attributed commit. A bad auto-accept that can be found and reverted is an
incident; one that cannot is a corrupted archive.

---

## Stage 2 — private sheet (next)

> **Making the responses sheet private does NOT require submitters to sign in.**
> An earlier draft of this document bundled the two together; that was wrong.
> They are unrelated settings:
>
> | Setting | Lives on | Affects submitters? |
> |---|---|---|
> | Sheet sharing (Restricted / link-shared) | the **responses sheet** | **No.** Submitters never touch the sheet. |
> | "Collect email addresses → Verified" | the **form** | Yes — requires a Google login. |
>
> A private responses sheet with a wide-open form is the **Google default**.
> This sheet is link-shared only because it was deliberately opened so that
> `--url` could fetch CSV without credentials. Closing it returns to the
> default and changes nothing for the public.

**Sign-in is not part of this plan.** Requiring a Google account to report a
typo would exclude exactly the people a civic archive exists to serve, and the
project's stated goal is not erecting barriers to participation. The form stays
open to anyone, no login.

What a private sheet buys, with zero submitter friction:

- **Submitted free text stops being world-readable.** This is the real win.
  An open responses sheet is an unmoderated public text box at a stable URL:
  anyone can submit content naming a real resident and it is instantly public.
- **Contributor tokens stop being public**, which is what currently reduces the
  Stage 1 whitelist to obscurity. With a private sheet the token is no longer
  printed anywhere a stranger can read, so auto-accept rests on actual access
  control rather than on an unpublished link.
- **Display names stop being public.** Contributors type real names into that
  box and will not expect them to be readable by anyone.

So the whitelist stays keyed on the **token**, and gets meaningfully stronger
without the form changing at all.

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

### E. Nothing to change in the whitelist

The whitelist keeps matching on the token. What changes is its strength: the
token is no longer printed into a document a stranger can open, so "anyone who
can read the sheet can submit as anyone in it" stops being true.

It is still a bearer token, so it is still not authentication in the strict
sense — someone who obtains it by other means can use it. But the realistic
attack (read the public sheet, copy a token) is closed, and that was the one
that made Stage 1 uncomfortable.

If you ever *do* want verified identity — say a volunteer reviewer with
auto-accept, where the stakes are higher — that is when email collection earns
its cost. The hooks:

- add an `email` hint to `COLUMN_HINTS` (`["email address"]`)
- allow `{"email": "them@example.com", "label": "reviewer"}` entries in
  `trusted_contributors.json`
- prefer an email match over a token match when both are present

Do not turn that on for the general public.

### F. Portability note

The sheet id, the form id and the whitelist are all per-municipality. None of
them belongs in code — they move to `profile.toml` in the Phase 10 split.
A second city needs its own form, its own sheet and its own service account.
