"""Prepare, inspect, or run the incident XAI agent using existing main components."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from imaks_kg.detection.engine import run as engine, overlay
from imaks_kg.rag import demo, incident_agent, incident_tools, team_runtime, team_retrieval, vector as v
from run_agent_v4 import load_local_key


def prepare():
    run_dir = incident_tools.ENGINE_RUN
    overlay_dir = incident_tools.ENGINE_OVERLAY
    if not run_dir.exists():
        engine.run('v3_1', run_dir)
    if not overlay_dir.exists():
        overlay.load(run_dir, overlay_dir)
    store = incident_tools.IncidentStore()
    report = {'engine_config': 'v3_1', 'incidents': len(store.incidents),
              'alarms': len(store.alarms), 'correlation_candidates': len(store.correlations),
              'new_model_calls': 0, 'gold_loaded': False, 'lock': store.lock()}
    v.write(ROOT / 'kg_build/xai_setup_20261113.json', report)
    print(json.dumps({key: report[key] for key in ('engine_config', 'incidents', 'alarms', 'correlation_candidates', 'new_model_calls')},
                     ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true', help='Free detector -> overlay preparation and integrity checks')
    action.add_argument('--prepare-team', action='store_true', help='Prepare all selectable original detectors; no model calls')
    action.add_argument('--inspect', action='store_true', help='Free incident list and source-path inspection')
    action.add_argument('--serve', action='store_true', help='Open the local XAI application backend')
    action.add_argument('--question', help='One real model-routed question; API costs apply')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--detector-profile', choices=team_runtime.PROFILES, default=team_runtime.DEFAULTS['detector_profile'])
    parser.add_argument('--document-mode', choices=team_runtime.SEARCH_MODES, default=team_runtime.DEFAULTS['document_mode'])
    parser.add_argument('--reuse-embedding-cache', type=Path)
    parser.add_argument('--read-only', action='store_true', help='Serve saved results without a key; reject generation')
    parser.add_argument('--allow-local-analysis', action='store_true', help='Explicitly enable CSV analysis APIs (local writes, no model calls)')
    parser.add_argument('--repair-incident', action='store_true', help='Opt in to one extra incident draft/verification for --question')
    args = parser.parse_args()
    if args.read_only and not args.serve:
        parser.error('--read-only requires --serve')
    if args.allow_local_analysis and not args.serve:
        parser.error('--allow-local-analysis requires --serve')
    if args.repair_incident and args.question is None:
        parser.error('--repair-incident requires --question')
    if args.prepare:
        prepare()
        return
    if args.prepare_team:
        if args.reuse_embedding_cache:
            team_retrieval.prepare_index(args.reuse_embedding_cache)
        for profile in team_runtime.PROFILES:
            print(json.dumps(team_runtime.prepare_profile(profile), ensure_ascii=False), flush=True)
        return
    store = team_runtime.store(args.detector_profile)
    if args.inspect:
        listing = incident_tools.list_incidents(store, {'offset': 0, 'limit': 20})
        print(json.dumps(listing, ensure_ascii=False, indent=2))
        return
    if not args.read_only:
        load_local_key()
    if args.serve:
        from imaks_kg.rag.sensor_analysis import AnalysisService
        page = ROOT / 'src/imaks_kg/rag/xai_demo.html'
        display_path = ROOT / 'kg_build/xai_display.json'
        hidden_runs = v.read(display_path).get('hidden_run_ids', []) if display_path.exists() else []
        server = demo.make_server(args.port, agent_answer=incident_agent.answer, page=page,
            hidden_run_ids=hidden_runs, incident_store_factory=team_runtime.store,
            agent_options={'detector_profile':set(team_runtime.PROFILES), 'document_mode':set(team_runtime.SEARCH_MODES),
                           'repair_incident': {True, False}},
            team_config=team_runtime.application_config, generation_enabled=not args.read_only,
            analysis_service=AnalysisService() if args.allow_local_analysis else None)
        print(f'XAI demo http://127.0.0.1:{server.server_port}/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return
    if not args.run_dir:
        parser.error('--question requires a new --run-dir')
    result = incident_agent.answer(args.question, args.run_dir, detector_profile=args.detector_profile,
                                   document_mode=args.document_mode, repair_incident=args.repair_incident)
    print(json.dumps({'status': result['status'], 'answer': result['answer'], 'run_dir': str(args.run_dir)}, ensure_ascii=False, indent=2))
    if result['status'] == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
