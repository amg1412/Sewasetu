-- Salted hashes are longer than the legacy 64-char SHA-256.
ALTER TABLE portal_users ALTER COLUMN password_hash TYPE VARCHAR(255);
