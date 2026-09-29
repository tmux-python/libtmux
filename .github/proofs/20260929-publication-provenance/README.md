# Publication provenance proof

[Run 36642578777](https://github.com/tmux-python/libtmux/actions/runs/36642578777) builds Python documentation from three clean product revisions and publishes an isolated immutable version through reviewed builder/publisher `843278f595d8a4495c18c9d9dbe8ab0b2bd50289`. The workflow in this branch is the exact proof caller. Its overall result is red because three negative jobs intentionally fail.

| Check | Observed result |
| --- | --- |
| Original build and publication | Passed |
| Dirty source record, changed content, wrong archive digest | Each failed provenance verification before AWS credentials |
| Identical content uploaded as a new artifact | Passed immutable comparison, skipped S3 sync, retained the original receipt |
| Ordinary public requests | Root, native Session page, build record and manifest returned HTTP 200 through Cloudflare and CloudFront |
| S3 after the identical rerun | All 7,699 objects and 476,169,378 bytes matched the recorded inventory; no extra or missing keys |

`evidence.json` records the result and scope limits. `jobs.json` and `job-assertions.json` identify the exact failed steps and skipped AWS steps. `manifest-first.json`, `manifest-after.json`, `verified-chain.json` and `s3-verification.json` retain the publication chain. `original-build-provenance.json` records sources and file hashes. `archived-artifacts.json` records all eleven downloaded archive digests. Raw archives, complete logs and the downloaded S3 tree are retained locally; large binaries are not stored on this branch.

Dispatch to first receipt took 434 seconds, including a 160-second tree build and 138-second S3 sync. The full proof took 551 seconds. `timing.json` contains exact job and step timestamps; `inventory-cost.json` contains the output size breakdown.

These are dispatch measurements. Release-event latency remains unmeasured. Controlled record and digest mutations prove publisher rejection; they do not establish cryptographic attestation of source execution. Ruby/Lua custom builders and the shared-root contract require separate migration.

The proof prefix is `en/py/provenance-proof-20260929-843278f5/`. Its manifest row does not change the default version. `cleanup.json` records caller restoration, conditional removal of only that row, deletion of only that prefix, and final absence checks.
