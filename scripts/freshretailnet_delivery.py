"""Reassemble and optionally restore the complete FreshRetailNet Git evidence."""
import argparse,gzip,importlib.util,json,os,shutil,zipfile
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('study_delivery',ROOT/'scripts/study_delivery.py')
delivery=importlib.util.module_from_spec(spec);spec.loader.exec_module(delivery)

def restore_linked(folder,destination,info,archives):
    inventory=delivery.safe_path(folder,info['inventory']['path'])
    if delivery.digest(inventory)!=info['inventory']['sha256']:
        raise ValueError('Study file inventory failed verification')
    with gzip.open(inventory,'rt') as stream:records=json.load(stream)['files']
    destination.mkdir(parents=True,exist_ok=True);written={};verified=linked=total=0
    with ExitStack() as stack:
        opened={key:stack.enter_context(zipfile.ZipFile(path)) for key,path in archives.items()}
        for record in records:
            target=delivery.safe_path(destination,record['path']);key=(record['sha256'],record['bytes'])
            if target.exists():
                if target.stat().st_size!=record['bytes'] or delivery.digest(target)!=record['sha256']:
                    raise ValueError(f'Preserve different existing study file:{target}')
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                if key in written:
                    os.link(written[key],target);linked+=1
                else:
                    with opened[record['archive']].open(record['member']) as source,target.open('xb') as output:
                        shutil.copyfileobj(source,output)
                if target.stat().st_size!=record['bytes'] or delivery.digest(target)!=record['sha256']:
                    raise ValueError(f'Restored study file failed verification:{target}')
            written.setdefault(key,target);verified+=1;total+=record['bytes']
            if verified%10000==0:print(f'Restored and verified {verified:,} paths',flush=True)
    return {'files':verified,'source_bytes':total,'unique_contents':len(written),
            'hardlinked_aliases_created':linked,'mode':'Identical files share hardlinks; use as read-only evidence'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives-dir',type=Path,default=ROOT/'study_results/reassembled/freshretailnet')
    parser.add_argument('--restore',type=Path,help='Restore original result/data/source paths, verifying every byte')
    parser.add_argument('--link-identical',action='store_true',help='Reduce storage using hardlinks for identical bytes; use restored evidence read-only')
    parser.add_argument('--receipt',type=Path,help='Write a verified restoration receipt after every original path passes')
    args=parser.parse_args();folder=ROOT/'study_results/freshretailnet';info=json.loads((folder/'archives.json').read_text())
    if (args.link_identical or args.receipt) and not args.restore:parser.error('--link-identical and --receipt require --restore')
    archives=delivery.reassemble(folder,args.archives_dir,info)
    if args.restore:
        if args.link_identical:restored=restore_linked(folder,args.restore,info,archives)
        else:
            delivery.restore(folder,args.restore,info,archives)
            restored={'files':info['inventory']['files'],'source_bytes':info['inventory']['source_bytes'],'mode':'Separate file copies'}
        receipt={'status':'VERIFIED','verified_at_utc':datetime.now(timezone.utc).isoformat(),
                 'destination':str(args.restore),'inventory_sha256':info['inventory']['sha256'],
                 'archives':{key:info['archives'][key]['sha256'] for key in archives},**restored}
        if args.receipt:
            args.receipt.parent.mkdir(parents=True,exist_ok=True);args.receipt.write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps(receipt),flush=True)

if __name__=='__main__':main()
