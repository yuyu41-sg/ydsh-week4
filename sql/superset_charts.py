# -*- coding: utf-8 -*-
"""
第4周：Superset 数据集与图表批量创建（REST API，可重复执行）
数据集：MySQL(ydsh_ads) 5 张 + Hive(ydsh_ads) 2 张
图表：KPI 大数字 / 销售趋势折线(Hive) / 品类柱状 / 区域分布条形 / 支付方式饼图 / 门店TopN排行表
最后组装成仪表板「云购生活经营分析仪表板」
用法：python sql/superset_charts.py
"""
import json
import requests

SUPERSET = "http://localhost:8088"
s = requests.Session()

def login():
    r = s.post(f"{SUPERSET}/api/v1/security/login",
               json={"username": "admin", "password": "admin",
                     "provider": "db", "refresh": True}, timeout=30)
    r.raise_for_status()
    s.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    r = s.get(f"{SUPERSET}/api/v1/security/csrf_token/", timeout=30)
    s.headers["X-CSRF-Token"] = r.json()["result"]

def ensure_dataset(database, schema, table):
    """按 (database, schema, table) 幂等创建数据集，返回 id"""
    q = {"q": f'(filters:!((col:table_name,opr:eq,value:{table})))'}
    r = s.get(f"{SUPERSET}/api/v1/dataset/", timeout=30, params=q)
    for it in r.json().get("result", []):
        if it["database"]["id"] == database and it["schema"] == schema:
            return it["id"]
    r = s.post(f"{SUPERSET}/api/v1/dataset/", timeout=60,
               json={"database": database, "schema": schema, "table_name": table,
                     "owners": []})
    r.raise_for_status()
    return r.json()["id"]

def m(column, label=None, agg="SUM"):
    return {"expressionType": "SIMPLE", "aggregate": agg, "label": label or f"{agg}({column})",
            "column": {"column_name": column}}

def ensure_chart(slice_name, viz_type, ds_id, form_extra):
    q = {"q": f'(filters:!((col:slice_name,opr:eq,value:{slice_name})))'}
    r = s.get(f"{SUPERSET}/api/v1/chart/", timeout=30, params=q)
    items = r.json().get("result", [])
    params = {"datasource": f"{ds_id}__table", "viz_type": viz_type, **form_extra}
    payload = {"slice_name": slice_name, "viz_type": viz_type,
               "datasource_id": ds_id, "datasource_type": "table",
               "params": json.dumps(params, ensure_ascii=False)}
    if items:
        cid = items[0]["id"]
        r = s.put(f"{SUPERSET}/api/v1/chart/{cid}", timeout=60, json=payload)
        print(f"已更新图表 {slice_name} (id={cid}) status={r.status_code}")
        return cid
    r = s.post(f"{SUPERSET}/api/v1/chart/", timeout=60, json=payload)
    if r.status_code not in (200, 201):
        print("创建失败:", slice_name, r.status_code, r.text[:300])
        raise SystemExit(1)
    cid = r.json()["id"]
    print(f"已创建图表 {slice_name} (id={cid})")
    return cid

login()
# ---------- 数据集 ----------
ds_kpi   = ensure_dataset(2, "ydsh_ads", "ads_kpi_result")        # Hive
ds_daily = ensure_dataset(2, "ydsh_ads", "ads_sales_daily")       # Hive
ds_month = ensure_dataset(1, "ydsh_ads", "monthly_trend")         # MySQL
ds_cat   = ensure_dataset(1, "ydsh_ads", "category_sales")        # MySQL
ds_prov  = ensure_dataset(1, "ydsh_ads", "province_sales")        # MySQL
ds_pay   = ensure_dataset(1, "ydsh_ads", "pay_type")              # MySQL
ds_top   = ensure_dataset(1, "ydsh_ads", "store_top10")           # MySQL
print("数据集:", ds_kpi, ds_daily, ds_month, ds_cat, ds_prov, ds_pay, ds_top)

# ---------- 图表 ----------
charts = []

charts.append(ensure_chart("① 全期KPI-GMV大数字", "big_number_total", ds_kpi, {
    "metric": m("gmv", "全期GMV"),
    "y_format": ",.2f",
    "subheader": "全周期成交总额",
}))
# 注：big_number 需要时间轴列，KPI 表无日期列，故用 big_number_total

charts.append(ensure_chart("② 销售趋势-每日GMV折线", "echarts_timeseries_line", ds_daily, {
    "x_axis": "dt",
    "metrics": [m("gmv", "GMV"), m("orders", "订单量")],
    "time_grain_sqla": "P1D",
    "rich_tooltip": True,
}))

charts.append(ensure_chart("③ 品类销售额-柱状图", "echarts_timeseries_bar", ds_cat, {
    "x_axis": "category",
    "metrics": [m("sales", "销售额")],
    "series_limit": 10,
    "order_desc": True,
    "show_legend": False,
}))
# 注：Superset 6.1 镜像移除了 dist_bar 插件，改用 echarts_timeseries_bar（支持非时间列 x 轴）

charts.append(ensure_chart("④ 区域分布-省份销售额条形图", "echarts_timeseries_bar", ds_prov, {
    "x_axis": "province",
    "metrics": [m("sales", "销售额")],
    "series_limit": 20,
    "order_desc": True,
    "orientation": "horizontal",
    "y_axis_layout": "LEFT",
    "show_legend": False,
}))

charts.append(ensure_chart("⑤ 支付方式占比-漏斗图", "funnel", ds_pay, {
    "groupby": ["name"],
    "metric": m("cnt", "订单数"),
    "metrics": [m("cnt", "订单数")],
    "sort_by_metric": False,
}))
# 注：6.1 镜像无 echarts_pie 插件，用 funnel 展示占比结构；漏斗图需同时提供 metric 与 metrics

charts.append(ensure_chart("⑥ 门店TopN-排行表", "table", ds_top, {
    "all_columns": ["store", "province", "sales", "orders"],
    "page_length": 10,
    "query_mode": "aggregate",
    "metrics": [m("sales", "销售额"), m("orders", "订单数")],
    "groupby": ["store", "province"],
    "include_time": False,
}))
print("图表ID:", charts)

# ---------- 仪表板 ----------
q = {"q": '(filters:!((col:dashboard_title,opr:eq,value:云购生活经营分析仪表板)))'}
r = s.get(f"{SUPERSET}/api/v1/dashboard/", timeout=30, params=q)
items = r.json().get("result", [])
if items:
    did = items[0]["id"]
    s.put(f"{SUPERSET}/api/v1/dashboard/{did}", timeout=60,
          json={"slices": charts})
    print(f"已更新仪表板 (id={did})，挂载 {len(charts)} 个图表")
else:
    r = s.post(f"{SUPERSET}/api/v1/dashboard/", timeout=60,
               json={"dashboard_title": "云购生活经营分析仪表板",
                     "slices": charts})
    r.raise_for_status()
    did = r.json()["id"]
    print(f"已创建仪表板 (id={did})，挂载 {len(charts)} 个图表")

print("\n完成。浏览器打开 http://localhost:8088 （admin/admin）查看仪表板")
