"""Private portable result bundles. Exact bytes, bounded reads, no overwrite or execution."""
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from . import comparison as c, sensor_analysis as a, vector as v
from ..detection.engine import overlay

VERSION='sensor-analysis-bundle-v1-20261115'
MAX_ZIP_BYTES=32*1024*1024
MAX_EXPANDED_BYTES=64*1024*1024
ALLOWED={'upload.csv','input.csv','input_manifest.json','calibration.json','summary.json','complete.json','state.json','request.json',
         'run/params.json','run/ir.json','run/events.json','run/signals.json','run/monitor_windows.json',
         'run/incidents.json','run/correlations.json','run/summary.json','run/complete.json',
         'overlay/overlay.ttl','overlay/overlay_report.json','overlay/complete.json'}
MANIFEST='BUNDLE_MANIFEST.json'


def dependencies(folder):
    receipt=v.read(folder/'calibration.json')
    path=(v.REPO_ROOT/receipt['params_file']).resolve()
    if not path.is_relative_to(v.REPO_ROOT.resolve()) or path.parent!=a.team_runtime.store().run_dir.resolve() or path.name!='params.json':
        raise a.InputError('invalid_calibration_reference','기존 기준 참조가 허용된 기본 엔진과 다릅니다.')
    expected=v.read(v.REPO_ROOT/'preprocessed/sensors/profile.json')['output_sha256'][a.rules.INPUT]
    if v.digest((v.REPO_ROOT/a.rules.INPUT).read_bytes())!=expected:
        raise a.InputError('dependency_mismatch','기존 센서 기준 파일의 해시가 다릅니다.')
    return {'kg_sha256':v.digest((v.REPO_ROOT/c.KG_REL).read_bytes()),'chunks_sha256':v.digest(v.SOURCE.read_bytes()),
            'calibration_params_sha256':v.digest(path.read_bytes()),'baseline_input_sha256':
            expected}


def validate_package(service, folder):
    store=a.AnalysisStore(folder)
    receipt=v.read(folder/'calibration.json')
    deps=dependencies(folder)
    if receipt['params_sha256']!=deps['calibration_params_sha256'] or receipt['input_sha256']!=deps['baseline_input_sha256']:
        raise a.InputError('dependency_mismatch','복원에 필요한 기존 기준이 현재 환경과 다릅니다.')
    summary=v.read(folder/'summary.json')
    if summary['analysis_id']!=folder.name or summary['kg_sha256']!=deps['kg_sha256']:
        raise a.InputError('dependency_mismatch','분석 ID 또는 고정 KG가 일치하지 않습니다.')
    if v.read(folder/'state.json').get('status')!='complete':
        raise a.InputError('analysis_not_ready','완료된 분석만 내보내거나 복원할 수 있습니다.')
    issues=overlay.loader_checks(store.overlay,store.base)
    if issues:raise a.InputError('invalid_overlay','복원 그래프의 참조·유형 검사를 통과하지 못했습니다.')
    # Recheck the uploaded CSV against its normalized prefix, without trusting
    # a zip's filenames or running its code or a model.
    metadata=a.schema(store.base)
    groups,_,_=a.parse_csv((folder/'upload.csv').read_bytes(),metadata)
    interval=v.read(folder/'input_manifest.json').get('intervals',{}).get('analysis',{})
    _,normalized,_,_=a.prepare_intervals(groups,metadata,interval.get('start'),interval.get('end'))
    if normalized!=(folder/'input.csv').read_bytes():
        raise a.InputError('normalized_input_mismatch','업로드 원본과 계산 입력이 일치하지 않습니다.')
    return store,deps


def export_bundle(service, analysis_id):
    folder=service.folder(analysis_id)
    service.store(analysis_id)
    store,deps=validate_package(service,folder)
    names=set(store.package_seal)|{'complete.json','state.json'}
    if names-ALLOWED:raise a.InputError('unexpected_bundle_file','분석 결과 외의 파일은 내보낼 수 없습니다.')
    files={name:(folder/name).read_bytes() for name in sorted(names)}
    if sum(map(len,files.values()))>MAX_EXPANDED_BYTES:raise a.InputError('bundle_size_limit','분석 묶음 크기 제한을 초과했습니다.')
    manifest={'version':VERSION,'analysis_id':analysis_id,'dependencies':deps,
              'files':{name:{'sha256':v.digest(raw),'bytes':len(raw)} for name,raw in files.items()},
              'private_local_package':True,'new_api_calls':0,
              'scope':'stored results and reference integrity, not proof of origin, truth or new evaluation'}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST,json.dumps(manifest,ensure_ascii=False,sort_keys=True))
        for name,raw in files.items():archive.writestr(name,raw)
    raw=out.getvalue()
    if len(raw)>MAX_ZIP_BYTES:raise a.InputError('bundle_size_limit','압축 묶음 크기 제한을 초과했습니다.')
    return raw


def read_bundle(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_ZIP_BYTES:
        raise a.InputError('bundle_size_limit','묶음은 32 MiB 이하여야 합니다.')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos=archive.infolist();names=[info.filename for info in infos]
            if len(names)>len(ALLOWED)+1 or len(set(names))!=len(names) or set(names)-ALLOWED-{MANIFEST} or MANIFEST not in names:
                raise a.InputError('invalid_bundle_entries','중복·경로 이탈·허용되지 않은 묶음 항목이 있습니다.')
            if sum(info.file_size for info in infos)>MAX_EXPANDED_BYTES or archive.getinfo(MANIFEST).file_size>256*1024:
                raise a.InputError('bundle_size_limit','압축 해제 크기 제한을 초과했습니다.')
            for info in infos:
                mode=stat.S_IFMT(info.external_attr>>16)
                if info.is_dir() or info.flag_bits&1 or mode not in (0,stat.S_IFREG) or info.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
                    raise a.InputError('invalid_bundle_entries','폴더·링크·암호화·지원하지 않는 압축은 허용하지 않습니다.')
            def unique_fields(pairs):
                if len({key for key,_ in pairs})!=len(pairs):raise ValueError('Duplicate manifest keys')
                return dict(pairs)
            manifest=json.loads(archive.read(MANIFEST),object_pairs_hook=unique_fields)
            if manifest['version']!=VERSION or not re.fullmatch(a.ID,manifest['analysis_id']):raise ValueError('Unknown bundle format')
            if set(manifest['files'])!=set(names)-{MANIFEST}:raise ValueError('Bundle membership changed')
            files={}
            for name,item in manifest['files'].items():
                if type(item['bytes']) is not int or item['bytes']!=archive.getinfo(name).file_size:raise ValueError('Size mismatch')
                content=archive.read(name)
                if v.digest(content)!=item['sha256']:raise ValueError('Checksum mismatch')
                files[name]=content
            return manifest,files
    except a.InputError:raise
    except (zipfile.BadZipFile,KeyError,ValueError,TypeError,RuntimeError,OSError):
        raise a.InputError('invalid_bundle','분석 묶음 형식·크기·해시를 확인할 수 없습니다.') from None


def import_bundle(service, raw):
    manifest,files=read_bundle(raw)
    aid=manifest['analysis_id'];target=service.folder(aid)
    if not {'complete.json','state.json','input.csv','upload.csv','input_manifest.json','calibration.json','summary.json'}<=set(files):
        raise a.InputError('invalid_bundle','필수 분석 파일이 없습니다.')
    service.root.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.restore-',dir=service.root)).resolve()
    try:
        folder=staging/aid;folder.mkdir()
        for name,content in files.items():
            path=(folder/name).resolve()
            if not path.is_relative_to(folder):raise a.InputError('invalid_bundle_entries','묶음 경로가 범위를 벗어납니다.')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        _,deps=validate_package(service,folder)
        if deps!=manifest['dependencies']:raise a.InputError('dependency_mismatch','원본 문서·KG·기준 버전이 다릅니다. 런타임 자료를 맞춰 주세요.')
        if target.exists():
            if any(not (target/name).is_file() or (target/name).read_bytes()!=content for name,content in files.items()):
                raise a.InputError('analysis_conflict','같은 분석 ID에 다른 내용이 있습니다. 덮어쓰지 않습니다.')
            validate_package(service,target)
            return {'analysis_id':aid,'status':'already_present','new_api_calls':0}
        # Both resolved paths were checked to stay inside this root. rename is
        # atomic on this filesystem; existing nonempty results are never replaced.
        if not folder.resolve().is_relative_to(service.root) or target.parent!=service.root:
            raise ValueError('Restore target escaped storage root')
        os.rename(folder,target)
        return {'analysis_id':aid,'status':'restored','new_api_calls':0,
                'scope':'exact stored artifacts; origin graph filenames retained, local input resolved by matching hash'}
    finally:
        if staging.exists():
            if staging.parent!=service.root or not staging.name.startswith('.restore-'):raise ValueError('Unsafe restore cleanup')
            shutil.rmtree(staging)
