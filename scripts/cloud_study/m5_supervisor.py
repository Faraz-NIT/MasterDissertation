#!/usr/bin/env python3
"""Own the verified local-model and frozen M5 workflow without editing source.

--once is a bounded, read-only preflight: it neither starts a service nor downloads
weights nor launches a study. --run explicitly enables execution. The supervisor
holds a process lock, honors an epoch/pause control file, and only signals process
groups it started. Storage probes read at most 1 KiB over verified HTTPS; logs
never contain a redirect's query string. Model-download denial is not a result.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import io
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import uuid
import zipfile

REPO = Path('/workspace/MasterDissertation')
TOOLS = Path('/workspace/tools')
PYTHON = REPO / '.venv/bin/python'
CONFIGS = REPO / 'results/run_configs'
LOGS = REPO / 'results/logs'
STATE = CONFIGS / 'supervisor_status.json'
CONTROL = CONFIGS / 'supervisor_control.json'
PREFLIGHT = CONFIGS / 'local_model_resource_preflight.json'
OLLAMA = TOOLS / 'ollama/bin/ollama'
MODELS = TOOLS / 'ollama/models'
OFFICIAL_MANIFEST = TOOLS / 'ollama/official_llama3.2_3b_manifest.json'
REGISTRY = 'https://registry.ollama.ai/v2/library/llama3.2/'
API = 'http://127.0.0.1:11434'
BASE_MODEL = 'llama3.2:3b'
MODEL = 'ega-llama3.2:3b-cloud30'
STAGES = ['llm_template_architectures_30series', 'llm_prose_study_ollama']
DEVELOPMENT = REPO / 'results/local_model_development_30series_batch1'
EXPECTED_BINARY_SHA256 = 'c94aa4156b3d13e64ebc2efe5ea53f015384c882be776e6695cfb37fb180d5ad'
GiB = 1024 ** 3


class Blocked(RuntimeError):
    pass


class Intervention(RuntimeError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('x') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sanitize(text):
    """Log URL hostnames only, including for signed redirect errors."""
    def host(match):
        try:
            parsed = urllib.parse.urlparse(match.group(0))
            return parsed.scheme + '://' + (parsed.hostname or 'redacted-host')
        except ValueError:
            return '[redacted-url]'
    text = re.sub(r'https?://[^\s\"\'<>]+', host, str(text))
    return re.sub(r'(?i)(authorization|api[_-]?key|access[_-]?token)\s*[:=]\s*[^\s,]+',
                  r'\1=[redacted]', text)


def manifest_entries(manifest):
    if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 2:
        raise Blocked('Official model manifest schema is invalid')
    entries = [manifest['config'], *manifest['layers']]
    for entry in entries:
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', entry.get('digest', '')):
            raise Blocked('Official model manifest contains an invalid digest')
        if not isinstance(entry.get('size'), int) or entry['size'] < 0:
            raise Blocked('Official model manifest contains an invalid size')
    return entries


def official_manifest():
    # A retained manifest came from the existing TLS-verifying official downloader.
    if OFFICIAL_MANIFEST.exists():
        value = read_json(OFFICIAL_MANIFEST)
    else:
        with urllib.request.urlopen(REGISTRY + 'manifests/3b', timeout=15) as response:
            if response.status != 200:
                raise Blocked('Official model manifest unavailable')
            value = json.loads(response.read(1024 * 1024))
    manifest_entries(value)
    return value


def storage_probe(manifest=None):
    """Make one read-only official blob request, preserving TLS verification."""
    requested_host = urllib.parse.urlparse(REGISTRY).hostname
    try:
        manifest = manifest or official_manifest()
        largest = max(manifest_entries(manifest), key=lambda item: item['size'])
        request = urllib.request.Request(REGISTRY + 'blobs/' + largest['digest'],
                                         headers={'Range': 'bytes=0-1023'})
        with urllib.request.urlopen(request, timeout=15) as response:
            host = urllib.parse.urlparse(response.geturl()).hostname
            body = response.read(1024)  # A server ignoring Range still cannot fill memory/disk.
            status = response.status
            return {'host': host, 'status': status, 'bytes_read': len(body),
                    'available': status in (200, 206) and bool(body), 'checked_at_utc': utc()}
    except urllib.error.HTTPError as exc:
        return {'host': urllib.parse.urlparse(exc.url).hostname or requested_host,
                'status': exc.code, 'available': False, 'checked_at_utc': utc()}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, Blocked) as exc:
        # Exception text can contain a signed URL, so store only its class.
        return {'host': requested_host, 'status': type(exc).__name__,
                'available': False, 'checked_at_utc': utc()}


def api(path, data=None, timeout=15):
    request = urllib.request.Request(API + path, data=None if data is None else json.dumps(data).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def model_tag(name=MODEL):
    try:
        return next((model for model in api('/api/tags').get('models', []) if model['name'] == name), None)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def resource_snapshot():
    cpu_max = Path('/sys/fs/cgroup/cpu.max')
    memory_max = Path('/sys/fs/cgroup/memory.max')
    quota = None
    if cpu_max.exists():
        count, period = cpu_max.read_text().split()
        quota = None if count == 'max' else int(count) / int(period)
    memory = None
    if memory_max.exists():
        value = memory_max.read_text().strip()
        memory = None if value == 'max' else int(value)
    usage = shutil.disk_usage(REPO)
    return {'cpu_quota_cores': quota, 'visible_cpus': os.cpu_count(),
            'memory_limit_bytes': memory, 'disk_total_bytes': usage.total,
            'disk_free_bytes': usage.free, 'checked_at_utc': utc()}


def basic_preflight(probe=True):
    import yaml
    value = {'mode': 'read_only_preflight', 'resources': resource_snapshot(),
             'study_launches': 0, 'model_downloads': 0, 'service_launches': 0,
             'stages': {}, 'model': model_tag(), 'time_estimate': 'Unmeasured until real local development requests execute'}
    for stage in STAGES:
        cfg = yaml.safe_load((CONFIGS / (stage + '.yaml')).read_text())
        expected = len(cfg['policies']) * len(cfg['scenarios']) * len(cfg['seeds']) * cfg['origins']
        output = REPO / cfg['output']
        value['stages'][stage] = {'expected_runs': expected, 'expected_decisions': expected * cfg['days'],
                                  'model_revision': cfg['llm']['model_revision'], 'max_calls_per_run': cfg['llm']['max_calls'],
                                  'merge_complete': bool(read_json(output / 'merge_manifest.json', {}).get('complete'))}
    if probe and not value['model']:
        value['storage_probe'] = storage_probe()
    return value


class Supervisor:
    def __init__(self, args):
        self.args = args
        self.control = Path(args.control)
        existing = read_json(self.control)
        if existing is None:
            existing = {'epoch': args.epoch or uuid.uuid4().hex, 'pause_requested': False, 'created_at_utc': utc()}
            atomic_json(self.control, existing)
        self.epoch = args.epoch or existing.get('epoch')
        if not self.epoch:
            raise Intervention('Control file requires an epoch')
        self.server = None
        self.last_report = 0
        self.last_pack = 0
        self.status = read_json(STATE, {})
        self.check_control()

    def record(self, phase, **fields):
        self.status.update(phase=phase, epoch=self.epoch, pid=os.getpid(), updated_at_utc=utc(), **fields)
        atomic_json(STATE, self.status)
        print(json.dumps({'phase': phase, **fields}, default=str), flush=True)

    def check_control(self):
        control = read_json(self.control, {})
        if control.get('epoch') != self.epoch:
            raise Intervention('Control epoch changed; refusing to resume the old execution epoch')
        if control.get('pause_requested'):
            raise Intervention('Pause requested through supervisor control file')

    def disk_guard(self, additional=0):
        free = shutil.disk_usage(REPO).free
        threshold = int(self.args.disk_reserve_gib * GiB) + int(additional)
        if free < threshold:
            raise Blocked(f'Disk reserve gate: {free} bytes free; {threshold} bytes required')

    def wait_interval(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check_control()
            time.sleep(min(5, max(0, deadline - time.monotonic())))

    def refresh_report(self, force=False):
        generator = REPO / 'results/report/generate_report.py'
        if not generator.exists() or (not force and time.monotonic() - self.last_report < self.args.report_interval):
            return
        self.last_report = time.monotonic()
        with generator.with_name('refresh.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            try:
                with (LOGS / 'supervisor_report_refresh.log').open('a') as stream:
                    result = subprocess.run([str(PYTHON), str(generator)], cwd=REPO,
                                            env=self.environment(), stdout=stream, stderr=subprocess.STDOUT, timeout=600)
                self.status['report_refresh'] = {'returncode': result.returncode, 'updated_at_utc': utc()}
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.status['report_refresh'] = {'error': type(exc).__name__, 'updated_at_utc': utc()}

    def pack_completed(self, force=False):
        helper = TOOLS / 'm5_pack_artifacts.py'
        if not helper.exists() or (not force and time.monotonic() - self.last_pack < self.args.pack_interval):
            return
        # Pack only outputs owned by the two local-model stages. The driver will
        # take this same lock around merging, preventing mutation/copy races.
        self.last_pack = time.monotonic()
        runs = []
        for stage in STAGES:
            metadata = read_json(CONFIGS / 'pipeline_status.json', {}).get('stages', {}).get(stage, {})
            output = Path(metadata.get('output', 'results/' + stage))
            if not output.is_absolute():
                output = REPO / output
            for root in [output, *output.with_name(output.name + '_workers').glob('w[0-9]*')]:
                runs.extend(p.parent for p in root.glob('*__*__seed*__origin*/summary.json')
                            if not (p.parent / 'packing_manifest.json').exists())
        if not runs:
            return
        with (LOGS / 'artifact_merge.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with (LOGS / 'supervisor_artifact_packing.log').open('a') as stream:
                result = subprocess.run([str(PYTHON), str(helper), '--pack', *map(str, runs)], cwd=REPO,
                                        env=self.environment(), stdout=stream, stderr=subprocess.STDOUT, timeout=600)
            if result.returncode:
                raise Blocked('Verified artifact packing failed; see supervisor_artifact_packing.log')

    @staticmethod
    def environment():
        result = dict(os.environ)
        result.update(OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS=str(MODELS),
                      OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1',
                      OLLAMA_CONTEXT_LENGTH='32768', OLLAMA_KEEP_ALIVE='24h',
                      OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', PYTHONUNBUFFERED='1')
        # Authentication stays in its existing platform/user binding. HOME and
        # credential values are never replaced, inspected, or saved in logs.
        return result

    @staticmethod
    def stop_owned(process):
        if process.poll() is not None:
            return
        # Each owned job was started in a fresh session. No existing worker/server
        # PID can be targeted by this process-group operation.
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)

    def run_owned(self, command, log_name, *, timeout=None, maintenance=False, nice=0):
        self.check_control()
        self.disk_guard()
        log_path = LOGS / log_name
        with log_path.open('a') as stream:
            process = subprocess.Popen(list(map(str, command)), cwd=REPO, env=self.environment(),
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       errors='replace', start_new_session=True, bufsize=1)
            if nice:
                os.setpriority(os.PRIO_PROCESS, process.pid, nice)
            def drain():
                for line in process.stdout:
                    stream.write(sanitize(line))
                    stream.flush()
            thread = threading.Thread(target=drain, daemon=True)
            thread.start()
            started = time.monotonic()
            self.record('owned_job_running', owned_job_pid=process.pid, owned_job_log=str(log_path), command_name=Path(command[0]).name)
            try:
                while process.poll() is None:
                    self.check_control()
                    if timeout and time.monotonic() - started > timeout:
                        raise Blocked(f'Bounded command exceeded {timeout}s; retained actual artifacts for diagnosis: {log_path.name}')
                    if maintenance:
                        self.pack_completed()
                        self.refresh_report()
                    self.disk_guard()
                    time.sleep(5)
                thread.join(timeout=5)
                if process.returncode:
                    raise Blocked(f'Command exited {process.returncode}; inspect {log_path.name}')
            except BaseException:
                self.stop_owned(process)
                thread.join(timeout=5)
                raise
            finally:
                process.stdout.close()
        self.status['owned_job_pid'] = None
        return time.monotonic() - started

    def ensure_server(self):
        try:
            version = api('/api/version')
            self.record('server_available', ollama_version=version.get('version'), reused_existing_server=True)
            return
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass
        if not (Path.home() / '.ollama/id_ed25519').is_file():
            raise Blocked('Existing Ollama authentication key is absent; do not write to the user home during setup')
        with OLLAMA.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        if checksum != EXPECTED_BINARY_SHA256:
            raise Blocked('Installed Ollama binary differs from its verified installation digest')
        with (LOGS / 'supervisor_ollama_server.log').open('a') as stream:
            self.server = subprocess.Popen([str(OLLAMA), 'serve'], cwd=REPO, env=self.environment(),
                                           stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        atomic_json(TOOLS / 'ollama/supervisor_server.json', {'pid': self.server.pid, 'epoch': self.epoch, 'started_at_utc': utc()})
        for _ in range(30):
            self.check_control()
            if self.server.poll() is not None:
                raise Blocked('Owned Ollama service exited; inspect supervisor_ollama_server.log')
            try:
                version = api('/api/version', timeout=2)
                self.record('server_available', ollama_version=version.get('version'), owned_server_pid=self.server.pid)
                return
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                self.wait_interval(1)
        raise Blocked('Owned Ollama service did not pass its version endpoint readiness check')

    def ensure_model(self):
        self.ensure_server()
        tag = model_tag()
        if tag is None:
            if model_tag(BASE_MODEL) is None:
                manifest = official_manifest()
                needed = sum(e['size'] for e in manifest_entries(manifest)
                             if not (MODELS / 'blobs' / e['digest'].replace(':', '-')).exists())
                self.disk_guard(needed)
                last_failed_signature = None
                while True:
                    self.check_control()
                    probe = storage_probe(manifest)
                    # Only host/status are printed; no signed redirect/token values.
                    self.record('waiting_for_model_storage', storage_probe=probe,
                                blocker=None if probe['available'] else 'Official weight storage route is unavailable')
                    if probe['available']:
                        signature = (probe['host'], probe['status'])
                        if signature == last_failed_signature:
                            self.wait_interval(self.args.probe_interval)
                            continue
                        try:
                            self.run_owned([PYTHON, TOOLS / 'download_ollama_verified.py'],
                                           'supervisor_verified_model_download.log', timeout=self.args.download_timeout)
                            break
                        except Blocked:
                            last_failed_signature = signature
                            self.record('model_download_failed', blocker='Verified download failed; waiting for a storage connectivity change before retry')
                            self.refresh_report(force=True)
                    else:
                        last_failed_signature = None  # A later healthy route is a meaningful change.
                    self.wait_interval(self.args.probe_interval)
            # Native pull re-verifies cached content and registers the official manifest.
            self.run_owned([OLLAMA, 'pull', BASE_MODEL], 'supervisor_native_model_pull.log', timeout=self.args.download_timeout)
            self.run_owned([OLLAMA, 'create', MODEL, '-f', TOOLS / 'ollama/Modelfile.cloud30'],
                           'supervisor_model_create.log', timeout=300)
            tag = model_tag()
        if not tag or not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', tag.get('digest', '')):
            raise Blocked('Actual local model tag/digest is unavailable')
        details = api('/api/show', {'model': MODEL})
        parameters = details.get('parameters', '')
        if not re.search(r'num_ctx\s+32768\b', parameters) or not re.search(r'num_thread\s+2\b', parameters):
            raise Blocked('Actual model parameters differ from the 32768-context/two-thread protocol')
        self.record('model_verified', model_name=MODEL, model_revision=tag['digest'], model_parameters=parameters)
        return tag['digest']

    def freeze_revision(self, revision):
        import yaml
        pending = {'PENDING_LOCAL_MODEL_DOWNLOAD', revision}
        prepared = []
        # Validate every target first so a conflicting frozen stage never causes
        # a partially changed design. Never alter tracked configs.
        for stage in STAGES:
            path = CONFIGS / (stage + '.yaml')
            cfg = yaml.safe_load(path.read_text())
            if cfg['llm']['model_revision'] not in pending:
                raise Blocked(f'{stage} already pins a different actual digest')
            if cfg['llm']['model'] != MODEL or cfg['llm']['max_calls'] != 15000 or cfg['llm']['document_batch_size'] != 1:
                raise Blocked(f'{stage} differs from the prepared cloud30 model/budget protocol')
            if cfg['llm']['model_revision'] != revision:
                output = REPO / cfg['output']
                if any(output.glob('*/summary.json')) or any(output.with_name(output.name + '_workers').glob('w*/*/run_manifest.json')):
                    raise Blocked(f'{stage} contains evaluation output; refusing to rewrite its model revision')
            cfg['llm']['model_revision'] = revision
            prepared.append((path, cfg))
        protocol_path = CONFIGS / 'execution_protocol.json'
        protocol = read_json(protocol_path)
        if protocol['model_revision'] not in ('pending download; freeze before evaluation', revision):
            raise Blocked('Execution protocol already pins a different actual digest')
        for path, cfg in prepared:
            temporary = path.with_name(path.name + '.supervisor.tmp')
            temporary.write_text(yaml.safe_dump(cfg))
            temporary.replace(path)
        protocol.update(model=MODEL, model_revision=revision,
                        freeze_status='Actual verified model digest frozen; development validation/resource preflight precede evaluation')
        atomic_json(protocol_path, protocol)
        self.record('actual_model_digest_frozen', model_revision=revision)

    def functional_readiness(self, revision):
        body = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Return the integer value 2 in the requested schema.'}],
                'temperature': 0, 'max_tokens': 128,
                'response_format': {'type': 'json_schema', 'json_schema': {'name': 'readiness', 'strict': True,
                    'schema': {'type': 'object', 'properties': {'value': {'type': 'integer'}},
                               'required': ['value'], 'additionalProperties': False}}}}
        started = time.monotonic()
        answer = api('/v1/chat/completions', body, timeout=600)
        actual = json.loads(answer['choices'][0]['message']['content'])
        if actual != {'value': 2} or answer['choices'][0].get('finish_reason') == 'length':
            raise Blocked('Structured model readiness request failed')
        usage = answer.get('usage', {})
        if not usage.get('prompt_tokens') or not usage.get('completion_tokens'):
            raise Blocked('Real model response omitted positive input/output token usage')
        atomic_json(LOGS / 'ollama_cloud30_functional_readiness.json',
                    {'model_revision': revision, 'request': body, 'response': answer, 'elapsed_seconds': time.monotonic() - started})
        self.record('structured_response_verified', functional_usage=usage)

    def development_validation(self, revision):
        marker = DEVELOPMENT / 'development_manifest.json'
        previous = read_json(marker, {})
        if previous.get('complete') and previous.get('model_revision') == revision and previous.get('document_batch_size') == 1:
            return previous
        self.record('development_validation', note='30 M5 series in every actual request; paired single-document template/prose grounding on development day 1700 before all holdout/evaluation windows')
        elapsed = self.run_owned([PYTHON, Path(__file__), '--internal-development', '--model-revision', revision],
                                 'local_model_development_30series_batch1.log', timeout=self.args.development_timeout,
                                 maintenance=True, nice=10)
        manifest = read_json(marker, {})
        if not manifest.get('complete') or manifest.get('model_revision') != revision:
            raise Blocked('Development validation did not produce its complete actual-model manifest')
        manifest['supervisor_wall_seconds'] = elapsed
        atomic_json(marker, manifest)
        return manifest

    def measured_preflight(self, manifest):
        import yaml
        resources = resource_snapshot()
        seconds = []
        bytes_per_call = []
        for call in manifest['real_calls']:
            seconds.append(call['elapsed_seconds'])
            bytes_per_call.append(call['artifact_bytes'])
        if not seconds:
            raise Blocked('No actual local-model requests were available for throughput measurement')
        mean_call = statistics.mean(seconds)
        p95_call = sorted(seconds)[max(0, math.ceil(.95 * len(seconds)) - 1)]
        docs = manifest['full_contract_documents_per_day']
        from ega.agents.orchestrator import POLICIES
        estimates = {}
        all_calls = 0
        decisions = 0
        for stage in STAGES:
            cfg = yaml.safe_load((CONFIGS / (stage + '.yaml')).read_text())
            per_policy_runs = len(cfg['scenarios']) * len(cfg['seeds']) * cfg['origins']
            stage_calls = 0
            for policy in cfg['policies']:
                spec = POLICIES[policy]
                if spec['llm']:
                    # Every source ID is preserved in the frozen common batches.
                    # Successful full grounding reads all rules; triage, route
                    # and critic add up to 3 additional requests per day.
                    extraction_calls = math.ceil(docs / cfg['llm']['document_batch_size'])
                    calls_per_day = extraction_calls + (0 if spec.get('single') else 1 + 1 + int(spec['critic']))
                    stage_calls += per_policy_runs * cfg['days'] * calls_per_day
            stage_decisions = per_policy_runs * len(cfg['policies']) * cfg['days']
            estimates[stage] = {'successful_path_call_upper_estimate': stage_calls,
                                'model_seconds_at_measured_mean': stage_calls * mean_call,
                                'model_seconds_at_measured_p95': stage_calls * p95_call,
                                'decisions': stage_decisions}
            all_calls += stage_calls
            decisions += stage_decisions
        raw_request_bytes = all_calls * statistics.mean(bytes_per_call)
        ratios = [entry['zip_deflate_bytes'] / max(1, entry['raw_bytes']) for entry in manifest['pilot_storage']]
        measured_ratio = max(ratios) if ratios else 1.
        # Budget for non-request snapshots/problems/SQLite plus in-flight raw
        # artifacts. Ratios are measured samples, never a storage guarantee.
        pilot_decision_bytes = max(e['raw_bytes'] for e in manifest['pilot_storage'])
        # Successful full grounding can be longer/larger than an escalated pilot;
        # the request-based estimate guards against extrapolating early holds.
        raw_estimate = max(raw_request_bytes * 1.5, decisions * pilot_decision_bytes)
        packed_estimate = raw_estimate * measured_ratio * 1.5
        time_days = all_calls * mean_call / 86400
        # Account for the independently running required numerical studies.
        # Their future storage remains even when they do not use the model slot.
        # Real packed samples take precedence; a 4 MiB/run floor leaves margin
        # over the observed approximately 2.4 MiB archives plus retained files.
        pending_numeric_bytes = 0
        numeric_estimates = {}
        pipeline = read_json(CONFIGS / 'pipeline_status.json', {}).get('stages', {})
        for name in ['main_study_stage1', 'llm_prose_reference_30series']:
            stage_meta = pipeline.get(name, {})
            output = Path(stage_meta.get('output', 'results/' + name))
            if not output.is_absolute():
                output = REPO / output
            worker_roots = list(output.with_name(output.name + '_workers').glob('w[0-9]*'))
            roots = worker_roots or [output]
            completed = [path.parent for root in roots for path in root.glob('*__*__seed*__origin*/summary.json')]
            samples = []
            unpacked_bytes = 0
            for run in completed:
                packing = read_json(run / 'packing_manifest.json', {})
                if packing.get('state') == 'packed':
                    samples.append(sum(path.stat().st_size for path in run.rglob('*') if path.is_file()))
                else:
                    unpacked_bytes += sum(path.stat().st_size for path in run.rglob('*') if path.is_file())
            remaining = max(0, stage_meta.get('expected_runs', 0) - len(completed))
            per_run = max([4 * 1024**2, *samples])
            estimated = remaining * per_run
            pending_numeric_bytes += estimated
            numeric_estimates[name] = {'remaining_runs': remaining, 'packed_bytes_per_run_budget': per_run,
                                      'estimated_additional_packed_bytes': estimated,
                                      'existing_unpacked_bytes_already_in_disk_usage': unpacked_bytes}
        value = {'measured_at_utc': utc(), 'model_revision': manifest['model_revision'], 'resources': resources,
                 'measurement': {'real_call_records': len(seconds), 'mean_call_seconds': mean_call,
                                 'p95_call_seconds': p95_call, 'mean_request_artifact_bytes': statistics.mean(bytes_per_call),
                                 'max_actual_zip_deflate_sample_ratio': measured_ratio},
                 'estimates': estimates, 'successful_path_calls_total': all_calls,
                 'successful_path_model_only_days_at_mean': time_days,
                 'successful_path_model_only_days_at_p95': all_calls * p95_call / 86400,
                 'projected_raw_artifact_bytes': raw_estimate,
                 'projected_packed_artifact_bytes_with_margin': packed_estimate,
                 'outstanding_numeric_storage': numeric_estimates,
                 'projected_additional_numeric_packed_bytes': pending_numeric_bytes,
                 'required_disk_reserve_bytes': self.args.disk_reserve_gib * GiB,
                 'limitations': ['Development sample is not an evaluation result.',
                     'Successful-path estimate assumes every source rule is grounded; observed validation holds may shorten runs.',
                     'Model-only time excludes forecast training, optimization, report generation, scheduling contention and retries.',
                     'Compression samples are estimates; live disk reserve is enforced independently.',
                     'No human study, LLM-only numeric comparator, or severity sweep has been implemented.']}
        blockers = []
        packer_exists = (TOOLS / 'm5_pack_artifacts.py').exists()
        value['verified_artifact_packer_available'] = packer_exists
        required = (packed_estimate if packer_exists else raw_estimate) + pending_numeric_bytes
        if resources['disk_free_bytes'] < required + self.args.disk_reserve_gib * GiB:
            blockers.append('Projected artifact storage plus reserve exceeds current free disk')
        value.update(passed=not blockers, blockers=blockers)
        atomic_json(PREFLIGHT, value)
        self.record('measured_resource_preflight', resource_preflight=str(PREFLIGHT), preflight_passed=not blockers,
                    model_only_projected_days=time_days, projected_packed_bytes=packed_estimate)
        self.refresh_report(force=True)
        if blockers:
            raise Blocked('; '.join(blockers) + '; detailed truthful estimates saved in local_model_resource_preflight.json')
        return value

    def execute_stages(self):
        from m5_parallel import status
        for stage in STAGES:
            self.check_control()
            self.disk_guard()
            tag = model_tag()
            if not tag or tag['digest'] != self.status['model_revision']:
                raise Blocked('Installed model digest changed after development validation')
            status(stage, state='prepared', blocker=None, model_revision=tag['digest'], supervisor_epoch=self.epoch)
            self.record('evaluation_stage_launch', active_stage=stage)
            self.run_owned([PYTHON, TOOLS / 'm5_parallel.py', '--config', CONFIGS / (stage + '.yaml'),
                            '--workers', '1', '--stage', stage, '--pack-completed'], stage + '_supervised_driver.log',
                           maintenance=True, nice=10)
            self.pack_completed(force=True)
            self.refresh_report(force=True)
            self.record('evaluation_stage_complete', active_stage=stage)
        protocol = read_json(CONFIGS / 'execution_protocol.json')
        protocol['freeze_status'] = 'Verified local model and measured preflight; both prepared local LLM stages complete'
        atomic_json(CONFIGS / 'execution_protocol.json', protocol)
        self.record('local_llm_stages_complete', active_stage=None, blocker=None)
        self.refresh_report(force=True)

    def run(self):
        try:
            revision = self.ensure_model()
            self.freeze_revision(revision)
            self.functional_readiness(revision)
            manifest = self.development_validation(revision)
            self.measured_preflight(manifest)
            if self.args.prepare:
                self.record('prepared_after_measured_preflight', active_stage=None, blocker=None,
                            note='No evaluation studies launched in prepare mode; paired real development requests and their errors retained')
                self.refresh_report(force=True)
            else:
                self.execute_stages()
            return 0
        except (Blocked, Intervention, KeyboardInterrupt) as exc:
            state = 'paused' if isinstance(exc, (Intervention, KeyboardInterrupt)) else 'blocked'
            self.record(state, blocker=sanitize(str(exc)), owned_job_pid=None)
            self.refresh_report(force=True)
            return 2
        except Exception as exc:
            self.record('failed', blocker=sanitize(str(exc)), error_type=type(exc).__name__, owned_job_pid=None)
            self.refresh_report(force=True)
            return 1


class CountWriter(io.RawIOBase):
    def __init__(self):
        self.count = 0
    def writable(self):
        return True
    def write(self, value):
        self.count += len(value)
        return len(value)


def storage_measurement(folder):
    files = [p for p in Path(folder).rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm'))]
    writer = CountWriter()
    with zipfile.ZipFile(writer, mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(files):
            archive.write(path, arcname=str(path.relative_to(folder)))
    return {'path': str(folder), 'raw_bytes': sum(p.stat().st_size for p in files), 'zip_deflate_bytes': writer.count,
            'file_count': len(files)}


def internal_development(revision):
    """Actual, isolated pre-evaluation-day model calls; no expected labels sent."""
    import yaml
    from ega.agents.llm import LLMClient, Extraction, ModelUnavailable
    from ega.agents.roles import FORMAT_CONVENTIONS
    from ega.config import load_config
    from ega.constraints import synthetic_contracts, render_prose, render_templates
    from ega.data.panel import Panel
    from ega.evaluation.grounding import signature
    from ega.experiment import run_experiment
    from ega.store import ArtifactStore
    from ega.util import canonical
    panel = Panel.load(REPO / 'data/processed/m5')
    if panel.n != 30:
        raise Blocked('Development pilot requires all 30 prepared M5 series')
    cfg = load_config(CONFIGS / 'llm_prose_study_ollama.yaml')
    if cfg.llm.model_revision != revision:
        raise Blocked('Development configuration digest differs from the frozen actual model')
    DEVELOPMENT.mkdir(parents=True, exist_ok=True)
    marker = DEVELOPMENT / 'development_manifest.json'
    if marker.exists():
        previous = read_json(marker)
        if previous.get('model_revision') != revision or previous.get('document_batch_size') != cfg.llm.document_batch_size:
            raise Blocked('Retained development outputs pin a different model revision')
        if previous.get('complete'):
            return 0
    # The minimum serving check pairs two actual source rules across both
    # carriers, with all 30 known entities in every request. It checks actual
    # values, identities and source links without sending expected labels.
    day = 1700
    rules = synthetic_contracts(panel.series, panel.price_at(day).tolist(), panel.eligibility(day),
                                day, 4242, 'normal', False, cfg.solver.budget)
    chosen = []
    for index in [0, 1]:
        if index < len(rules) and (rules[index].constraint_id not in {r.constraint_id for r in chosen}):
            chosen.append(rules[index])
    grounding = DEVELOPMENT / 'grounding'
    grounding.mkdir(exist_ok=True)
    store = ArtifactStore(grounding / 'artifacts')
    dev_llm = cfg.llm.model_copy(deep=True)
    dev_llm.spend_ledger = str(DEVELOPMENT / 'grounding_spend.json')
    client = LLMClient(dev_llm, store)
    rows = []
    try:
        for carrier, documents in [('template', render_templates(chosen)), ('prose', render_prose(chosen))]:
            for start in range(0, len(documents), dev_llm.document_batch_size):
                batch_docs = documents[start:start + dev_llm.document_batch_size]
                batch_rules = chosen[start:start + dev_llm.document_batch_size]
                payload = {'documents': [document.payload() for document in batch_docs], 'day': day,
                           'known_entities': [s.model_dump() for s in panel.series],
                           'task': 'Extract all active source rules. Preserve values and units exactly. Do not silently resolve conflicts.',
                           'format_conventions': FORMAT_CONVENTIONS}
                before = client.calls
                try:
                    result = client.ask('supplier and constraint agent', payload, Extraction)
                    expected = {signature(rule.model_dump()) for rule in batch_rules}
                    actual = {signature(c.model_dump()) for c in result.constraints}
                    rows.append({'carrier': carrier, 'source_refs': [document.ref for document in batch_docs],
                                 'whole_set_exact_match': actual == expected, 'issues': result.issues,
                                 'false_constraints': len(actual - expected), 'omitted_constraints': len(expected - actual),
                                 'calls': client.calls - before})
                except ModelUnavailable as exc:
                    rows.append({'carrier': carrier, 'source_refs': [document.ref for document in batch_docs], 'whole_set_exact_match': False,
                                 'error': sanitize(str(exc)), 'calls': client.calls - before})
        atomic_json(grounding / 'grounding_results.json', {'development_only': True, 'series': 30, 'day': day,
                    'model_revision': revision, 'cases': rows, 'llm_calls': client.calls,
                    'tokens': client.tokens, 'llm_errors': client.errors,
                    'note': 'Field-complete controlled carriers; this sample is not a natural-language production benchmark.'})
    finally:
        store.close()
    if client.tokens <= 0:
        raise Blocked('Development extraction produced no actual model output/token usage')
    # The optional full one-day pilot has an explicit flag. Actual paired
    # source/context payloads are sufficient to measure model availability,
    # serving correctness, throughput and compression before user-authorized
    # long CPU studies; numerical components already have validated M5 runs.
    pilot_folders = []
    for carrier in (() if not os.environ.get('M5_FULL_DEVELOPMENT_PILOT') else ('prose',)):
        dev = cfg.model_copy(deep=True)
        dev.start_day, dev.days, dev.origins, dev.seeds = day, 1, 1, [4242]
        dev.scenarios, dev.policies, dev.document_carrier = ['normal'], ['B9'], carrier
        dev.output = str(DEVELOPMENT / ('pilot_' + carrier))
        dev.llm.spend_ledger = str(DEVELOPMENT / ('pilot_' + carrier + '_spend.json'))
        atomic_json(DEVELOPMENT / ('pilot_' + carrier + '_config.json'), dev.model_dump(mode='json'))
        run_experiment(dev, resume=True)
        pilot_folders.extend(sorted(Path(dev.output).glob('*__*__seed*__origin*')))
    measurements = [storage_measurement(folder) for folder in pilot_folders] or [storage_measurement(grounding)]
    calls = []
    error_artifacts = 0
    for path in DEVELOPMENT.rglob('objects/*.json'):
        obj = json.loads(path.read_text())
        if obj.get('kind') == 'llm_error':
            error_artifacts += 1
        if obj.get('kind') != 'llm_call':
            continue
        usage = obj.get('response', {}).get('usage', {})
        calls.append({'artifact': str(path), 'role': obj['role'],
                      'elapsed_seconds': obj['elapsed_seconds'], 'artifact_bytes': path.stat().st_size,
                      'prompt_tokens': usage.get('prompt_tokens'), 'completion_tokens': usage.get('completion_tokens'),
                      'finish_reason': obj['response']['choices'][0].get('finish_reason')})
    if not calls or not any((call['prompt_tokens'] or 0) > 0 and (call['completion_tokens'] or 0) > 0 for call in calls):
        raise Blocked('Development pilot has no actual measured model token usage')
    atomic_json(marker, {'complete': True, 'development_only': True, 'model_revision': revision,
                        'series': panel.n, 'day': day, 'grounding': str(grounding),
                        'document_batch_size': cfg.llm.document_batch_size,
                        'pilot_runs': len(pilot_folders), 'full_contract_documents_per_day': len(rules),
                        'real_calls': calls, 'llm_error_artifacts': error_artifacts,
                        'pilot_storage': measurements, 'created_at_utc': utc(),
                        'notes': ['Schema and semantic extraction errors remain errors.',
                                  'No model selection or gate retuning is performed on evaluation windows.',
                                  'Four actual single-document extraction checks; numerical M5 simulator prerequisites validated separately. A full development simulation pilot is optional.',
                                  'Grounding and pilot results are descriptive development checks, not full-study outcomes.']})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--once', action='store_true', help='Bounded read-only preflight; never launches a service, model download or experiment')
    modes.add_argument('--run', action='store_true', help='Explicitly enable the verified model/development/preflight/study workflow')
    modes.add_argument('--prepare', action='store_true', help='Enable verified model and real development validation/preflight, then stop before any evaluation study')
    modes.add_argument('--internal-development', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--model-revision', help=argparse.SUPPRESS)
    parser.add_argument('--control', default=str(CONTROL), help='JSON file with epoch and pause_requested; epoch change halts old execution')
    parser.add_argument('--epoch', help='Expected control epoch; mismatch stops execution')
    parser.add_argument('--probe-interval', type=float, default=60, help='Seconds between bounded official storage probes (minimum 60)')
    parser.add_argument('--disk-reserve-gib', type=float, default=2, help='Minimum free disk reserve, enforced throughout owned jobs')
    parser.add_argument('--development-timeout', type=float, default=86400, help='Bounded real development workload limit in seconds (default24h; full CPU study stages have no wall-time cap)')
    parser.add_argument('--full-development-pilot', action='store_true', help='Add one real all-30-series B9 prose development-day simulation run before preflight (may take hours)')
    parser.add_argument('--download-timeout', type=float, default=10800)
    parser.add_argument('--report-interval', type=float, default=300)
    parser.add_argument('--pack-interval', type=float, default=120)
    parser.add_argument('--no-network-probe', action='store_true', help='Omit storage probe in --once mode')
    args = parser.parse_args(argv)
    if args.disk_reserve_gib < 2 or args.probe_interval < 60:
        parser.error('Reserve must be at least 2 GiB; probe interval at least 60 seconds')
    os.chdir(REPO)
    if args.full_development_pilot:
        os.environ['M5_FULL_DEVELOPMENT_PILOT'] = '1'
    if args.once:
        print(json.dumps(basic_preflight(probe=not args.no_network_probe), indent=2))
        return 0
    if args.internal_development:
        if not args.model_revision:
            parser.error('--internal-development requires an actual --model-revision')
        return internal_development(args.model_revision)
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / 'm5_supervisor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('An M5 supervisor already owns this workflow', file=sys.stderr)
            return 2
        return Supervisor(args).run()


if __name__ == '__main__':
    raise SystemExit(main())
