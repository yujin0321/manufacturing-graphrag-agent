# 외부 공개 배포 안내 (생성 모드)

작성: 2026-11-18, `8th-yujin`. 대상은 공개 URL에서 CSV 분석, 저장 결과 조회, **새 질문(LLM 호출)**을 모두 제공하는 구성이다.

```
방문자 ──HTTPS──▶ Caddy (443, 인증서 자동 발급) ──▶ app: run_xai_agent.py (8770, 외부에 직접 노출 안 함)
                                                    └─ 저장소 폴더를 /app에 마운트 (코드 + 복원한 런타임)
```

## 1. 배포 전에 팀과 확인할 것

| 항목 | 내용 |
|---|---|
| 원문 노출 | 런타임 ZIP에는 문서 원문 청크가 들어 있다. 답변의 `sources`와 문서 질문 결과로 방문자에게 원문 일부가 보인다. 프로젝트 방침은 "팀 내부 관리"이므로 공개 범위를 팀과 합의한다. |
| 질문 기록 공개 | `/api/history`는 최근 실행 50개를 모두 보여 준다. 방문자들의 질문이 서로에게 보인다. |
| 비용 | 질문 한 번에 계획, 초안, 검토 단계에서 모델을 여러 번 호출한다. OpenAI 대시보드의 **프로젝트 월 예산(Usage limits)**을 반드시 설정한다. 서버의 한도 기능과 별도로 걸리는 최종 안전장치다. |

## 2. 서버 준비

- 리눅스 VM 1대 (Ubuntu 22.04 이상, 1 vCPU / 2 GB RAM이면 충분). 예: AWS Lightsail, EC2, GCP e2-small, Oracle Cloud Free Tier.
- 방화벽에서 **80, 443 포트**를 연다. 8770은 열지 않는다.
- 도메인의 DNS A 레코드를 서버 공인 IP로 지정한다. 무료 도메인으로는 DuckDNS 같은 서비스를 쓸 수 있다.
- Docker와 Docker Compose를 설치한다 (`curl -fsSL https://get.docker.com | sh`).

## 3. 코드와 런타임 올리기

```bash
git clone --branch main https://github.com/yujin0321/manufacturing-graphrag-agent.git
cd manufacturing-graphrag-agent
```

런타임 ZIP을 내 PC에서 서버로 복사한 뒤 복원한다. 공개 저장소나 채팅에는 올리지 않는다.

```powershell
# 내 PC (PowerShell)
scp imaks_agent_runtime_20261114.zip ubuntu@<서버IP>:~/manufacturing-graphrag-agent/
```

```bash
# 서버
docker run --rm -v "$PWD":/app -w /app python:3.11-slim sh -c \
  "pip install -q -r docs/agent_handoff/requirements.txt && python scripts/agent_handoff.py restore imaks_agent_runtime_20261114.zip && python scripts/agent_handoff.py audit"
rm imaks_agent_runtime_20261114.zip
sudo chown -R 1000:1000 .   # 컨테이너 사용자(uid 1000)가 분석 결과와 실행 기록을 쓸 수 있게 함
```

## 4. 설정 (.env)

```bash
cp deploy/env.example .env
nano .env
```

| 변수 | 권장값 | 의미 |
|---|---|---|
| `OPENAI_API_KEY` | (필수) | 서버에만 둔다. Git, ZIP, 채팅에 넣지 않는다. |
| `IMAKS_PUBLIC_HOSTS` | `imaks.example.com` | 공개 도메인. `https://` 없이 호스트 이름만 쓴다. Caddy 인증서 발급과 서버의 Host/Origin 검사에 함께 쓰인다. |
| `IMAKS_GENERATION_DAILY_LIMIT` | `30` | 전체 방문자 합산 하루 질문 수 (UTC 기준) |
| `IMAKS_GENERATION_HOURLY_PER_IP` | `5` | 방문자 IP별 시간당 질문 수 |
| `IMAKS_UPLOAD_HOURLY_PER_IP` | `10` | IP별 시간당 CSV/ZIP 업로드 수 |
| `IMAKS_ACCESS_CODE` | (선택) | 설정하면 질문할 때 접근 코드를 한 번 입력해야 한다. 링크를 넓게 공유할 때 사용한다. |

한도 카운터는 메모리에 있어서 **서버를 재시작하면 초기화된다**. 그래서 OpenAI 프로젝트 예산을 함께 건다.

## 5. 실행과 확인

```bash
docker compose up -d --build
docker compose logs -f app      # "XAI demo ... (listening on 0.0.0.0)" 확인
```

1. `https://<도메인>/api/session`에서 `generation_enabled: true`와 `generation_remaining_today`가 나오는지 확인한다.
2. 화면에서 CSV 업로드 → 사건 상세 → 문서/KG 질문 1개를 순서대로 확인한다.
3. 같은 IP로 한도를 넘기면 HTTP 429와 안내 문구가 나오는지 확인한다.

## 6. 운영

| 작업 | 명령 |
|---|---|
| 코드 업데이트 | `git pull && docker compose restart app` |
| 의존성 변경 후 | `docker compose up -d --build` |
| 중지 | `docker compose down` |
| 생성 끄기 (비용 문제 시 즉시) | Dockerfile `CMD`에 `"--read-only"`를 추가하고 `docker compose up -d --build`. 저장 결과 조회와 CSV 분석은 계속 동작한다. |

## 로컬 기본 동작은 그대로

`IMAKS_*` 변수가 없으면 서버는 이전처럼 `127.0.0.1`에만 바인딩하고 Host/Origin도 `127.0.0.1`만 허용한다. 한도와 접근 코드도 꺼진다. 로컬 개발 명령은 바뀌지 않는다. 새 UI로 띄울 때만 `--page sensor-ui/integration/serve-page.html`을 추가한다.

```powershell
.\.venv\Scripts\python.exe scripts/run_xai_agent.py --serve --allow-local-analysis --port 8770 --page sensor-ui/integration/serve-page.html
```

## 검증

`tests/test_deploy_server.py`가 다음을 검사한다. 기본값의 로컬 전용 유지, 공개 Host 허용과 미등록 Host 거부, 공개 도메인의 `http://` Origin 거부, 접근 코드가 틀리면 모델 호출 전에 차단, IP별·일일 한도, `X-Forwarded-For` 앞부분 위조로 한도를 우회하지 못함. 기존 `tests/test_team_app_server.py` 13개도 그대로 통과한다.
