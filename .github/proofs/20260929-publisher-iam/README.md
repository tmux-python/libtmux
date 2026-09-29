# Publisher IAM proof — 2026-09-29

[Run 36639348612](https://github.com/tmux-python/libtmux/actions/runs/36639348612) executed the workflow at `73513701eb1f4bc88225efa06877082fd285c82f`.
The approved publisher was `8fda4b89071621b9ed2c4722a68d61f6ecf9c1c4`.

| Probe | Observed result |
| --- | --- |
| Approved workflow, Python prefix | Uploaded `en/py/iam-proof-36639348612/probe.txt` |
| Approved workflow, C++ prefix | S3 sync denied at `ListObjectsV2` (`s3:ListBucket`) |
| Direct job | `sts:AssumeRoleWithWebIdentity` denied |
| Unapproved commit `c7bdbc43884e7e000948110234d006e68445d777` | `sts:AssumeRoleWithWebIdentity` denied |
| Unapproved tag `v0.1.0-alpha.1` | `sts:AssumeRoleWithWebIdentity` denied |

All reusable calls passed input validation and artifact download. The foreign
prefix call also assumed the Python publisher role successfully before S3
denied its sync. This run proves the foreign sync denial; it does not contain
a separate direct `PutObject` attempt.

Each expected negative job remains failed. The status verdict passed; the
workflow intentionally remains red. No errors were suppressed. Every call used
an empty `port` input and skipped manifest updates. No trust policy, environment,
or tag changed during this probe. The root operator owns isolated object cleanup.

`evidence.json` records job links, exact failure steps, log excerpts, and local
full-log hashes. Full job logs are available through the linked GitHub run.
The preceding startup failure (run 36639189198) executed no jobs: the old tag
required a `distribution` secret. It is recorded but excluded from IAM proof.

This archive preserves the proof workflow and evidence before the live
`docs-site-deploy` branch is restored to
`da4484ad8117aa09ec2fcb0c92f83bde4aa304e6` with an exact branch lease.

## Restoration and object cleanup

The live caller branch and local checkout were verified restored and clean at
`da4484ad8117aa09ec2fcb0c92f83bde4aa304e6`. The proof workflow is absent.
The root operator verified the uploaded object body matched this run, found
zero objects in all three denied prefixes, deleted only the successful probe
object, and verified its prefix was empty. An optional public GET returned
403; its cause was not diagnosed. This proof makes no public delivery or
release-to-site latency claim. See the receipts in `evidence.json`.
