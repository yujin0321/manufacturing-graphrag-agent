"""Source-preserving comparison of documented operating constraints, not GT tuning."""
from decimal import Decimal
from .common import DOCS, OUT, REPO_ROOT, read_csv, read_jsonl, write_json


def review():
    pages = {(r['doc_id'], r['page']): r for r in read_jsonl(DOCS/'pages.jsonl')}
    thresholds = read_csv(REPO_ROOT/'preprocessed/sensors/rules/sensor_thresholds.csv')
    tables = read_jsonl(DOCS/'tables.jsonl')
    def quote(doc, text):
        page = pages[(doc, 1)]
        start = page['text_normalized'].index(text)
        return {'document': doc, 'page': 1, 'quote': text, 'charStart': start, 'charEnd': start+len(text)}
    items = []
    thermal = quote('DS-THERM-2200', 'The rated maximum for continuous operation is 200°C.')
    current = quote('DS-ELEC-3300', 'The sensor is rated for continuous operation up to 14 A.')
    pressure = quote('DS-MECH-4400', 'alarm thresholds should be set at\nleast 5× the accuracy (0.50 bar) from the nominal operating point to avoid nuisance alarms.')
    for r in thresholds:
        kind = r['sensor_id'].rsplit('_', 1)[-1]
        checks = []
        if kind == 'TMP' and Decimal(r['critHi']) > Decimal('200'):
            checks.append(('critHi', 'continuous temperature rating', Decimal('200'), thermal, 'different quantities: alarm threshold vs continuous rating'))
        if kind == 'CUR' and Decimal(r['critHi']) > Decimal('14'):
            checks.append(('critHi', 'continuous current rating', Decimal('14'), current, 'duration-dependent rating and corrective-action recommendation'))
        if kind == 'PRS':
            for field in ('warnLo', 'warnHi'):
                delta = abs(Decimal(r[field])-Decimal(r['nominalValue']))
                if delta < Decimal('0.50'):
                    checks.append((field, 'recommended distance from nominal', Decimal('0.50'), pressure, 'recommendation deviation, not a proven hard-limit contradiction'))
        for field, spec, bound, evidence, interpretation in checks:
            row_matches = [(t, i, row) for t in tables if t['doc_id']=='SOP-002'
                           for i, row in enumerate(t['rows_normalized'])
                           if len(row)>=7 and row[0]==kind and row[2]==r['critLo'] and row[6]==r['critHi']]
            if not row_matches:
                raise ValueError('SOP source row not found: '+r['sensor_id'])
            t, index, row = row_matches[0]
            items.append({'sensor':r['sensor_id'], 'sop_field':field, 'sop_value':r[field],
                          'nominal':r['nominalValue'], 'unit':r['unit'], 'datasheet_constraint':spec,
                          'datasheet_value':str(bound), 'interpretation':interpretation,
                          'applicability':'sensor-series applicability inferred from type; verify before real-world use',
                          'sop_source':{'document':'SOP-002','tableId':t['table_id'],'rowIndex':index+1,'row':row},
                          'datasheet_source':evidence, 'resolution':'preserve both with source and condition; no overwrite'})
    write_json(OUT/'source_constraint_review.json',items)
    lines=['# SOP·데이터시트 조건별 수치 검토', '',
           '문서 원문과 전처리 임계값을 대조했다. ground_truth.csv는 읽지 않았다.',
           '같은 값의 오류로 단정하지 않고, 연속 운전 정격·공정 경보·권장 설정의 의미와 지속 조건을 구분한다.',
           '센서 형식에 따른 데이터시트 적용을 가정한 검토 후보이다. 실제 제조사·모델 대응을 입증한 것은 아니다.', '',
           '| 센서 | SOP 값 | 데이터시트 조건 | 검토 의미 |', '|---|---|---|---|']
    for r in items:
        lines.append(f"| {r['sensor']} | {r['sop_field']}={r['sop_value']} {r['unit']} | {r['datasheet_constraint']}={r['datasheet_value']} | {r['interpretation']} |")
    lines+=['', '220°C 미만·10분 미만의 간헐 조건은 200°C 연속 운전 정격을 대체하지 않는다.',
            '14~20 A의 짧은 운전 조건도 14 A 연속 정격과 별개로 보존한다.',
            '원문 차이는 자동으로 통일하지 않았다. 상세 위치·인용은 source_constraint_review.json에 있다.', '']
    (REPO_ROOT/'reports/stage3_source_review_impl.md').write_text('\n'.join(lines),encoding='utf8')
    print('Source constraint review candidates:',len(items))


if __name__=='__main__':
    review()
