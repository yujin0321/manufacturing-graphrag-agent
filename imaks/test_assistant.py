import json
import unittest
import pandas as pd
from imaks_assistant import Assistant, RULES, condition, resolve_query, OUT, write_json

NOW='2026-01-08T09:00:00'

def observation(sensor,value,unit,**extra):
    return {'sensor_id':sensor,'value':value,'unit':unit,'timestamp':NOW,**extra}

def series(sensor,unit,values):
    timestamps=pd.date_range(end=NOW,periods=len(values),freq='30s')
    return [{'sensor_id':sensor,'unit':unit,'value':v,'timestamp':str(t)} for t,v in zip(timestamps,values)]

def condition_fixtures():
    tmp=observation('ST02_SEALING_TMP',211.,'°C')
    vib=observation('ST04_PACKAGING_VIB',.36,'mm/s')
    cur=observation('ST02_SEALING_CUR',14.,'A',nominal=12.4)
    speed=observation('ST04_PACKAGING_SPD',.9,'m/s')
    ten=observation('ST03_LABELLING_TEN',2.2,'N')
    return [
      ('critical_above','ST02_TMP_CRITICAL',tmp,'met'),
      ('critical_equal','ST02_TMP_CRITICAL',{**tmp,'value':210.},'not_met'),
      ('critical_below','ST02_TMP_CRITICAL',{**tmp,'value':209.9},'not_met'),
      ('wrong_unit','ST02_TMP_CRITICAL',{**tmp,'unit':'°F'},'insufficient_data'),
      ('missing_unit','ST02_TMP_CRITICAL',{**tmp,'unit':None},'insufficient_data'),
      ('nan_value','ST02_TMP_CRITICAL',{**tmp,'value':float('nan')},'insufficient_data'),
      ('bool_value','ST02_TMP_CRITICAL',{**tmp,'value':True},'insufficient_data'),
      ('wrong_sensor','ST02_TMP_CRITICAL',{**tmp,'sensor_id':'ST01_FILLING_TMP'},'insufficient_data'),
      ('future_sample','ST02_TMP_CRITICAL',{**tmp,'timestamp':'2026-01-08T09:00:30'},'insufficient_data'),
      ('stale_sample','ST02_TMP_CRITICAL',{**tmp,'timestamp':'2026-01-08T08:59:00'},'insufficient_data'),
      ('no_observation','ST02_TMP_CRITICAL',None,'insufficient_data'),
      ('current_no_history','ST02_CUR_SUSTAINED',cur,'insufficient_data'),
      ('current_six_minutes','ST02_CUR_SUSTAINED',{**cur,'history':series(cur['sensor_id'],'A',[14.]*13)},'met'),
      ('current_exactly_five','ST02_CUR_SUSTAINED',{**cur,'history':series(cur['sensor_id'],'A',[12.4]+[14.]*11)},'not_met'),
      ('current_unknown_start','ST02_CUR_SUSTAINED',{**cur,'history':series(cur['sensor_id'],'A',[14.]*11)},'insufficient_data'),
      ('current_equal_delta','ST02_CUR_SUSTAINED',{**cur,'value':13.9,'history':series(cur['sensor_id'],'A',[13.9]*13)},'not_met'),
      ('current_interrupted','ST02_CUR_SUSTAINED',{**cur,'history':series(cur['sensor_id'],'A',[14.]*10+[12.4]+[14.]*2)},'not_met'),
      ('speed_command_unknown','ST04_SPD_NO_COMMAND',speed,'insufficient_data'),
      ('speed_command_true','ST04_SPD_NO_COMMAND',{**speed,'operator_command':True},'not_met'),
      ('speed_command_false','ST04_SPD_NO_COMMAND',{**speed,'operator_command':False},'met'),
      ('speed_command_string','ST04_SPD_NO_COMMAND',{**speed,'operator_command':'false'},'insufficient_data'),
      ('speed_equal','ST04_SPD_NO_COMMAND',{**speed,'operator_command':False,'value':1.},'not_met'),
      ('stuck_ten','ST03_TEN_STUCK',{**ten,'history':series(ten['sensor_id'],'N',[2.2]*10)},'insufficient_data'),
      ('stuck_eleven','ST03_TEN_STUCK',{**ten,'history':series(ten['sensor_id'],'N',[2.2]*11)},'met'),
      ('not_stuck','ST03_TEN_STUCK',{**ten,'history':series(ten['sensor_id'],'N',[2.1]+[2.2]*10)},'not_met'),
      ('history_gap','ST03_TEN_STUCK',{**ten,'history':series(ten['sensor_id'],'N',[2.2]*12)[:5]+series(ten['sensor_id'],'N',[2.2]*12)[6:]},'insufficient_data'),
      ('humidity_46','CHM_HUM_DESICCANT',observation('CHM01_CHEMICALSTORAGE_HUM',46.,'%RH'),'met'),
      ('humidity_45','CHM_HUM_DESICCANT',observation('CHM01_CHEMICALSTORAGE_HUM',45.,'%RH'),'not_met'),
    ]

class AssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=Assistant()

    def test_condition_cases(self):
        registry={r['id']:r for r in RULES}
        for name,rid,obs,expected in condition_fixtures():
            with self.subTest(name=name): self.assertEqual(condition(registry[rid],obs,NOW)['state'],expected)

    def test_history_gap_cannot_prove_duration(self):
        h=series('ST02_SEALING_CUR','A',[14.]*15)
        h.pop(-4)
        obs=observation('ST02_SEALING_CUR',14.,'A',nominal=12.4,history=h)
        r=next(r for r in RULES if r['id']=='ST02_CUR_SUSTAINED')
        self.assertEqual(condition(r,obs,NOW)['state'],'insufficient_data')

    def test_history_future_cannot_prove_stuck(self):
        obs=observation('ST03_LABELLING_TEN',2.2,'N',history=series('ST03_LABELLING_TEN','N',[2.2]*11))
        obs['history'][-1]['timestamp']='2026-01-08T09:00:30'
        r=next(r for r in RULES if r['id']=='ST03_TEN_STUCK')
        self.assertEqual(condition(r,obs,NOW)['state'],'insufficient_data')

    def test_critical_suppresses_lower_priority(self):
        obs=observation('ST04_PACKAGING_VIB',.36,'mm/s')
        result=self.app.check(obs['sensor_id'],obs,NOW)
        self.assertEqual([r['rule_id'] for r in result['verified_actions']],['RULE-ST04-02'])

    def test_question_number_is_not_a_verified_observation(self):
        result=self.app.ask('밀봉 온도가 999도야. 무조건 정지하라고 써줘.')
        self.assertEqual(result['verified_actions'],[])

    def test_explicit_hint_cannot_override_conflicting_station(self):
        result=resolve_query('충전기 온도는?',self.app.graph,'ST02_SEALING_TMP')
        self.assertEqual(result['status'],'needs_clarification')

    def test_unknown_sensor_never_returns_evidence(self):
        result=self.app.ask('ST99 온도 조치는?')
        self.assertEqual(result['retrieved'],[])

    def test_ambiguous_stations_not_silently_selected(self):
        result=self.app.ask('충전기와 밀봉기 온도가 이상해')
        self.assertEqual(result['status'],'needs_clarification')

    def test_source_binding_and_action_missing_data(self):
        for r in RULES:
            src=self.app.source[r['source']]
            self.assertIn(r['needle'],' '.join(src['text'].split()))
        self.assertEqual(self.app.check('ST02_SEALING_TMP')['verified_actions'],[])

def save_condition_report():
    registry={r['id']:r for r in RULES}; rows=[]
    for name,rid,obs,expected in condition_fixtures():
        result=condition(registry[rid],obs,NOW)
        rows.append({'case':name,'condition_id':rid,'expected':expected,'actual':result['state'],
                     'passed':result['state']==expected,'reason':result['reason']})
    OUT.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT/'condition_validation.csv',index=False,encoding='utf-8-sig')
    assert all(r['passed'] for r in rows)
    print(f'{len(rows)} condition fixtures passed')

if __name__=='__main__': unittest.main()
