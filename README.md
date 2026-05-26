# Command Watcher AI

Command Watcher AI는 서버 명령어 실행 이력을 MySQL과 Chroma Vector DB에 저장하고, 자연어 질문으로 로그 조회, 이상 행동 탐지, 워크플로우 추천, 컴플라이언스 점검, 인시던트 분석을 수행하는 FastAPI 기반 분석 도구입니다.

## 주요 기능

- 자연어 로그 조회: 사용자, 명령어, 기간, IP 기준 조회와 집계
- Chroma 의미 검색: 비슷한 운영 패턴이나 관련 로그 검색
- 이상 행동 분석: IsolationForest와 위험 명령어 패턴 기반 사용자/세션 탐지
- 인시던트 분석: 의심 세션 타임라인, 공격 경로 단서, 근본 원인 후보 정리
- 컴플라이언스 점검: 위험 명령어, 실패 로그, 사용자별 위반 통계 요약
- 추천 Agent: 사용자별 명령어 사용 패턴을 기반으로 개선 워크플로우 제안

## 구성

```text
.
├── src/
│   ├── api/                  # FastAPI 엔드포인트
│   ├── agents/               # Router, Query, Anomaly, Incident 등 Agent
│   ├── graph/                # LangGraph 워크플로우
│   ├── tools/                # MySQL, Chroma, 이상 탐지 도구
│   ├── config.py             # 환경변수 로딩 및 설정
│   └── llm.py                # Ollama LLM 생성 헬퍼
├── templates/index.html      # 웹 UI
├── data/                     # CSV 입력 데이터, git ignore 대상
├── chroma_db/                # Chroma 영속 저장소, git ignore 대상
├── build_vector_db.py        # MySQL 로그를 Chroma DB로 빌드
├── import_csv.py             # CSV를 MySQL command_history에 적재
├── csv_maker.py              # 샘플 로그 CSV 생성
└── tests/                    # 빠른 단위 테스트
```

## 요구사항

- Python 3.10 이상 권장
- MySQL 또는 MariaDB
- Ollama
- Ollama 모델: 기본값 `qwen2.5:3b`

현재 저장소에는 `requirements.txt`가 없으므로, 새 환경에서는 아래 패키지가 필요합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn pandas sqlalchemy pymysql scikit-learn chromadb langchain langchain-core langchain-community langchain-ollama langchain-chroma langchain-huggingface sentence-transformers
```

## 빠른 시작

### 1. 가상환경 준비

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

필요 패키지를 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn pandas sqlalchemy pymysql scikit-learn chromadb langchain langchain-core langchain-community langchain-ollama langchain-chroma langchain-huggingface sentence-transformers
```

### 2. Ollama 모델 준비

```powershell
ollama pull qwen2.5:3b
ollama serve
```

기본 API 서버 코드는 로컬 Ollama(`http://127.0.0.1:11434`)를 사용합니다.

### 3. 환경변수 설정

`.env.example`을 복사해 `.env`를 만들고 DB 접속 정보를 수정합니다.

```powershell
Copy-Item .env.example .env
```

주요 설정:

```env
LLM_MODEL=qwen2.5:3b
DB_HOST=localhost
DB_PORT=3306
DB_USER=cmd_admin
DB_PASSWORD=change-me
DB_NAME=cmd_watcher
CHROMA_PERSIST_DIR=./chroma_db
CHROMA_COLLECTION_NAME=command_logs
EMBEDDING_MODEL=BAAI/bge-m3
API_PORT=8000
```

### 4. MySQL 테이블 생성

`build_vector_db.py`는 `id`와 `created_at` 컬럼도 조회하므로, CSV를 넣기 전에 테이블을 명시적으로 만들어 두는 것이 안전합니다.

```sql
CREATE DATABASE IF NOT EXISTS cmd_watcher;

CREATE TABLE IF NOT EXISTS cmd_watcher.command_history (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_name VARCHAR(128) NOT NULL,
  command TEXT NOT NULL,
  timestamp DATETIME NOT NULL,
  current_dir VARCHAR(512),
  client_ip VARCHAR(64),
  server_ip VARCHAR(64),
  exit_code INT NOT NULL DEFAULT 0,
  session_id VARCHAR(128),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_timestamp (timestamp),
  INDEX idx_user_name (user_name),
  INDEX idx_session_id (session_id),
  INDEX idx_client_ip (client_ip)
);
```

### 5. 샘플 데이터 적재

기본 입력 파일은 `data/command_history_with_hacker.csv`입니다.

이미 파일이 있다면 바로 적재합니다.

```powershell
.\.venv\Scripts\python.exe import_csv.py
```

새 샘플을 만들려면:

```powershell
.\.venv\Scripts\python.exe csv_maker.py
New-Item -ItemType Directory -Force data
Move-Item command_history_with_hacker.csv data\command_history_with_hacker.csv
.\.venv\Scripts\python.exe import_csv.py
```

### 6. Chroma Vector DB 빌드

```powershell
.\.venv\Scripts\python.exe build_vector_db.py
```

빌드 확인:

```powershell
.\.venv\Scripts\python.exe check_chroma_db.py
```

### 7. 서버 실행

```powershell
.\.venv\Scripts\python.exe main.py
```

브라우저에서 접속:

```text
http://localhost:8000
```

API 직접 호출:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/query `
  -ContentType "application/json" `
  -Body '{"query":"최근 7일 인시던트 근본 원인 분석"}'
```

## 질문 예시

```text
chroma_db에는 몇 명의 사용자가 있어?
전체 사용자 수 알려줘
지난 7일간 sudo를 가장 많이 사용한 사람은 누구야?
실패한 명령어가 가장 많은 사용자는 누구야?
docker와 비슷한 운영 패턴 로그를 찾아줘
최근 7일 이상 행동 분석해줘
hacker 세션 hacked-1c9cf9 인시던트 분석
user01에게 추천할 효율적인 명령어 워크플로우를 알려줘
최근 sudo 사용 로그가 규정 위반인지 감사 관점에서 확인해줘
```

## Agent 동작 방식

요청은 먼저 RouterAgent가 의도를 분류한 뒤 전문 Agent로 전달됩니다.

- `query`: 정확한 통계와 필터링은 MySQL, 의미 기반 검색은 Chroma 사용
- `anomaly`: IsolationForest와 위험 명령어 SQL 집계를 함께 사용
- `incident`: 의심 이벤트 중심 타임라인과 근본 원인 후보 생성
- `recommendation`: 사용자별 최근 명령어, 실패 패턴, 안정적인 전역 명령어 분석
- `compliance`: 위험 명령어와 실패 로그를 감사 관점으로 요약

사용자 수처럼 정확한 집계가 필요한 질문은 Chroma similarity search가 아니라 MySQL 또는 Chroma metadata 집계 경로를 사용합니다.

## 테스트

빠른 단위 테스트:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Router live eval:

```powershell
.\.venv\Scripts\python.exe harness\run_router_eval.py
```

Query planner eval:

```powershell
.\.venv\Scripts\python.exe harness\run_query_eval.py
```

DB 연결 확인:

```powershell
.\.venv\Scripts\python.exe harness\db_smoke.py
```

## 운영 메모

- `.env`, `data/`, `chroma_db/`는 git ignore 대상입니다.
- `build_vector_db.py`는 MySQL의 최신 로그를 읽어 Chroma를 다시 구성합니다.
- `MAX_ROWS_FOR_ANALYSIS`로 Chroma에 넣을 최대 행 수를 조절할 수 있습니다.
- 임베딩 모델은 기본 `BAAI/bge-m3`입니다. 최초 실행 시 모델 다운로드가 필요할 수 있습니다.
- Chroma 검색은 유사 로그 검색용입니다. 전체 건수, 사용자 수, 사용자 목록 같은 정확한 집계는 metadata 집계나 MySQL을 사용해야 합니다.

## 문제 해결

### MySQL 연결 실패

- `.env`의 `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` 확인
- 데이터베이스와 `command_history` 테이블이 생성되어 있는지 확인
- `harness\db_smoke.py`로 연결 상태 확인

### Chroma DB가 비어 있음

- `import_csv.py`로 MySQL에 데이터가 들어갔는지 먼저 확인
- `build_vector_db.py`를 다시 실행
- `.env`의 `CHROMA_PERSIST_DIR`, `CHROMA_COLLECTION_NAME` 확인

### Ollama 응답 실패

- `ollama serve`가 실행 중인지 확인
- `ollama list`로 `qwen2.5:3b` 모델 존재 여부 확인
- 다른 모델을 쓰려면 `.env`의 `LLM_MODEL` 수정

## 보안 주의

이 프로젝트는 샘플 로그 분석용 도구입니다. 실제 운영 환경에 연결할 경우 DB 계정 권한을 읽기 전용 또는 최소 권한으로 제한하고, `.env`와 로그 파일에 민감 정보가 포함되지 않도록 관리하세요.
