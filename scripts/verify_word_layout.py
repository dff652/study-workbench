#!/usr/bin/env python3
"""Render verified Word snapshots through an explicitly owned Office image.

No network or application database is used. Source snapshots are read-only;
copies and rendered PDFs live in a new private verification directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.exports.snapshots import verify_snapshot


def run(command):
    return subprocess.run(command,check=True,text=True,capture_output=True,timeout=300)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--office-image',required=True)
    parser.add_argument('--image-owner',required=True)
    parser.add_argument('--source-report',type=Path,required=True)
    args=parser.parse_args()
    details=json.loads(run(['docker','image','inspect',args.office_image]).stdout)[0]
    if details['Config']['Labels'].get('com.study-workbench.resource-owner')!=args.image_owner:
        raise RuntimeError('Office image ownership does not match the supplied evidence')
    image_id=details['Id']
    source=json.loads(args.source_report.read_text())
    token=uuid.uuid4().hex
    owner='swb-word-'+token
    output=ROOT/'artifacts/word-verification'/token
    output.mkdir(parents=True,mode=0o700)
    for parent in [output,output.parent,output.parent.parent]:parent.chmod(0o700)
    inputs=output/'input';pdfs=output/'pdf';inputs.mkdir(mode=0o700);pdfs.mkdir(mode=0o700)
    records=[]
    # Writer can silently drop OMML when its optional Math component is absent.
    # Render a native fraction with distinctive tokens as a canary.
    from docx import Document
    from docx.oxml import OxmlElement
    canary=Document()
    paragraph=canary.add_paragraph('Native equation verification')
    equation=OxmlElement('m:oMath')
    fraction=OxmlElement('m:f')
    for tag,value in [('m:num','314159'),('m:den','271828')]:
        part=OxmlElement(tag); run_node=OxmlElement('m:r'); token_node=OxmlElement('m:t')
        token_node.text=value; run_node.append(token_node); part.append(run_node); fraction.append(part)
    equation.append(fraction)
    paragraph._p.append(equation)
    canary.save(inputs/'native-math-canary.docx')
    for entry in source['documents']:
        directory=Path(entry['directory']).resolve()
        if not directory.is_relative_to(ROOT/'exports'):
            raise RuntimeError('Office regression sources must be verified project export snapshots')
        manifest=verify_snapshot(directory)
        original=directory/'document.docx'
        name=manifest['inputs']['document']['document_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',name):raise RuntimeError('Invalid local document ID')
        destination=inputs/(name+'.docx')
        shutil.copyfile(original,destination);destination.chmod(0o600)
        records.append({'document_id':name,'source_directory':str(directory),
            'source_sha256':manifest['files']['document.docx']['sha256'],
            'source_export_id':manifest['export_id'],'expected_pages':manifest['page_count']})
    name=owner
    try:
        run(['docker','create','--name',name,'--label','com.study-workbench.resource-owner='+owner,
            '--network','none','--read-only','--memory','768m','--cpus','1','--pids-limit','128',
            '--security-opt','no-new-privileges:true','--cap-drop','ALL','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=128m',
            '--user',f'{os.getuid()}:{os.getgid()}',
            '--mount',f'type=bind,src={inputs},dst=/input,readonly',
            '--mount',f'type=bind,src={pdfs},dst=/output',
            '--env','SAL_USE_VCLPLUGIN=svp',image_id,
            'soffice','-env:UserInstallation=file:///tmp/profile','--headless','--norestore',
            '--convert-to','pdf:writer_pdf_Export','--outdir','/output',
            '/input/native-math-canary.docx',
            *['/input/'+r['document_id']+'.docx' for r in records]])
        result=run(['docker','start','--attach',name])
        (output/'office.log').write_text(result.stdout+result.stderr)
        code=json.loads(run(['docker','inspect',name]).stdout)[0]['State']['ExitCode']
        if code:raise RuntimeError('Office converter exited unsuccessfully')
        version=run(['docker','run','--rm','--label','com.study-workbench.resource-owner='+owner,
            '--network','none','--read-only',image_id,'soffice','--version']).stdout.strip()
        canary_text=run(['pdftotext',str(pdfs/'native-math-canary.pdf'),'-']).stdout
        if not all(token in canary_text for token in ('314159','271828')):
            raise RuntimeError('Office dropped native equations; verify the Math component before accepting layout')
        for record in records:
            pdf=pdfs/(record['document_id']+'.pdf')
            if not pdf.is_file():raise RuntimeError('Office did not produce a PDF')
            pdf.chmod(0o600)
            info=run(['pdfinfo',str(pdf)]).stdout
            pages=int(re.search(r'^Pages:\s+(\d+)',info,re.M)[1])
            bbox=pdfs/(record['document_id']+'.bbox.html')
            run(['pdftotext','-bbox',str(pdf),str(bbox)])
            doc=ET.parse(bbox)
            boxes=list(doc.iter('{http://www.w3.org/1999/xhtml}page'))
            violations=[]
            for n,page in enumerate(boxes,1):
                width,height=float(page.attrib['width']),float(page.attrib['height'])
                for word in page.iter('{http://www.w3.org/1999/xhtml}word'):
                    x0,y0,x1,y1=[float(word.attrib[k]) for k in ['xMin','yMin','xMax','yMax']]
                    if x0<0 or y0<0 or x1>width+.5 or y1>height+.5:violations.append(n)
            record.update(actual_pages=pages,page_count_matches=pages==record['expected_pages'],
                bbox_violations=sorted(set(violations)),pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
            run(['pdftoppm','-scale-to','900','-png',str(pdf),str(pdfs/record['document_id'])])
        report={'office_version':version,'office_image_id':image_id,'network':'none','native_math_canary':'passed',
            'source_files_unchanged':all(
                hashlib.sha256((inputs/(r['document_id']+'.docx')).read_bytes()).hexdigest()==r['source_sha256']
                and hashlib.sha256((Path(r['source_directory'])/'document.docx').read_bytes()).hexdigest()==r['source_sha256']
                for r in records),
            'documents':records,'manual_visual_review':'pending'}
        (output/'verification.local.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        for path in output.rglob('*'):
            path.chmod(0o700 if path.is_dir() else 0o600)
        print(json.dumps({'report':str(output/'verification.local.json'),'office_version':version,
            'documents':[{k:r[k] for k in ['document_id','expected_pages','actual_pages','bbox_violations']} for r in records]},ensure_ascii=False))
    finally:
        existing=subprocess.run(['docker','inspect',name],text=True,capture_output=True)
        if existing.returncode==0:
            value=json.loads(existing.stdout)[0]
            if value['Config']['Labels'].get('com.study-workbench.resource-owner')==owner:
                run(['docker','rm','--force',name])


if __name__=='__main__':main()
