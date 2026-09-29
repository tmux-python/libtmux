#!/usr/bin/env python3
"""Compare downloaded S3 bytes against the original hosted artifact inventory."""
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
load=lambda name: json.loads((root/name).read_text())
record=load('original-build-provenance.json')
descriptor=load('original-descriptor/publication.json')
version=record['version']
prefix=f"en/py/{version}/"
expected={item['path']: item for item in record['files']}
raw=(root/'original-build-provenance.json').read_bytes()
expected['build-provenance.json']={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
listing=load('s3-list-after.json')
objects={item['Key'].removeprefix(prefix):item for item in listing.get('Contents',[])}
assert set(objects)==set(expected), {'missing': sorted(set(expected)-set(objects)), 'extra':sorted(set(objects)-set(expected))}
local={str(path.relative_to(root/'s3-tree')):path for path in (root/'s3-tree').rglob('*') if path.is_file()}
assert set(local)==set(expected)
for path, item in expected.items():
    assert not local[path].is_symlink(),path
    body=local[path].read_bytes()
    assert len(body)==item['size']==objects[path]['Size'],path
    assert hashlib.sha256(body).hexdigest()==item['sha256'],path
manifest=load('manifest-after.json')
entries=[item for item in manifest['ports']['py'] if item['slug']==version]
assert len(entries)==1
receipt=entries[0]['publication']
assert receipt['artifact']==descriptor['artifact']
assert receipt['operation']=='published'
assert receipt['build']['sha256']==expected['build-provenance.json']['sha256']
first=load('manifest-first.json')
first_entry=next(item for item in first['ports']['py'] if item['slug']==version)
assert first_entry['publication']==receipt, 'immutable rerun changed original receipt'
before=load('manifest-before-first.json')
assert manifest['defaultVersion']==before['defaultVersion']
assert [item for item in manifest['ports']['py'] if item['slug']!=version]==before['ports']['py']
print(json.dumps({'s3InventoryVerified':True,'objects':len(objects),'bytes':sum(item['Size'] for item in objects.values()),'buildSha256':expected['build-provenance.json']['sha256'],'originalReceiptPreserved':True,'unrelatedManifestRowsAndDefaultPreserved':True,'receipt':receipt},indent=2))
