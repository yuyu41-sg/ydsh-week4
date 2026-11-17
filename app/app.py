# -*- coding: utf-8 -*-
"""
子任务3：Streamlit 对话式问答界面（接入第3周 NL2SQL 后端）
闭环：提问 → 大模型生成 SQL → SELECT-only 校验 → Hive 执行 → 结果表格/图表渲染
特性：历史对话、加载状态、错误提示、自动图表渲染
用法：streamlit run app/app.py  （需先启动 Hive 容器并配置 .env）
"""
import json
import os
import sys

import pandas as pd
import streamlit as st

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "app"))

st.set_page_config(page_title="云购生活 · 智能经营问答", page_icon="🛒", layout="wide")
st.title("🛒 云购生活 · 智能经营问答")
st.caption("NL2SQL 闭环：自然语言 → 生成 SQL → SELECT-only 校验 → Hive 执行 → 图表渲染 ｜ 模型：智谱 GLM（glm-4-flash）")

# ---------- 复用第3周 NL2SQL 后端 ----------
from nl2sql import generate_sql, run_sql, validate_sql  # noqa: E402


def to_dataframe(rows):
    """beeline tsv 输出 → DataFrame（首行为表头）"""
    if not rows:
        return None
    header = [h.strip() for h in rows[0].split("\t")]
    data = [r.split("\t") for r in rows[1:]]
    df = pd.DataFrame(data, columns=header)
    # 尽量转数值列
    for c in df.columns:
        try:
            df[c] = pd.to_numeric(df[c])
        except (ValueError, TypeError):
            pass
    return df


def auto_chart(df):
    """简单启发式：1 个类别列 + 1 个数值列 → 柱状图；多行时间序列 → 折线"""
    if df is None or df.empty:
        return None
    num_cols = df.select_dtypes("number").columns.tolist()
    cat_cols = [c for c in df.columns if c not in num_cols]
    if not num_cols:
        return None
    if len(cat_cols) == 1 and len(num_cols) == 1 and len(df) <= 20:
        return ("bar", cat_cols[0], num_cols)
    if len(df) > 5:
        return ("line", cat_cols[0] if cat_cols else None, num_cols[:2])
    return None


# ---------- 历史对话 ----------
if "history" not in st.session_state:
    st.session_state.history = []

# 渲染历史
for h in st.session_state.history:
    with st.chat_message(h["role"], avatar=("🧑‍💼" if h["role"] == "user" else "🤖")):
        st.markdown(h["content"])
        for extra in h.get("extras", []):
            extra()

question = st.chat_input("请输入你的问题，例如：销量最高的前5个品类 / 2024年6月广东省的销售额是多少")

if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑‍💼"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="🤖"):
        extras = []
        try:
            # 1. 生成 SQL（加载状态）
            with st.spinner("🧠 大模型正在生成 SQL…"):
                sql = generate_sql(question)
            st.code(sql, language="sql")
            extras.append(lambda s=sql: st.code(s, language="sql"))

            # 2. 安全校验
            validate_sql(sql)

            # 3. Hive 执行（含自修复重试）
            with st.spinner("🐘 正在 Hive 上执行查询…"):
                rows, err = run_sql(sql)
                retries = 0
                while err and retries < 2:
                    retries += 1
                    st.warning(f"Hive 报错，第 {retries} 次自修复：{err[:120]}")
                    from nl2sql import repair_sql
                    sql = repair_sql(sql, err)
                    validate_sql(sql)
                    st.code(sql, language="sql")
                    rows, err = run_sql(sql)
                if err:
                    st.error(f"重试 {retries} 次后仍执行失败：{err}")
                    raise RuntimeError(err)

            df = to_dataframe(rows)
            if df is None or df.empty:
                st.info("查询完成，但没有返回数据行。")
            else:
                st.markdown(f"**查询结果**（{len(df)} 行）")
                st.dataframe(df, use_container_width=True)
                extras.append(lambda d=df: st.dataframe(d, use_container_width=True))

                # 4. 自动图表渲染
                chart = auto_chart(df)
                if chart:
                    kind, x, ys = chart
                    if kind == "bar":
                        st.bar_chart(df.set_index(x)[ys])
                    else:
                        st.line_chart(df.set_index(x)[ys])
                    extras.append(lambda k=kind, x=x, y=ys, d=df:
                                  (st.bar_chart(d.set_index(x)[y]) if k == "bar"
                                   else st.line_chart(d.set_index(x)[y])))
        except ValueError as e:
            st.error(f"⛔ 安全拦截：{e}")
        except Exception as e:
            st.error(f"❌ 出错了：{e}")

        st.session_state.history.append(
            {"role": "assistant", "content": "已完成查询。" if not err else "查询失败。",
             "extras": extras})

# 侧栏：说明与示例
with st.sidebar:
    st.subheader("使用说明")
    st.markdown(
        "1. 输入自然语言问题\n"
        "2. 系统生成只读 SQL 并校验\n"
        "3. Hive 实际执行（报错自动自修复）\n"
        "4. 结果自动渲染为表格与图表")
    st.subheader("示例问题")
    for ex in ["销量最高的前5个品类",
               "2024年6月广东省的销售额是多少",
               "2024年每月的GMV和订单量趋势",
               "删除所有订单数据（演示安全拦截）"]:
        st.markdown(f"- {ex}")
    st.caption("⚠️ SELECT-only 拦截已开启；写操作将被拒绝并记录。")
