(() => {
  async function request(path, options) {
    if (location.protocol === 'file:') {
      throw new Error('연결용 화면은 백엔드 서버에서 열어 주세요.');
    }
    const response = await fetch('/api' + path, options);
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.message || '요청 실패 (' + response.status + ')');
    }
    return response.json();
  }
  const eventPath = (runId, eventId) =>
    '/runs/' + encodeURIComponent(runId) + '/events/' + encodeURIComponent(eventId);
  window.SensorAPI = {
    detect(file) {
      const body = new FormData();
      body.append('file', file);
      return request('/detect', { method: 'POST', body });
    },
    series(runId, eventId) {
      return request(eventPath(runId, eventId) + '/series');
    },
    explain(runId, eventId) {
      return request(eventPath(runId, eventId) + '/explain', { method: 'POST' });
    }
  };
})();
