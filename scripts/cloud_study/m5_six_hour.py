#!/usr/bin/env python3
"""Run explicitly supplied frozen, all-30-series studies inside a UTC budget.

No old full-study defaults, model selection, downloads or source changes. --once
is read-only. --run owns new numerical/local-LLM driver process groups, checks
the actual pinned model digest, stops jobs at the hard job deadline, and reserves
the final interval for honest PDF/report generation. Completed runs survive;
interrupted runs never become complete experimental results.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
import uuid
import yaml

from m5_supervisor import REPO, PYTHON, TOOLS, CONFIGS, LOGS, GiB, api, atomic_json, read_json, resource_snapshot, sanitize, utc
from ega.config import load_config
from m5_parallel import status as pipeline_status

STATE = CONFIGS / 'six_hour_supervisor_status.json'
CONTROL = CONFIGS / 'six_hour_supervisor_control.json'


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Deadline requires an explicit UTC/timezone offset')
    return parsed.astimezone(timezone.utc).timestamp()


def normalized_revision(value):
    return value.removeprefix('sha256:')


def config_entry(path, category):
    path = Path(path).resolve()
    if not path.is_relative_to(CONFIGS) or not path.is_file():
        raise ValueError('Only existing frozen ignored runtime configs under results/run_configs are accepted')
    cfg = load_config(path)
    data = Path(cfg.dataset)
    if not data.is_absolute():
        data = REPO / data
    manifest = read_json(data / 'manifest.json', {})
    if manifest.get('series') != 30 or manifest.get('dataset') != 'M5' or manifest.get('synthetic') is not False:
        raise ValueError(f'{path.name}: the required actual M5 selection is all 30 prepared series')
    needs_llm = bool(set(cfg.policies) & {'B6', 'B7', 'B8', 'B9', 'B10'})
    if needs_llm != (category == 'llm'):
        raise ValueError(f'{path.name}: category differs from its frozen policy model requirements')
    output = Path(cfg.output)
    if not output.is_absolute():
        output = REPO / output
    output = output.resolve()
    if not output.is_relative_to(REPO / 'results'):
        raise ValueError('Study outputs must stay in generated repository results')
    expected = len(cfg.policies) * len(cfg.scenarios) * len(cfg.seeds) * cfg.origins
    if needs_llm:
        if not cfg.llm.enabled or cfg.llm.model_revision in ('unrecorded', 'PENDING_LOCAL_MODEL_DOWNLOAD'):
            raise ValueError('Actual local model revision must be frozen before bounded-study launch')
        if cfg.llm.base_url not in ('http://localhost:11434/v1', 'http://127.0.0.1:11434/v1'):
            raise ValueError('This CPU-budget coordinator supports the user-selected local Ollama endpoint only')
    return {'name': path.stem, 'path': str(path), 'category': category, 'output': str(output),
            'expected_runs': expected, 'expected_decisions': expected * cfg.days, 'series': 30,
            'policies': cfg.policies, 'scenarios': cfg.scenarios, 'seeds': cfg.seeds,
            'days': cfg.days, 'origins': cfg.origins, 'document_carrier': cfg.document_carrier,
            'solver': cfg.solver.model_dump(mode='json'),
            'model': cfg.llm.model if needs_llm else None,
            'model_revision': cfg.llm.model_revision if needs_llm else None,
            'config_sha256': __import__('hashlib').sha256(path.read_bytes()).hexdigest()}


def verify_actual_models(entries):
    required = {(entry['model'], entry['model_revision']) for entry in entries if entry['category'] == 'llm'}
    if not required:
        return []
    models = {item['name']: item for item in api('/api/tags').get('models', [])}
    evidence = []
    for name, revision in sorted(required):
        tag = models.get(name)
        if not tag or normalized_revision(tag['digest']) != normalized_revision(revision):
            raise ValueError(f'Actual registered local model differs from the frozen revision: {name}')
        show = api('/api/show', {'model': name})
        evidence.append({'name': name, 'actual_digest': tag['digest'], 'size_bytes': tag['size'],
                         'parameters': show.get('parameters'), 'details': tag.get('details')})
    return evidence


def snapshot(args):
    entries = [config_entry(path, 'numeric') for path in args.numeric_config]
    entries += [config_entry(path, 'llm') for path in args.llm_config]
    pending = []
    required_pending = []
    mandatory_paths = getattr(args, 'wait_for_llm_config', [])
    optional_paths = getattr(args, 'optional_llm_config', [])
    for raw in [*mandatory_paths, *optional_paths]:
        path = Path(raw).resolve()
        if not path.is_relative_to(CONFIGS) or path.suffix not in ('.yaml', '.yml'):
            raise ValueError('Pending LLM configs must be explicit ignored runtime YAML paths')
        if path.exists():
            entries.append(config_entry(path, 'llm'))
        else:
            pending.append(str(path))
            if raw in mandatory_paths:
                required_pending.append(str(path))
    if not entries:
        raise ValueError('Supply at least one frozen numeric or LLM config')
    if len({entry['name'] for entry in entries}) != len(entries) or len({entry['output'] for entry in entries}) != len(entries):
        raise ValueError('Each supplied stage requires its own name and output')
    jobs = instant(args.job_deadline_utc)
    report = instant(args.report_deadline_utc)
    if report - jobs < 60:
        raise ValueError('Reserve at least one minute after the hard job deadline for reporting')
    return {'mode': 'read_only_budget_preflight', 'checked_at_utc': utc(), 'resources': resource_snapshot(),
            'stages': entries, 'actual_models': verify_actual_models(entries),
            'job_deadline_utc': datetime.fromtimestamp(jobs, timezone.utc).isoformat(),
            'report_deadline_utc': datetime.fromtimestamp(report, timezone.utc).isoformat(),
            'remaining_job_seconds': max(0, jobs - time.time()), 'study_launches': 0,
            'pending_frozen_llm_configs': pending,
            'mandatory_pending_llm_configs': required_pending,
            'planned_concurrency': {'numeric_workers': args.numeric_workers, 'llm_workers': 1}}


class Coordinator:
    def __init__(self, args, preflight):
        self.args, self.preflight = args, preflight
        self.job_deadline = instant(args.job_deadline_utc)
        self.report_deadline = instant(args.report_deadline_utc)
        self.control = Path(args.control)
        control = read_json(self.control)
        if control is None:
            control = {'epoch': args.epoch or uuid.uuid4().hex, 'pause_requested': False,
                       'scope': 'six_hour_all30_budget', 'created_at_utc': utc()}
            atomic_json(self.control, control)
        self.epoch = args.epoch or control.get('epoch')
        if not self.epoch or control.get('epoch') != self.epoch or control.get('pause_requested'):
            raise ValueError('Expected execution epoch is absent/changed or explicitly paused')
        self.jobs = []
        self.queues = {category: [entry for entry in preflight['stages'] if entry['category'] == category]
                       for category in ('numeric', 'llm')}
        self.pending = list(preflight.get('pending_frozen_llm_configs', []))
        self.required_pending = set(preflight.get('mandatory_pending_llm_configs', []))
        self.last_report = 0
        self.last_heartbeat = 0
        self.state = {'epoch': self.epoch, 'pid': os.getpid(), 'started_at_utc': utc(),
                      'job_deadline_utc': preflight['job_deadline_utc'],
                      'report_deadline_utc': preflight['report_deadline_utc'],
                      'stage_names': [entry['name'] for entry in preflight['stages']], 'owned_jobs': [],
                      'pending_frozen_llm_configs': self.pending,
                      'note': 'All 30 series retained; reduced frozen budget design is separate from unexecuted full-study scope.'}

    def record(self, phase, **fields):
        self.state.update(phase=phase, updated_at_utc=utc(), **fields)
        self.state['owned_jobs'] = [{key: job[key] for key in ('stage', 'category', 'pid', 'log')}
                                    for job in self.jobs if job['process'].poll() is None]
        atomic_json(STATE, self.state)
        print(json.dumps({'phase': phase, **fields}), flush=True)

    def guard(self):
        value = read_json(self.control, {})
        if value.get('epoch') != self.epoch or value.get('pause_requested'):
            return 'explicit_epoch_or_pause_intervention'
        if time.time() >= self.job_deadline:
            return 'hard_job_deadline_reached'
        if resource_snapshot()['disk_free_bytes'] < self.args.disk_reserve_gib * GiB:
            return 'hard_disk_reserve_reached'
        return None

    @staticmethod
    def environment():
        result = dict(os.environ)
        result.update(OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS='/workspace/tools/ollama/models',
                      OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', PYTHONUNBUFFERED='1')
        return result

    def launch(self, entry):
        reason = self.guard()
        if reason:
            raise RuntimeError(reason)
        current = config_entry(entry['path'], entry['category'])
        if current != entry:
            raise RuntimeError('Frozen configuration changed after its budget preflight')
        verify_actual_models([entry])
        workers = self.args.numeric_workers if entry['category'] == 'numeric' else 1
        pipeline_status(entry['name'], state='prepared', required=True, budget_study=True,
                        config_path=entry['path'], output=entry['output'], expected_runs=entry['expected_runs'],
                        expected_decisions=entry['expected_decisions'], series=30,
                        supervisor_epoch=self.epoch, hard_job_deadline_utc=self.preflight['job_deadline_utc'])
        log_path = LOGS / (entry['name'] + '_budget_driver.log')
        command = [str(PYTHON), str(TOOLS / 'm5_parallel.py'), '--config', entry['path'],
                   '--workers', str(workers), '--stage', entry['name'], '--pack-completed']
        with log_path.open('a') as stream:
            process = subprocess.Popen(command, cwd=REPO, env=self.environment(),
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        os.setpriority(os.PRIO_PROCESS, process.pid, 10)
        self.jobs.append({'stage': entry['name'], 'category': entry['category'], 'pid': process.pid,
                          'process': process, 'entry': entry, 'log': str(log_path), 'handled': False})
        self.record('study_stage_launched', active_stage=entry['name'])

    def stop_owned(self, reason):
        live = [job for job in self.jobs if job['process'].poll() is None]
        for job in live:
            os.killpg(job['pid'], signal.SIGINT)
        deadline = time.monotonic() + 30
        while any(job['process'].poll() is None for job in live) and time.monotonic() < deadline:
            time.sleep(.25)
        for job in live:
            if job['process'].poll() is None:
                os.killpg(job['pid'], signal.SIGKILL)
                job['process'].wait(timeout=10)
            pipeline_status(job['stage'], state='budget_stopped' if reason == 'hard_job_deadline_reached' else 'paused',
                            stop_reason=reason, supervisor_epoch=self.epoch,
                            note='Only completed summaries count as results; partial audit artifacts are retained.')
        for category in self.queues:
            for entry in self.queues[category]:
                pipeline_status(entry['name'], state='unrun_within_budget', stop_reason=reason,
                                required=True, budget_study=True, output=entry['output'], config_path=entry['path'],
                                expected_runs=entry['expected_runs'], expected_decisions=entry['expected_decisions'], series=30)
        for raw in self.pending:
            pipeline_status(Path(raw).stem, state='unrun_within_budget', stop_reason=reason,
                            required=raw in self.required_pending, budget_study=True,
                            config_path=raw, series=30, supervisor_epoch=self.epoch,
                            note='Requested frozen LLM configuration was not supplied/validated; no expected run count is invented.')

    def refresh_report(self, final=False):
        if not final and time.monotonic() - self.last_report < self.args.report_interval:
            return
        generator = Path(self.args.report_generator)
        if not generator.exists():
            self.state['report_refresh'] = {'status': 'unavailable', 'generator': str(generator)}
            return
        # A progress PDF must not delay enforcement of the job cutoff. The
        # reserved final interval permits a longer final generation command.
        timeout = min(600 if final else 60, max(1, (self.report_deadline if final else self.job_deadline) - time.time()))
        if time.time() >= self.report_deadline:
            self.state['report_refresh'] = {'status': 'report_deadline_elapsed'}
            return
        self.last_report = time.monotonic()
        with generator.with_name('refresh.lock').open('a') as lock:
            retry_until = min(self.report_deadline, time.time() + 60)
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not final or time.time() >= retry_until:
                        self.state['report_refresh'] = {'status': 'another_report_refresh_active'}
                        return
                    time.sleep(.5)
            try:
                with (LOGS / 'six_hour_report_refresh.log').open('a') as stream:
                    command = [str(PYTHON), str(generator), *self.args.report_arg]
                    if final:
                        command.append('--final-snapshot')
                    result = subprocess.run(command, cwd=REPO,
                                            env=self.environment(), stdout=stream,
                                            stderr=subprocess.STDOUT, timeout=timeout)
                self.state['report_refresh'] = {'returncode': result.returncode, 'at_utc': utc()}
            except subprocess.TimeoutExpired:
                self.state['report_refresh'] = {'status': 'timed_out', 'at_utc': utc()}

    def accept_pending_configs(self):
        """Only explicitly named future files can add an LLM stage to this epoch."""
        for raw in list(self.pending):
            if not Path(raw).is_file():
                continue
            try:
                entry = config_entry(raw, 'llm')
                evidence = verify_actual_models([entry])
            except (ValueError, OSError, yaml.YAMLError) as exc:
                # The parent may still be atomically freezing the file/model.
                # Keep numerical work moving; never launch a pending revision.
                self.state['pending_config_validation'] = {'path': raw, 'status': 'waiting_for_valid_frozen_config',
                                                           'error': sanitize(str(exc)), 'checked_at_utc': utc()}
                continue
            if entry['name'] in self.state['stage_names'] or entry['output'] in {
                    existing['output'] for existing in self.preflight['stages']}:
                raise RuntimeError('Pending LLM stage duplicates an existing frozen stage/output')
            self.queues['llm'].append(entry)
            self.pending.remove(raw)
            self.required_pending.discard(raw)
            self.preflight['stages'].append(entry)
            self.preflight['actual_models'].extend(evidence)
            self.preflight['pending_frozen_llm_configs'] = list(self.pending)
            self.preflight['mandatory_pending_llm_configs'] = sorted(self.required_pending)
            self.state['stage_names'].append(entry['name'])
            self.state['pending_frozen_llm_configs'] = list(self.pending)
            atomic_json(CONFIGS / 'six_hour_runtime_preflight.json', self.preflight)
            self.record('frozen_pending_llm_stage_accepted', stage=entry['name'], actual_model=evidence)

    def run(self):
        atomic_json(CONFIGS / 'six_hour_runtime_preflight.json', self.preflight)
        self.record('six_hour_execution_started')
        stop_reason = None
        try:
            while True:
                stop_reason = self.guard()
                if stop_reason:
                    self.stop_owned(stop_reason)
                    break
                self.accept_pending_configs()
                for job in self.jobs:
                    if not job['handled'] and job['process'].poll() is not None:
                        job['handled'] = True
                        code = job['process'].returncode
                        self.record('stage_process_finished', stage=job['stage'], returncode=code)
                        if code:
                            pipeline_status(job['stage'], state='failed', blocker='Driver failed; inspect retained stage budget log',
                                            supervisor_epoch=self.epoch)
                        # A failure is recorded and independent categories still
                        # progress. No failed run is relabeled or retried blindly.
                for category in ('numeric', 'llm'):
                    live = any(job['category'] == category and job['process'].poll() is None for job in self.jobs)
                    if not live and self.queues[category]:
                        self.launch(self.queues[category].pop(0))
                self.refresh_report()
                if time.monotonic() - self.last_heartbeat >= 60:
                    self.last_heartbeat = time.monotonic()
                    self.record('budget_work_running', remaining_job_seconds=max(0, self.job_deadline - time.time()),
                                pending_frozen_llm_configs=list(self.pending))
                if not any(job['process'].poll() is None for job in self.jobs) and not any(self.queues.values()) and not self.required_pending:
                    stop_reason = 'all_supplied_stage_processes_finished'
                    break
                time.sleep(min(5, max(.1, self.job_deadline - time.time())))
        except KeyboardInterrupt:
            stop_reason = 'explicit_supervisor_interrupt'
            self.stop_owned(stop_reason)
        except Exception as exc:
            stop_reason = 'coordinator_error'
            self.state['error'] = sanitize(str(exc))
            self.stop_owned(stop_reason)
        self.record('final_report_generation', stop_reason=stop_reason)
        self.refresh_report(final=True)
        failed = [job['stage'] for job in self.jobs if job['process'].returncode]
        phase = 'finished_with_budget_limits' if stop_reason != 'all_supplied_stage_processes_finished' or failed else 'all_supplied_studies_complete'
        report_ok = self.state.get('report_refresh', {}).get('returncode') == 0
        if not report_ok:
            phase = 'final_report_incomplete'
        self.record(phase, stop_reason=stop_reason, failed_or_interrupted_stages=failed,
                    note='Final report must disclose reduced design, actual coverage, failures and unexecuted scope.')
        return 0 if phase == 'all_supplied_studies_complete' else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true', help='Read-only config/resource/actual-model preflight; no process launches')
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--numeric-config', action='append', default=[], help='Frozen all30-series numeric runtime YAML; can be repeated')
    parser.add_argument('--llm-config', action='append', default=[], help='Frozen all30-series live local-model runtime YAML; can be repeated')
    parser.add_argument('--wait-for-llm-config', action='append', default=[], help='Explicit future runtime YAML path; start numeric work now and accept this LLM stage only after its config and actual model digest are frozen')
    parser.add_argument('--optional-llm-config', action='append', default=[], help='Explicit optional future runtime YAML; accept if it freezes while other work runs, but do not wait for this file after mandatory stages finish')
    parser.add_argument('--numeric-workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--job-deadline-utc', required=True, help='Absolute timezone-qualified instant to stop owned study jobs')
    parser.add_argument('--report-deadline-utc', required=True, help='Absolute final-report deadline after the job cutoff')
    parser.add_argument('--disk-reserve-gib', type=float, default=2)
    parser.add_argument('--epoch')
    parser.add_argument('--control', default=str(CONTROL))
    parser.add_argument('--report-generator', default=str(REPO / 'results/report/generate_report.py'))
    parser.add_argument('--report-arg', action='append', default=None, help='Override report arguments (repeat using --report-arg=VALUE); default --scope six-hour')
    parser.add_argument('--report-interval', type=float, default=300)
    args = parser.parse_args(argv)
    if args.report_arg is None:
        args.report_arg = ['--scope', 'six-hour']
    if args.disk_reserve_gib < 2:
        parser.error('Minimum disk reserve is2GiB')
    os.chdir(REPO)
    try:
        preflight = snapshot(args)
        if args.once:
            print(json.dumps(preflight, indent=2))
            return 0
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / 'm5_six_hour.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return Coordinator(args, preflight).run()
    except (ValueError, OSError) as exc:
        print(sanitize(str(exc)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
