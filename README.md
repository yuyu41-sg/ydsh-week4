# 云购生活新零售数仓 · 第 4 周（可视化 · 部署 · 压测）

ydsh-team · 张宇（20230308059）｜ 前置仓库：[week1](https://github.com/yuyu41-sg/ydsh-week1) / [week2](https://github.com/yuyu41-sg/ydsh-week2) / [week3](https://github.com/yuyu41-sg/ydsh-week3)

## 本周交付物（对照任务书清单）

| 序号 | 交付物 | 位置 |
|---|---|---|
| 1 | Superset 仪表板（6 图表，Hive+MySQL 双数据源） | http://localhost:8088（`sql/superset_setup.py` + `sql/superset_charts.py` 一键创建） |
| 2 | ECharts 数据大屏（scale 自适应 + 折线/柱状/散点/热力/地图） | `bigscreen/index.html` |
| 3 | Streamlit NL2SQL 问答闭环 | `app/`（http://localhost:8501） |
| 4 | docker-compose.yml 多服务一键部署 | `docker-compose.yml`（mysql/metastore/hive-server/superset/app 五服务 + 健康检查） |
| 5 | 部署手册 / API 配置指南 | `docs/部署手册.md`、`docs/API配置指南.md` |
| 6 | 压力测试记录 | `docs/压力测试记录.md`（`python/stress_test.py`） |

## 快速开始

```bash
cp .env.example .env          # 填入 ZHIPU_API_KEY
docker compose up -d          # 五服务一键启动（依赖+健康检查）
bash sql/replay_all.sh        # 首次：数仓数据初始化（写入命名卷，重建不丢）
python sql/load_mysql.py      # 首次：ADS 指标导入 MySQL
python sql/superset_setup.py  # 首次：注册数据源
python sql/superset_charts.py # 首次：创建图表与仪表板
```

## 服务端口

| 服务 | 地址 | 说明 |
|---|---|---|
| Superset | http://localhost:8088 | admin / admin，仪表板"云购生活经营分析仪表板" |
| Streamlit 问答 | http://localhost:8501 | NL2SQL 闭环（生成SQL→校验→Hive执行→图表） |
| HiveServer2 | localhost:10000 | beeline / 数据大屏数据源 |
| MySQL 业务库 | localhost:3307 | ydsh_ads（Superset 第二数据源） |

## 技术要点

- **密钥安全**：全部经 `.env` 注入，compose 只写 `${VAR}`；LLM Key 只注入 app 容器
- **数据持久化**：数仓数据在命名卷 `hive-warehouse`（吸取第 3 周容器重建丢数据教训）
- **NL2SQL 增强**：SELECT-only 拦截 + 报错回传自修复（repair_sql，最多 2 次）
- **大屏自适应**：1920×1080 设计稿整体 scale 缩放，任意分辨率不错位
- **地图合规**：省份地图用 ECharts 官方标准 china.js，版图符合国家标准
- **查询优化**：分区裁剪对比实测（见 docs/压力测试记录.md，含小数据集的诚实边界分析）
