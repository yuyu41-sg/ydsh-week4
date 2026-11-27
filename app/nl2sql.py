# -*- coding: utf-8 -*-
"""
子任务4：NL2SQL 构建（自然语言 → 生成 SQL → 执行 → 返回结果）
链路：
  1) data/schema.json 注入系统提示词（含表注释、列清单、few-shot 示例）
  2) 智谱 GLM 生成只读 SELECT SQL（代码块提取，非法语句拦截）
  3) 经 beeline 在 Hive 实际执行，返回结果
前置：.env 已配置 ZHIPU_API_KEY；data/schema.json 已由 schema_extract.py 生成
用法：python nl2sql.py "广东省上月销售额是多少？"
"""
import json
import os
import re
import subprocess
import sys

from dotenv import load_dotenv
from openai import OpenAI

BASE = os.path.dirname(os.path.abspath(__file__))  # 本文件所在目录（本地=week4/app，容器=/app）
load_dotenv(os.path.join(BASE, ".env"))            # 容器内：/app/.env
load_dotenv(os.path.join(os.path.dirname(BASE), ".env"))  # 本地：week4/.env

api_key = os.environ.get("ZHIPU_API_KEY")
if not api_key or "xxxx" in api_key:
    raise SystemExit("未配置 API Key：请复制 .env.example 为 .env 并填入真实 ZHIPU_API_KEY")

# ---------- 1. 载入 Schema ----------
with open(os.path.join(BASE, "data", "schema.json"), encoding="utf-8") as f:
    schema = json.load(f)
schema_lines = []
for t, info in schema.items():
    schema_lines.append(f"{t} -- {info['comment']}")
    schema_lines.append("  " + ", ".join(info["columns"]))
    if info["partitions"]:
        schema_lines.append(f"  分区字段: {', '.join(info['partitions'])}")
schema_desc = "\n".join(schema_lines)

# ---------- 2. 系统提示词（含 few-shot 与规范约束） ----------
SYSTEM_PROMPT = f"""你是 Hive SQL 专家。根据用户的自然语言问题，生成一条可在 Hive 4.0 上执行的查询 SQL。

可用表（ Schema 如下）：
{schema_desc}

硬性规范：
1. 只生成 SELECT 语句，禁止 INSERT / UPDATE / DELETE / DROP / CREATE。
2. 只允许使用上面列出的表和列，禁止编造表名或列名。
3. 表名必须带库名前缀（如 ydsh_dwd.dwd_order）。
4. 时间字段 order_timestamp/dt 为 string 类型，格式 yyyy-MM-dd 或 yyyy-MM-dd HH:mm:ss，日期比较用 SUBSTR() 或字符串比较。
5. "销售额/GMV"默认口径为已完成订单的 pay_amount 之和（order_status = '已完成'）；涉及品类销量时用 dwd_order_item 关联 dim_product。
6. 省份/城市等维度在 dim_store / dim_user 表中，注意关联键。
7. 结果限制在 50 行以内（必要时加 LIMIT）。
8. GROUP BY / ORDER BY / HAVING 中必须重复完整表达式或原始列名，严格禁止使用 SELECT 别名（Hive 不支持别名分组与别名排序）。
9. dwd_order 已有分区列 order_month（格式 'yyyy-MM'），月度/季度趋势直接 GROUP BY order_month，禁止用 SUBSTR 拆分。

示例（few-shot）：
问："广东省的销售额是多少"
答：SELECT ROUND(SUM(o.pay_amount),2) AS sales FROM ydsh_dwd.dwd_order o JOIN ydsh_dwd.dim_store s ON o.store_id=s.store_id WHERE s.province='广东省' AND o.order_status='已完成';
问："销量最高的前5个品类"
答：SELECT p.category, SUM(i.quantity) AS total_qty FROM ydsh_dwd.dwd_order_item i JOIN ydsh_dwd.dim_product p ON i.product_id=p.product_id JOIN ydsh_dwd.dwd_order o ON i.order_id=o.order_id AND o.order_status='已完成' GROUP BY p.category ORDER BY SUM(i.quantity) DESC LIMIT 5;
问："2024年每月的GMV和订单量趋势"
答：SELECT o.order_month, ROUND(SUM(o.pay_amount),2) AS gmv, COUNT(DISTINCT o.order_id) AS order_cnt FROM ydsh_dwd.dwd_order o WHERE o.order_month LIKE '2024%' AND o.order_status='已完成' GROUP BY o.order_month ORDER BY o.order_month;

只输出 SQL 本身，不要任何解释。"""

client = OpenAI(api_key=api_key,
                base_url=os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"))

def generate_sql(question: str) -> str:
    resp = client.chat.completions.create(
        model=os.environ.get("ZHIPU_MODEL", "glm-4-flash"),
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": question}],
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    # 提取 ```sql ... ``` 或裸 SQL
    m = re.search(r"```(?:sql)?\s*(.+?)\s*```", text, re.S)
    sql = m.group(1).strip() if m else text.strip().rstrip(";") + ";"
    return sql

def validate_sql(sql: str):
    """只读校验：拦截任何写操作"""
    banned = re.findall(r"\b(insert|update|delete|drop|create|alter|truncate)\b", sql, re.I)
    if banned:
        raise ValueError(f"模型生成了被禁止的语句: {banned}，已拦截")
    if not sql.lower().lstrip().startswith("select"):
        raise ValueError("非 SELECT 语句，已拦截")

def _run_sql_pyhive(sql: str):
    """容器内执行：pyhive 直连 HiveServer2（容器里没有 docker CLI）"""
    from pyhive import hive
    conn = hive.connect(host=os.environ.get("HIVE_HOST", "hive-server"),
                        port=10000, database="default", username="hive", auth="NONE")
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        header = [(d[0].split(".")[-1] if d[0] else "col") for d in cursor.description]
        rows = ["\t".join(header)]
        for vals in cursor.fetchall():
            rows.append("\t".join("" if v is None else str(v) for v in vals))
        return rows
    finally:
        conn.close()

def run_sql(sql: str):
    """在 Hive 上执行并返回 (结果行, 错误信息)"""
    sql = sql.rstrip(";")
    if os.path.exists("/.dockerenv"):
        # Docker 容器内运行：直连 HiveServer2
        try:
            return _run_sql_pyhive(sql), None
        except Exception as e:
            return [], str(e)
    # 宿主机运行：经 docker exec 调 beeline
    cmd = ["docker", "exec", "ydsh-hiveserver2", "bash", "-c",
           f"beeline -u jdbc:hive2://localhost:10000 --outputformat=tsv2 --silent=true -e \"{sql}\" 2>&1"]
    env = os.environ.copy(); env["MSYS_NO_PATHCONV"] = "1"
    out = subprocess.run(cmd, capture_output=True, text=True, env=env).stdout
    rows, err = [], None
    for l in out.splitlines():
        ls = l.strip()
        if not ls or ls.startswith(("INFO", "WARN", "[WARN]", "SLF4J", "Connecting", "Connected",
                                    "Driver", "Transaction", "0:", "Beeline version",
                                    "Closing", "No such file")):
            continue
        if "Error:" in ls or "FAILED:" in ls:
            err = ls
        elif not ls.startswith("---"):
            rows.append(l)
    return rows, err

def repair_sql(sql: str, error: str) -> str:
    """把 Hive 报错回传给大模型，让它自行修正 SQL（自修复重试）"""
    resp = client.chat.completions.create(
        model=os.environ.get("ZHIPU_MODEL", "glm-4-flash"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"你生成的 SQL 在 Hive 上执行报错，请修正后只输出修正后的 SQL，不要解释。\n\n原SQL：\n{sql}\n\nHive报错：\n{error}"},
        ],
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    m = re.search(r"```(?:sql)?\s*(.+?)\s*```", text, re.S)
    return (m.group(1).strip() if m else text).rstrip(";") + ";"

if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else "销量最高的前5个品类"
    print(f"【问题】{question}")
    sql = generate_sql(question)
    print(f"【生成 SQL】\n{sql}")
    validate_sql(sql)
    rows, err = run_sql(sql)
    retries = 0
    while err and retries < 2:
        retries += 1
        print(f"【执行报错，第{retries}次自修复】{err}")
        sql = repair_sql(sql, err)
        validate_sql(sql)
        print(f"【修正后 SQL】\n{sql}")
        rows, err = run_sql(sql)
    if err:
        raise SystemExit(f"重试 {retries} 次后仍执行失败：{err}")
    print(f"【执行结果】(共{len(rows)}行)" + (f"，经{retries}次自修复" if retries else ""))
    for r in rows[:12]:
        print(" ", r)

# ---------- 时序预测：预测类问题不走 SQL，改走预测模型（第3周 predict_gmv 方案） ----------
# 设计原因：NL2SQL 只能生成 SELECT 查历史，无法做时序外推；
# 预测类问题（含"预测/预报/未来N天"）路由到本模块：Hive 实查 dws_order_day 日 GMV →
# 滞后特征（lag1/lag7/ma7/星期几）+ 线性回归 → 迭代预测未来 N 天。

def is_prediction_question(question: str) -> bool:
    q = (question or "").strip()
    return ("预测" in q or "预报" in q or "预估" in q) or ("未来" in q and "趋势" not in q)

def parse_forecast_days(question: str) -> int:
    m = re.search(r"未来\s*(\d+)\s*[天日]", question or "")
    d = int(m.group(1)) if m else 7
    return max(1, min(d, 30))

def predict_sales(days: int = 7):
    """从 Hive 实查每日 GMV，滞后特征+线性回归迭代预测未来 N 天。
    返回 (hist_df, pred_df, metrics)；与第3周 predict_gmv.py 同一方法。"""
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LinearRegression

    rows, err = run_sql("SELECT dt, gmv FROM ydsh_dws.dws_order_day ORDER BY dt")
    if err or len(rows) < 15:
        raise RuntimeError(f"预测所需历史数据查询失败：{err or '数据行不足'}")
    df = pd.DataFrame([r.split("\t") for r in rows[1:]], columns=["dt", "gmv"])
    df["dt"] = pd.to_datetime(df["dt"])
    df["gmv"] = pd.to_numeric(df["gmv"])
    df = df.sort_values("dt").reset_index(drop=True)

    FEATURES = ["lag1", "lag7", "ma7", "dow"]
    feat_df = df.set_index("dt")
    feat_df["lag1"] = feat_df["gmv"].shift(1)
    feat_df["lag7"] = feat_df["gmv"].shift(7)
    feat_df["ma7"] = feat_df["gmv"].shift(1).rolling(7).mean()
    feat_df["dow"] = feat_df.index.day_of_week
    feat = feat_df.dropna()

    # 留出最后 30 天做评估（与第3周报告口径一致）
    split_date = feat.index[-min(30, len(feat) - 1)]
    train, test = feat[feat.index < split_date], feat[feat.index >= split_date]
    model = LinearRegression().fit(train[FEATURES], train["gmv"])
    test_pred = model.predict(test[FEATURES])
    mape = float(np.mean(np.abs((test["gmv"] - test_pred) / test["gmv"])) * 100)

    # 全量重训后迭代预测未来 N 天
    model = LinearRegression().fit(feat[FEATURES], feat["gmv"])
    hist = df["gmv"].tolist()
    future_dates = pd.date_range(df["dt"].iloc[-1] + pd.Timedelta(days=1), periods=days)
    preds = []
    for d in future_dates:
        p = float(model.predict(pd.DataFrame(
            [[hist[-1], hist[-7], float(np.mean(hist[-7:])), d.day_of_week]],
            columns=FEATURES))[0])
        preds.append(p)
        hist.append(p)

    hist_df = df[["dt", "gmv"]]
    pred_df = pd.DataFrame({"dt": future_dates.date, "pred_gmv": [round(p, 2) for p in preds]})
    metrics = {"mape": round(mape, 1), "total": round(sum(preds), 2),
               "daily_avg": round(float(np.mean(preds)), 0), "data_days": len(df)}
    return hist_df, pred_df, metrics
