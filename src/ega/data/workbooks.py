"""Small safe OOXML value reader for constraint carriers.

Only cell values are read; formulas, macros, external links, and oversized ZIP members
are rejected. Formula calculation and arbitrary Excel layouts are intentionally unsupported.
"""
from __future__ import annotations
import posixpath
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

def read_workbook(path: str | Path, max_bytes: int=8_000_000) -> list[dict]:
    result=[]
    with ZipFile(path) as z:
        if sum(x.file_size for x in z.infolist())>max_bytes:
            raise ValueError('Workbook exceeds uncompressed size limit')
        if any('externallinks' in x.filename.lower() or 'vbaproject' in x.filename.lower() for x in z.infolist()):
            raise ValueError('External links and macros are not accepted')
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            shared=[''.join(node.itertext()) for node in root.findall('m:si',NS)]
        relroot=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rels={x.attrib['Id']:x.attrib['Target'] for x in relroot}
        workbook=ET.fromstring(z.read('xl/workbook.xml'))
        for sheet in workbook.findall('m:sheets/m:sheet',NS):
            target=rels[sheet.attrib['{'+NS['r']+'}id']]
            member=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            if not member.startswith('xl/') or '..' in member.split('/'):
                raise ValueError('Unsafe worksheet path')
            xml=ET.fromstring(z.read(member)); cells=[]
            for c in xml.findall('.//m:sheetData/m:row/m:c',NS):
                if c.find('m:f',NS) is not None: raise ValueError(f"Formula not accepted in {sheet.attrib['name']}!{c.attrib.get('r')}")
                typ=c.attrib.get('t','n'); v=c.find('m:v',NS)
                if typ=='inlineStr': val=''.join(c.find('m:is',NS).itertext())
                elif v is None: val=''
                elif typ=='s': val=shared[int(v.text)]
                else: val=v.text or ''
                cells.append({'cell':c.attrib.get('r',''),'value':val})
            result.append({'sheet':sheet.attrib['name'],'cells':cells})
    return result

def parse_season_month(season_start_year: int, season_start_month: int, month: int) -> tuple[int,int]:
    if not 1<=month<=12 or not 1<=season_start_month<=12:
        raise ValueError('Months must lie in 1..12')
    return season_start_year + int(month<season_start_month),month

def cluster_union(clusters: list[str], locations: list[dict]) -> list[str]:
    valid={x['cluster'] for x in locations}|{'ALL'}
    if set(clusters)-valid: raise ValueError('Unknown cluster')
    return sorted({x['location'] for x in locations if 'ALL' in clusters or x['cluster'] in clusters})
