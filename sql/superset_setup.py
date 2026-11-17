# -*- coding: utf-8 -*-
"""
第4周：Superset 数据源注册脚本（REST API 方式，可重复执行）
注册 Hive（ydsh-hiveserver2）与 MySQL（ydsh-mysql/ydsh_ads）两个数据源
用法：python sql/superset_setup.py（需 Superset 已初始化 admin 账号）
"""
import requests

SUPERSET = "http://localhost:8088"
s = requests.Session()

def login():
    r = s.post(f"{SUPERSET}/api/v1/security/login",
               json={"username": "admin", "password": "admin",
                     "provider": "db", "refresh": True}, timeout=30)
    r.raise_for_status()
    s.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    # POST 需要额外携带 CSRF 令牌（与 Session cookie 配套）
    r = s.get(f"{SUPERSET}/api/v1/security/csrf_token/", timeout=30)
    r.raise_for_status()
    s.headers["X-CSRF-Token"] = r.json()["result"]

def ensure_database(name, uri):
    """存在则更新 URI，不存在则创建，返回 id"""
    q = {"q": f'(filters:!((col:database_name,opr:eq,value:{name})))'}
    r = s.get(f"{SUPERSET}/api/v1/database/", timeout=30, params=q)
    items = r.json().get("result", [])
    if items:
        did = items[0]["id"]
        s.put(f"{SUPERSET}/api/v1/database/{did}", timeout=30,
              json={"database_name": name, "sqlalchemy_uri": uri})
        print(f"已更新数据源 {name} (id={did})")
    else:
        r = s.post(f"{SUPERSET}/api/v1/database/", timeout=30,
                   json={"database_name": name, "sqlalchemy_uri": uri})
        r.raise_for_status()
        did = r.json()["id"]
        print(f"已创建数据源 {name} (id={did})")
    return did

login()
hive_id = ensure_database("ydsh_hive", "hive://hive@ydsh-hiveserver2:10000/default")
mysql_id = ensure_database("ydsh_mysql", "mysql+pymysql://root:root@ydsh-mysql:3306/ydsh_ads")

for did, name in [(hive_id, "ydsh_hive"), (mysql_id, "ydsh_mysql")]:
    r = s.get(f"{SUPERSET}/api/v1/database/{did}/connection", timeout=60)
    print(name, "连接测试:", r.json().get("message", r.text)[:150])
