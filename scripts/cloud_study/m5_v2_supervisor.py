"""Own one isolated pilot process and enforce its registered hard cutoff."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT=Path('/workspace/MasterDissertation')
OUT=ROOT/'results/v2_pilot'
protocol=json.loads((OUT/'protocol.json').read_text())
cutoff=datetime.fromisoformat(protocol['experiment_cutoff_utc'])
state_path=OUT/'supervisor.json'


def save(state):
    state['updated_at_utc']=datetime.now(timezone.utc).isoformat()
    temp=state_path.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2));temp.replace(state_path)


if state_path.exists():raise FileExistsError('Refusing to replace existing owner state')
environment=dict(os.environ)
environment.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',
                   NUMEXPR_NUM_THREADS='1',PYTHONUNBUFFERED='1')
state={'owner_pid':os.getpid(),'started_at_utc':datetime.now(timezone.utc).isoformat(),
       'experiment_cutoff_utc':cutoff.isoformat(),'phase':'launching','child_exit_code':None}
save(state)
with (OUT/'evaluation.stdout.log').open('x') as log:
    child=subprocess.Popen([sys.executable,'/workspace/tools/m5_v2_pilot.py','run'],cwd=ROOT,
        env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    state.update(child_pid=child.pid,owned_process_group=child.pid,phase='running');save(state)
    next_save=time.monotonic()+15
    while child.poll() is None:
        if datetime.now(timezone.utc)>=cutoff:
            state['phase']='deadline_termination';save(state)
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            break
        if time.monotonic()>=next_save:save(state);next_save=time.monotonic()+15
        time.sleep(.25)
    state.update(child_exit_code=child.returncode,phase='completed' if child.returncode==0 else 'stopped_or_failed',
                 finished_at_utc=datetime.now(timezone.utc).isoformat())
    save(state)
    print(json.dumps(state),flush=True)
    sys.exit(child.returncode if child.returncode>=0 else 1)
