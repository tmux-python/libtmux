#!/usr/bin/env python3
"""Assert completed GitHub jobs; public delivery is assessed separately."""
import json
import pathlib
import re
import sys

raw = json.loads(pathlib.Path(sys.argv[1]).read_text())
pages = raw if isinstance(raw, list) else [raw]
jobs = [job for page in pages for job in page["jobs"]]
assert jobs and all(job["status"] == "completed" for job in jobs), "run still active or jobs missing"

def select(prefix):
    return [job for job in jobs if job["name"].startswith(prefix)]

def success(prefix, count=None):
    matches = select(prefix)
    assert matches and (count is None or len(matches) == count), (prefix, len(matches))
    assert all(job["conclusion"] == "success" for job in matches), [(job["name"], job["conclusion"]) for job in matches]
    return matches

def step(job, name):
    matches = [item for item in job["steps"] if item["name"] == name]
    assert len(matches) == 1, (job["name"], name, len(matches))
    return matches[0]

success("build-libtmux-org")
assert any(" / build" in job["name"] for job in select("build-libtmux-org")), "real build job missing"
published = success("publish-libtmux-org", 1)[0]
assert step(published, "Verify artifact and build provenance")["conclusion"] == "success"
assert step(published, "Sync to this call's own prefix")["conclusion"] == "success"
assert step(published, "Upsert manifest/<port>.json")["conclusion"] == "success"
success("proof-artifacts", 4)
identical = success("proof-identical", 1)[0]
assert step(identical, "Verify artifact and build provenance")["conclusion"] == "success"
assert step(identical, "Protect immutable tag contents")["conclusion"] == "success"
assert step(identical, "Sync to this call's own prefix")["conclusion"] == "skipped"
assert step(identical, "Upsert manifest/<port>.json")["conclusion"] == "success"

negatives = select("proof-reject")
assert len(negatives) == 3, len(negatives)
for case in ("dirty", "inventory", "digest"):
    matches = [job for job in negatives if re.search(r"\b" + case + r"\b", job["name"])]
    assert len(matches) == 1, (case, len(matches))
    job = matches[0]
    assert job["conclusion"] == "failure", (case, job["conclusion"])
    assert step(job, "Verify artifact and build provenance")["conclusion"] == "failure", case
    aws = [item for item in job["steps"] if "aws-actions/configure-aws-credentials" in item["name"]]
    assert len(aws) == 1 and aws[0]["conclusion"] == "skipped", (case, aws)
    assert step(job, "Sync to this call's own prefix")["conclusion"] == "skipped", case
    assert step(job, "Upsert manifest/<port>.json")["conclusion"] == "skipped", case
public = select("proof-public")
assert len(public) == 1, len(public)
print(json.dumps({"publicationAndExpectedRejections": "passed", "publicJob": public[0]["conclusion"], "publicDelivery": "inspect archived ordinary GET responses and verified-chain.json", "jobs": [{"id": job["id"], "name": job["name"], "conclusion": job["conclusion"]} for job in jobs]}, indent=2))
