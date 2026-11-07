# AFP Watch Out, Weekly IDSR and Meningitis (Django)

The Ghana Health Service surveillance web app, as a standard Django project:

- **AFP 60-day follow-up**: alerts for cases past due, due soon or missing a follow-up report; new-case entry with the 60-day clock; edit or delete a case within 24 hours; update from file; the district/region case report (PNG, PDF, Excel).
- **Weekly IDSR**: data entry by district and epi week, upload of the official weekly form or a table, fetch from DHIMS2, and the Weekly Epidemiological Bulletin (PNG, PDF).
- **Meningitis**: the case line list (entry, editing, upload of the regional meningitis workbook, downloads with or without names), sub-districts with their populations and the WHO alert and epidemic thresholds, and the reports of the regional workbook (see [Meningitis](#meningitis)).

Each account works for one region and its districts only. National administrators (region "Ghana") see every region.

The desktop-only tools of the local app (the Tk entry form `app.py`, the Windows alerts `notify.py` and their scheduled task) are not part of this project. They stay in the `AFP Notification` folder.

## Project layout

| Path | What it holds |
|---|---|
| `surveillance/` | Project settings, root `urls.py`, `wsgi.py` / `asgi.py` |
| `core/` | Org units (`orgunits.py`, `data/ghana-org-units.json`), letterheads and support contacts (`branding.py`), sign-in gate and request region (`access.py`), start page, shared CSS/JS |
| `accounts/` | Accounts (Django users and a `Profile` with region, cadre and picture), sign-in, lockout, passwords, profile, the Accounts page |
| `afp/` | AFP register (`register.py`), case list (`cases.py`), Excel report (`report.py`), views |
| `idsr/` | IDSR stores (`store.py`), DHIMS2 (`dhims2.py`), bulletin data (`bulletin.py`), the official form template (`data/`), views |
| `reminders/` | SMS reminders to district officers: Fish Africa client (`letsfish.py`), rules (`service.py`), the daily command `send_reminders`, the page |
| `meningitis/` | Line list models (`models.py`), code lists (`choices.py`), columns (`linelist.py`), saving and checks (`cases.py`), reports (`reports.py`), upload (`importer.py`), Excel downloads (`exports.py`), views |
| `<app>/templates/`, `<app>/static/` | Each page's HTML template, CSS and JavaScript |
| `data/` | The workbooks the app reads and writes (not in git) |
| `reference/` | Source documents: the weekly form loaded for week 43, the bulletin PDF, the North East map project |
| `passenger_wsgi.py` | Entry point for cPanel "Setup Python App" |
| `.env.example` | The server's settings, to copy to `.env` |
| `make_upload.py` | Builds the zips and `.env` to upload to the server (`dist/`) |
| `server_setup.sh` | Run on the server: installs, sets up the database and accounts, links the subdomain, checks the site |

The data files in `data/`:

- `AFP nofitication.xlsx`: the AFP register, with `AFP case entries.json` (who entered which case, and when) beside it.
- `IDSR weekly data.xlsx`: North East's IDSR store. The other regions' stores, and Ghana's, are in `IDSR regions/`.
- `idsr-images/`: each region's map and SORMAS pictures for the bulletin.

Each save keeps the previous file as `.bak.xlsx`. Close a workbook in Excel before saving from the app.

## Run it on this computer

1. Install Python 3.12 or later, then `pip install -r requirements.txt`.
2. Double-click `Start app.cmd`. It sets up the database, gathers the static files, starts the app on http://127.0.0.1:8765 and opens the login page. Keep the window open while you work; close it to stop.
   The same steps by hand: `python manage.py migrate`, `python manage.py collectstatic`, `python manage.py runserver 127.0.0.1:8765`.
3. **First run:** with no accounts yet, the login page shows "Create your account" (full name, region, username, password of at least 8 characters).
4. **Bring over the local app's accounts** (everyone keeps their password and picture): `python manage.py import_legacy_users`.

## Accounts and sign-in

- Accounts live in the database with Django's password hashing. Imported passwords are moved to Django's hashing the first time each person signs in.
- A sign-in lasts 12 hours. After 5 wrong passwords in a row, the username is locked for 5 minutes.
- A password set for someone else must be changed at the next sign-in. Anyone can change their own password from their profile.
- Every page and download needs a sign-in. API calls send Django's CSRF token (`core/static/core/js/csrf.js`).
- Profile pictures and the remembered DHIMS2 token are kept in `private_media/`, which is never served directly.

## Settings

Everything that differs between this computer and the server comes from environment variables (see the top of `surveillance/settings.py`):

| Variable | Meaning |
|---|---|
| `DJANGO_SECRET_KEY` | Long random string. Without it, one is made and kept in `.secret_key` |
| `DJANGO_DEBUG` | `1` only while testing |
| `DJANGO_ALLOWED_HOSTS` | The site's domain(s), comma separated |
| `DJANGO_HTTPS` | `1` once the site has an SSL certificate |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | e.g. `https://surveillance.rhduer.online`, if a proxy changes the host |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `DB_ENGINE=mysql` for MySQL. Without it, SQLite (`db.sqlite3`, or the file `DB_NAME` names) |
| `DATA_DIR` | Folder of the workbooks (default `data/`) |
| `AFP_REGISTER` | The AFP register workbook (default `DATA_DIR/AFP nofitication.xlsx`) |
| `PRIVATE_DIR` | Folder for profile pictures and the DHIMS2 token (default `private_media/`) |

The same variables can go in a `.env` file beside `manage.py` (copy `.env.example`). Variables set in cPanel win over `.env`.

## Deploy on Namecheap shared hosting (cPanel)

The pages call `/api/...` from the site root, so the app needs a domain or subdomain of its own (e.g. `surveillance.rhduer.online`), not a folder such as `example.org/afp`.

Two folders on the server, never one inside the other:

- `/home/<cpanel user>/surveillance`: the app (code, `.env`, `db.sqlite3`, `data/`). Private.
- `/home/<cpanel user>/surveillance_web`: the subdomain's document root. It holds only a `.htaccess` (written by `server_setup.sh`) that hands every visit to the app. Whatever sits in a document root can be downloaded by anyone, so the app must not be in it.

**On this computer**

1. `python make_upload.py`. It writes `dist/surveillance-app.zip` (the code), `dist/surveillance-data.zip` (the workbooks in `data/` and the local app's accounts in `legacy-accounts/`) and `dist/.env` (the server's settings with a new secret key).

**In cPanel**

2. *Domains*: the subdomain `surveillance.rhduer.online` with document root `surveillance_web` (*Manage* > *New Document Root*). *SSL/TLS Status*: run AutoSSL for it.
3. *File Manager*: make the folder `/home/<cpanel user>/surveillance` (in your home folder, not inside `surveillance_web` or `public_html`). Upload both zips into it and *Extract* each, then upload `dist/.env` (turn on *Show Hidden Files* in *Settings* to see it). You get `manage.py`, `passenger_wsgi.py`, `server_setup.sh`, `.env`, `data/`, ... directly in `surveillance/`.
4. *Setup Python App* > *Create Application*: Python 3.12 (3.10 or later; the "recommended" 3.6 is too old), Application root `surveillance`, Application URL the subdomain with the path empty, startup file `passenger_wsgi.py`, entry point `application`. If cPanel replaced `passenger_wsgi.py` with its own "It works!" file, extract `surveillance-app.zip` again.
5. Copy the command shown at the top of the app's page (`source /home/<user>/virtualenv/surveillance/3.12/bin/activate && cd /home/<user>/surveillance`), paste it in *Terminal*, then run `bash server_setup.sh`. It installs the packages, makes the database, gathers the static files, imports the accounts, makes the support account (its password is printed once: write it down), writes `surveillance_web/.htaccess`, restarts the app and checks from outside that `/login` answers and that `db.sqlite3`, `.env` and `data/` cannot be downloaded.
6. Open `https://surveillance.rhduer.online/login`. Once the accounts can sign in, delete `legacy-accounts/` and the two zips.

**Restart:** `touch ~/surveillance/tmp/restart.txt` (or *Restart* in *Setup Python App*).

**Updating the app later:** run `make_upload.py` again, upload only `surveillance-app.zip`, extract it over the old files (your `.env`, `db.sqlite3` and `data/` are not in it), and run `bash server_setup.sh` again. Do not upload `surveillance-data.zip` or `.env` again: they would replace the server's data and sign everyone out.

**If something goes wrong:** the end of `django-errors.log` and `stderr.log` in the app folder show the error. A web server "404 Not Found" page (not the app's) means `surveillance_web/.htaccess` is missing: run `server_setup.sh` again. For a closer look set `DJANGO_DEBUG=1` in `.env`, restart, read the error page, and set it back at once.

Notes:

- **SQLite**: Namecheap's servers have an SQLite older than Django needs. `requirements.txt` installs `pysqlite3-binary`, which the settings use instead. SQLite is enough for a few dozen users; back up `db.sqlite3` with the workbooks.
- **MySQL** (optional): make the database and user under *MySQL Databases*, `pip install PyMySQL`, and set the `DB_*` lines in `.env`. `mysqlclient` usually cannot be built on shared hosting; PyMySQL stands in for it.
- **Several processes**: Passenger may run the app in more than one process. Every request that saves something holds a lock file (`data/.write.lock`, `core/locks.py`), so two saves never overwrite each other.
- **Backups**: download `data/`, `db.sqlite3` and `private_media/` regularly (or include them in cPanel's backup).

## Meningitis

Open it from the start page or at `/meningitis`. Unlike the AFP register and the IDSR stores, the line list is kept in the database (`db.sqlite3` or MySQL): back it up with the database.

- **Line list**: one row per patient, with the columns of the regional workbook (Table14: LastName … FinalClassification). The EPID number is `CCC-RRR-DDD-YY-NNNNN` (for example `GHA-NOR-GUS-26-00012`): the region and district parts come from the org units, the year from the date seen, and the number is the next free one for the district and year. The epi week is the ISO week of the date seen (else of onset).
- **Checks**: age in months (under 1 year) or in years, not both; onset on or before the date seen, and no date in the future; vaccines only when Vaccinated is 1-Yes; lab results only when a specimen was collected. Confirmed with no pathogen in the final result is a warning, not an error.
- **Other regions**: a patient whose district of residence is in another region is listed apart and left out of the region's reports, as the workbook kept them on the *Outbreak linelist-other region* sheet.
- **Upload**: the regional workbook (both line list sheets) or a download from the page. Cases are matched by EPID; rows with no EPID (Filter 0) are skipped; blank cells never erase anything; codes written in other ways ("9 unknown", "Missing", "2 GND") are read back to the list and counted in the review. Nothing is saved until you apply the review.
- **Sub-districts and thresholds**: each sub-district's population sets its weekly alert and epidemic thresholds. The WHO defaults are 3 and 10 cases per 100,000 a week; at or under 30,000 people (or with no population on file), 2 and 5 cases in a week. The season starts in epi week 39. Each region can change these. Sub-districts named in an upload are added without a population.
- **Reports** (Excel and PDF): weekly cases and deaths by sub-district with the thresholds (cells amber for alert, red for epidemic), the district summary, the regional summary (by district, age group, sex, final lab result and sub-district, with CFR), the epi curve by final classification, vaccination and indicators (with data completeness), laboratory results, and one threshold chart per sub-district. Each covers a year, either the season (from week 39 of the year before) or the calendar year, optionally a range of weeks and one district. Every report's totals equal the number of cases in the line list for the same filters.
- **Who can do what**: regional accounts add and change their region's cases. Whoever entered a case can delete it within 24 hours; support can delete any. The Ghana view reads every region and changes nothing; its New case and Upload tabs ask for the region first. Every change is logged (the case form shows it).
- **Faster entry**: *Save and add another* keeps the district, facility, sub-district and date seen for the next case. The Upload tab has a blank template with drop-down lists for every coded column.

## SMS reminders (AFP 60-day follow-up)

Who does what on the *SMS reminders* page: **regional officers** add and change their own region's district officers and see its reminders and log; the **support account** (super admin) holds the Fish Africa settings and is the only one who sends from the page (*Send now*, test SMS), in any region; **national administrators** read every region. The daily job sends every region's reminders.

District officers get an SMS through [Fish Africa](https://docs.letsfish.africa) for their district's AFP cases: once when a case enters its last 7 days before the day-60 follow-up visit, then once it is overdue and every 7 days until its Outcome is "FUP done" (the AFP page's own rules). Each officer gets one SMS per run listing their cases by EPID number and due date; patient names are never sent. Each case and stage goes to each phone once; a failed send is tried again on the next run.

1. **Fish Africa account**: in its dashboard, *Settings* > *Applications* > *Default App*, copy the App ID and App Secret. Ask Fish Africa to approve a sender ID (at most 11 characters, e.g. `GHS-AFP`).
2. **Settings** (support account only): sign in as support, open *SMS reminders* (`/reminders`) and enter the App ID, App Secret and sender ID under *Fish Africa settings*. They are kept in `private_media/sms.json` (never served; the secret is never shown again). `LETSFISH_APP_ID`, `LETSFISH_APP_SECRET` and `LETSFISH_SENDER_ID` in `.env` also work; the page's values win. Optional in `.env`: `REMINDER_SOON_DAYS` (default 7) and `REMINDER_REPEAT_DAYS` (default 7).
3. **Officers** (each regional team, for its own region): on the same page, add each district officer's name and phone number (choose *Whole region* for someone who should get every district's), then send a test SMS.
4. **Daily job**: `python manage.py send_reminders` sends today's reminders (`--dry-run` shows them without sending). Schedule it once a day:
   - cPanel *Cron Jobs*: `0 8 * * * cd ~/surveillance && ~/virtualenv/surveillance/3.12/bin/python manage.py send_reminders`
   - Windows: `schtasks /Create /SC DAILY /ST 08:00 /TN "AFP SMS reminders" /TR "cmd /c cd /d \"<project folder>\" && python manage.py send_reminders"`

The page also has *Send now* (the same reminders, earlier) and the log of what was sent.

## Maintenance

- Org units: `python manage.py orgunits` lists them. `python manage.py orgunits --import <regions.json> <districts.json>` refreshes them from DHIS2 exports. Corrections to the exports are in `CORRECTIONS` in `core/orgunits.py` (16 regions, 261 districts).
- Logos are in `core/static/core/img/`. Support contacts are in `core/branding.py`.
- Tests: `python manage.py test`. They run on a temporary copy of `data/`, never on the real files.

## Support

- WhatsApp: 0246828504
- Email: babayahaya.mohammed@ghs.gov.gh

© Ghana Health Service · Regional Health Directorate, Upper East (Surveillance). All rights reserved.
