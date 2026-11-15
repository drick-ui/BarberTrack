-- ONLY for an existing database that was created with an older database.sql.
-- Adds the columns needed for OTP + login lockout. Works on XAMPP (MariaDB).
USE barbertrack;
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS otp_hash VARCHAR(255) NULL,
  ADD COLUMN IF NOT EXISTS otp_expires DATETIME NULL,
  ADD COLUMN IF NOT EXISTS otp_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS failed_logins INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS locked_until DATETIME NULL;
