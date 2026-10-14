# Sewa Setu: what I found, what I fixed, what I left alone

Evidence: nginx log (1.5M requests), app log, cron log, the seed database and the code.
Every fix has a test that fails on the code before it and passes after it, committed in
that order (`git log --oneline`; raw runs in `docs/evidence/fixN-before.txt` / `-after.txt`).
Run them: `SS_DB_HOST=localhost pytest tests/` (uses an isolated `sewasetu_test` database).

## Top 5, ranked by citizen impact

1. **Submission crashed after saving** (13,759 of 34,332 attempts in the logs failed with 500/504,
   "too many clients"). The record was already saved, so the citizen saw an error, retried, and
   was told "duplicate application", with no application number. Fix: connections always closed,
   SMS sent in the background, the acknowledgment PDF no longer built in the request, a unique
   index on mobile, and a retry now shows the existing application number. Indexes added for the
   hot lookups (every one was a full table scan of 100k rows).
2. **Upload rejected most citizens with "ERR_VAL_47"** (75,815 upload attempts, 34,332 reached
   the declaration). The page promised JPG/PDF up to 5 MB; the code took only PDF up to 100 KB.
   Fix: code matches the page, plain-language errors, server-chosen filenames, 1-hour session
   (was 5 minutes).
3. **Deemed approval stopped on 14 March.** The nightly job reads `settings.ini`, which was renamed
   `app.ini`; 108 nightly runs crashed. Fix: one shared config loader, a loud non-zero exit,
   a `--dry-run` flag. On the seeded data the dry run says **4,745 applications** are overdue.
4. **Any citizen could read anyone's record** (name, DOB, bank account) by changing the number in
   the URL, approve/reject applications with a citizen login, forge staff sessions with the signing
   key and admin password published in the repo, and inject SQL in the reset form. Passwords were
   unsalted SHA-256 of the DOB. Fix: ownership checks, admin-only decisions (recorded with the
   decider), credentials and signing key from the environment, parameterised SQL, salted hashes
   upgraded when each citizen next logs in.
5. **Names and dates stored wrongly.** Names were cut to 20 *bytes* (an Assamese name kept about 7
   letters; all 300 non-ASCII records in the seed are damaged). Dates were parsed month-first although
   the form says DD/MM/YYYY. Every validation failure said "Something went wrong". Fix: names
   capped by characters (100), day-first dates only, specific messages that send the citizen to the
   right page.

## Not done, on purpose

- **Existing records were not changed.** 875 stored citizens show an age under 60 (776 are approved),
  probably from the month-first dates. They need officer review, not a script.
- **The 4,745 overdue backfill has not been run on any live system.** The nightly job will do it
  at 02:00 once deployed; run `scripts/deemed_approval.py --dry-run` first and have an officer
  agree the number.
- **`/__gateway/` is still public.** The brief says the assessor reads OTPs through it. In a real
  deployment it must be removed: anyone can read anyone's OTP.
- No login rate limiting (DOB passwords are guessable; this is the biggest open risk), no CSRF
  tokens on admin buttons (SameSite=Lax cookies reduce it), the captcha is never checked, the
  widow form still asks for a late husband's employer (policy question, now with a clear message),
  and the database password is still in `app.ini`.
- No interface rewrite and no framework change.

## What my tools got wrong

I first assumed the PDF border (4,000 line segments) caused the crashes. Timing showed it takes
0.02 s, and failing submissions did not leak connections in my tests. I could not reproduce
"too many clients" on one CPU, so Fix 1 is defensive (shorter connection life, work off the request
path) and its tests check behaviour I could prove, not the production overload itself.
I also first set the password hashing cost so high that 300 logins took 54 CPU-seconds; I lowered it.
