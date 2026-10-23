# Remaining acceptance

The two-repository, two-container Remote Vibecoding migration is deployed and
verified. See docs/deployment-2026-10-23.md for evidence and rollback boundaries.

- Obtain explicit owner permission for the new private snapshot manual upload to
  the existing Google Drive destination, then verify staged offsite recovery.
  Automatic approval review rejected upload; do not bypass this boundary.
  Local recovery is already verified.
- Obtain phone-side acceptance of the location-first UI. Preserve the private
  legacy rollback bundle until acceptance and replacement recovery verification;
  then agree its retention/removal.

## Local voice acceptance

Menu simplification, paired session pagination, response ages and default Settings
styling are deployed. Local voice implementation passes component checks. Verify
Russian speech on the VPS with measured elapsed time, CPU and peak memory, then
verify Telegram download to Core transcription to native response and retained
photo recognition. Video is explicitly out of scope. Keep exactly two containers.
