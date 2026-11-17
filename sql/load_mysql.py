# -*- coding: utf-8 -*-
"""
第4周：把 ADS 层指标数据导入 MySQL 业务库（ydsh_ads），供 Superset 第二数据源使用
数据来源：bigscreen/data.json（由 Hive 实查导出）
用法：python sql/load_mysql.py
"""
import json
import os
import pymysql

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data = json.load(open(os.path.join(BASE, "bigscreen", "data.json"), encoding="utf-8"))

conn = pymysql.connect(host="127.0.0.1", port=3307, user="root", password="root", charset="utf8mb4")
cur = conn.cursor()
cur.execute("CREATE DATABASE IF NOT EXISTS ydsh_ads DEFAULT CHARSET utf8mb4")
cur.execute("USE ydsh_ads")

def rebuild(table, ddl, rows, placeholder):
    cur.execute(f"DROP TABLE IF EXISTS {table}")
    cur.execute(ddl)
    cur.executemany(f"INSERT INTO {table} VALUES ({placeholder})", rows)

rebuild("kpi_result",
        "CREATE TABLE kpi_result (gmv DECIMAL(14,2), orders INT, aov DECIMAL(10,2), active_users INT, repurchase_rate DECIMAL(6,4))",
        [(14151214.68, 5642, 2508.19, 997, 0.9809)], "%s,%s,%s,%s,%s")

rebuild("monthly_trend",
        "CREATE TABLE monthly_trend (month VARCHAR(7), gmv DECIMAL(14,2), orders INT)",
        [(r["month"], r["gmv"], r["orders"]) for r in data["monthly_trend"]], "%s,%s,%s")

rebuild("category_sales",
        "CREATE TABLE category_sales (category VARCHAR(30), sales DECIMAL(14,2))",
        [(r["category"], r["sales"]) for r in data["category_sales"]], "%s,%s")

rebuild("province_sales",
        "CREATE TABLE province_sales (province VARCHAR(30), sales DECIMAL(14,2))",
        [(r["province"], r["sales"]) for r in data["province_sales"]], "%s,%s")

rebuild("pay_type",
        "CREATE TABLE pay_type (name VARCHAR(20), cnt INT)",
        [(r["name"], r["count"]) for r in data["pay_type"]], "%s,%s")

rebuild("store_top10",
        "CREATE TABLE store_top10 (store VARCHAR(50), province VARCHAR(30), sales DECIMAL(14,2), orders INT)",
        [(r["store"], r["province"], r["sales"], r["orders"]) for r in data["store_top10"]], "%s,%s,%s,%s")

rebuild("heatmap",
        "CREATE TABLE heatmap (hour VARCHAR(2), category VARCHAR(30), qty DECIMAL(10,0))",
        [(r["hour"], r["category"], r["qty"]) for r in data["heatmap"]], "%s,%s,%s")

conn.commit()
cur.execute("SHOW TABLES")
tables = [r[0] for r in cur.fetchall()]
print("MySQL ydsh_ads 表：", tables)
conn.close()
