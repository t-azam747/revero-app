# M1 verification status — 16 November 2026

M1 implementation was committed as `a055356`: ordered migrations, shared SQLite connection policy, private API access, worker supervision, encrypted backups, optional verified S3-compatible upload, deployment configuration, CI, and an isolated restore drill.

Local verification: 140 backend tests passed; 11 browser tests passed; the frontend production build passed; `git diff --check` passed. The isolated restore drill passed on macOS using authored fixture data, fake providers, a fresh restored volume and two real API process starts. Its output is `artifacts/m1-restore-drill.json` (ignored). No real provider call was made.

The M1 exit gate remains **open**. The deployment host, private ingress, object-storage account, region, credentials, backup retention decision, and independent recovery-key custody have not been supplied or verified. No off-host upload or clean-host restore has run. The one-hour data-loss and two-hour restoration targets therefore have not been demonstrated. CI is configured but has not run on GitHub for this commit.

Owner decision (16 November 2026): keep Revero local for now. Do not set up or buy a VM, domain, VPN, or cloud backup service for M1. The original always-on deployment and off-host recovery gate is deferred, not verified. Continue local use and treat a backup on storage outside the computer plus a tested restore as the practical next protection step. Do not claim that local testing proves recovery from loss of the computer.

Local recovery gap: the passing drill restores an authored temporary database on this computer. It does not verify an encrypted copy on a separate physical device, the owner's ability to retrieve its key after this computer is lost, or restoration of a copy from that device. Use the existing `app.backups` backup/restore functions for a user-selected external destination and test a restore into a new isolated path with processing and delivery paused. Do not move or overwrite the personal database during that test. The external destination and key custody remain owner choices.
