#!/usr/bin/env python3
"""Freeze or verify a private, whole-page trial package; never calls a model."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.exports.snapshots import write_private


def verify(package,data_root):
    if package.is_symlink():raise ValueError('Package cannot be a symlink')
    package=package.resolve();data_root=data_root.resolve()
    if not package.is_relative_to(data_root):raise ValueError('Package must be inside private data root')
    if package.stat().st_mode&0o077 or package.parent.stat().st_mode&0o077:raise ValueError('Private package permissions required')
    raw=package.read_bytes();data=json.loads(raw)
    if data.get('schema')!='study-workbench.private-trial.v1':raise ValueError('Unsupported trial schema')
    pages={}
    for page in data['pages']:
        sha=page['sha256'];key=page['storage_key'];path=(data_root/key).resolve()
        if not path.is_relative_to(data_root) or (data_root/key).is_symlink():raise ValueError('Source path escapes data root')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source hash mismatch')
        if path.stat().st_mode&0o077:raise ValueError('Private source permissions required')
        with Image.open(path) as image:
            if (page['width'],page['height'])!=image.size:raise ValueError('Source dimensions mismatch')
        if sha in pages or page['split'] not in {'development','holdout'}:raise ValueError('Pages must be unique and assigned once')
        pages[sha]=page
    if {p['split'] for p in pages.values()}!={'development','holdout'}:raise ValueError('Both whole-page splits required')
    ids=set()
    for case in data['cases']:
        if case['id'] in ids or not case['question_text'].strip():raise ValueError('Unique case IDs and verified text required')
        ids.add(case['id']);page=pages[case['image_sha256']]
        if case['split']!=page['split']:raise ValueError('Case/page split mismatch')
        x0,y0,x1,y1=case['original_bbox']
        if not all(type(v) in (int,float) and math.isfinite(v) for v in (x0,y0,x1,y1)):raise ValueError('Finite coordinates required')
        if not (0<=x0<x1<=page['width'] and 0<=y0<y1<=page['height']):raise ValueError('Case region outside original')
        if case['author_state']!='unknown' or case['actual_date'] is not None or case['independence']!='unknown':
            raise ValueError('Legacy unknown provenance cannot be inferred by this trial package')
        if case['reviewer']!='primary-agent-visual' or not case['truth_gaps']:raise ValueError('Review origin and remaining truth gaps required')
    return {'schema':'study-workbench.trial-freeze.v1','package_sha256':hashlib.sha256(raw).hexdigest(),
        'page_sha256':sorted(pages),'case_ids':sorted(ids),'external_requests':0,
        'human_family_trial_complete':False,'model_evaluation_complete':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True);parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args();result=verify(args.package,args.data_root)
    frozen=args.package.with_name('freeze.local.json')
    if args.freeze:
        encoded=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2).encode()
        if frozen.exists():
            if json.loads(frozen.read_text())!=result:raise ValueError('Frozen package changed; create a new version')
        else:write_private(frozen,encoded)
    else:
        if json.loads(frozen.read_text())!=result:raise ValueError('Frozen package or original changed')
    print(json.dumps({'pages':len(result['page_sha256']),'cases':len(result['case_ids']),
        'frozen':True,'external_requests':0,'human_trial_complete':False,'model_evaluation_complete':False}))


if __name__=='__main__':main()
