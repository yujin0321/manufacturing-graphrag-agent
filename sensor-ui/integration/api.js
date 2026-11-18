(() => {
  async function request(path, options) {
    if (location.protocol === 'file:') throw Error('예원 분석 서버에서 연결용 화면을 열어 주세요.');
    const response = await fetch(path, options);
    const data = await response.json().catch(() => null);
    if (!response.ok || !data) throw Error(data?.error?.message || data?.error || '서버 요청 실패 (' + response.status + ')');
    return data;
  }
  const root = id => '/api/analyses/' + encodeURIComponent(id);
  const number = value => value == null || value === '' ? null : Number(value);
  const format = date => new Date(date).toISOString().slice(0, 19);
  const nominalTime = time => Date.parse(time + 'Z');
  const normalize=(data,id)=>{
    if(data.status!=='complete')throw Error('완료된 분석만 열 수 있습니다.');
      return {
        run_id:id,created:data.job?.created_at_utc,start:data.intervals.analysis.start,end:data.intervals.analysis.end,alarm_count:data.alarms,
        sensor_count:data.sensors?.length,gap_count:data.quality?.gaps?.length,intervals:data.intervals,warnings:data.warnings,coverage:data.coverage,correlations:data.correlation_candidates,
        events:data.incident_items.map(item => ({
          event_id:item.id,id:item.sensor_id,time:item.start,start:item.start,end:item.end,
          kind:item.anomaly_type,severity:item.severity,rule_id:item.rule_ids?.join(', '),value:null,unit:''
        }))
      };
  };
  const session=()=>request('/api/session');
  window.SensorAPI = {
    session,
    async analyses(){return (await request('/api/analyses')).items;},
    async open(id){return normalize(await request(root(id)),id);},
    exportUrl:id=>root(id)+'/export',
    async restore(file){
      const config=await session();
      const result=await request('/api/analyses/import',{method:'POST',
        headers:{'Content-Type':'application/zip','X-Demo-Token':config.csrf_token},body:file});
      return this.open(result.analysis_id);
    },
    history:()=>request('/api/history'),
    saved:id=>request('/api/run/'+encodeURIComponent(id)),
    async question(question){
      const settings=await session();
      if(!settings.generation_enabled)throw Error('읽기 전용입니다. 저장된 답변을 조회할 수 있습니다.');
      const headers={'Content-Type':'application/json','X-Demo-Token':settings.csrf_token};
      if(settings.access_code_required){
        let code=null;
        try{code=sessionStorage.getItem('imaksAccessCode');}catch(error){}
        if(!code)code=(window.prompt('질문 기능 접근 코드를 입력해 주세요.')||'').trim();
        if(!code)throw Error('접근 코드가 필요합니다.');
        headers['X-Access-Code']=code;
        try{sessionStorage.setItem('imaksAccessCode',code);}catch(error){}
      }
      try{
        return await request('/api/agent',{method:'POST',headers,body:JSON.stringify({question})});
      }catch(error){
        if(/접근 코드/.test(error.message)){try{sessionStorage.removeItem('imaksAccessCode');}catch(e){}}
        throw error;
      }
    },
    async detect(file, onStatus = () => {}, range = {}) {
      if (file.size > 4 * 1024 * 1024) throw Error('CSV는 최대 4 MiB입니다. 분석할 시간 구간을 줄여 주세요.');
      const session = await request('/api/session');
      if (!session.analysis_enabled || !session.csrf_token) throw Error('서버에 로컬 분석 기능을 켜 주세요.');
      let data = await request('/api/analyses', {
        method: 'POST',
        headers: {'Content-Type':'text/csv; charset=utf-8','X-Demo-Token':session.csrf_token,'X-Input-Kind':'uploaded_sensor_csv',...(range.start?{'X-Analysis-Start':range.start,'X-Analysis-End':range.end}:{})},
        body: file
      });
      const id = data.analysis_id;
      if (!id) throw Error('서버가 분석 ID를 반환하지 않았습니다.');
      for (let i = 0; ['queued','processing'].includes(data.status) && i < 300; i++) {
        onStatus(data.phase??data.status);
        await new Promise(resolve => setTimeout(resolve, 1000));
        data = await request(root(id));
      }
      if (data.status !== 'complete') throw Error(data.error?.message || data.error || '분석이 완료되지 않았습니다 (' + data.status + ', ' + id + ').');
      return normalize(data,id);
    },
    async series(id,event,interval) {
      const params = new URLSearchParams({
        sensor_id:event.id,
        start:format(Math.max(nominalTime(interval.start),nominalTime(event.start)-600000)),
        end:format(Math.min(nominalTime(interval.end),nominalTime(event.end)+600000)),
        limit:'2000'
      });
      const points=[];
      let data;
      do {
        data=await request(root(id)+'/series?'+params);
        points.push(...data.points.map(point=>({time:point.timestamp,value:Number(point.value)})));
        if(data.next_offset!=null)params.set('offset',String(data.next_offset));
      } while(data.next_offset!=null);
      const alarm=data.alarms.filter(a=>!event.rule_id||event.rule_id.split(', ').includes(a.rule_id))
        .filter(a=>a.trigger_at>=event.start&&a.trigger_at<=event.end)
        .sort((a,b)=>a.trigger_at.localeCompare(b.trigger_at))[0];
      return {points,unit:data.unit,low:number(data.thresholds.warnLo),high:number(data.thresholds.warnHi),
        trigger:alarm?.trigger_at, gaps:data.gaps, thresholds:data.thresholds};
    },
    async explain(id,eventId) {
      const data=await request(root(id)+'/incidents/'+encodeURIComponent(eventId));
      return {
        status:data.agent_status,answer:data.answer, warnings:data.warnings,
        sources:data.sources.map(s=>({id:s.chunk_id,text:s.text,location:s.page!=null?'p. '+s.page:null})),
        verification:data.xai?.decision_evidence?.status,
        binding:data.xai?.claim_binding?.status,
        rules:data.xai?.matched_rules, checks:data.xai?.rule_explanations,
        claims:data.claims, incident:data.xai?.incident, decisions:data.xai?.decision_evidence?.items,
        paths:data.edges
      };
    }
  };
})();
