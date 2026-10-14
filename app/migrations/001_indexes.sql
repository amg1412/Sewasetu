-- Apply to the LIVE database (safe to re-run):
-- psql -h <host> -U sewasetu sewasetu -f app/migrations/001_indexes.sql

-- Hot lookups (every status check, OTP verify, duplicate check and the nightly
-- deemed-approval job scanned the whole table). Unique mobile also closes the
-- double-submit race.
CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_mobile ON applications (mobile);
CREATE INDEX IF NOT EXISTS idx_applications_status_submitted ON applications (status, submitted_at);
CREATE INDEX IF NOT EXISTS idx_otps_mobile_id ON otps (mobile, id DESC);
