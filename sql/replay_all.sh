#!/bin/bash
# ============================================================
# 第4周：数仓数据全链路初始化（仅首次部署执行）
# 前提：docker compose up -d 已启动且 hive-server healthy
# 顺序：ODS建表→加载→缺失值→去重→枚举标准化→异常值→字段合并
#       →DWD建表→DWD加载→DWS→ADS
# ============================================================
set -e
HIVE="docker exec ydsh-hiveserver2 bash -c"

# 注入 week2/week3 脚本（week1 的脚本经 /sql 挂载，无需 cp）
docker cp ../ydsh-week2/sql ydsh-hiveserver2:/tmp/sql2
docker cp ../ydsh-week3/sql ydsh-hiveserver2:/tmp/sql3

for f in /sql/ods/create_ods.sql /sql/ods/load_ods.sql \
         /sql/clean/missing_value.sql /sql/clean/dedup.sql \
         /tmp/sql2/clean/enum_standard.sql /tmp/sql2/clean/outlier_format.sql \
         /tmp/sql2/clean/field_merge.sql /tmp/sql2/dwd/01_create_dwd.sql \
         /tmp/sql2/dwd/02_load_dwd.sql /tmp/sql3/dws/create_dws.sql \
         /tmp/sql3/ads/create_ads.sql; do
  echo ">>> 执行 $f"
  beeline_cmd="beeline -u jdbc:hive2://localhost:10000 --silent=true -f $f"
  $HIVE "$beeline_cmd" > /tmp/beeline_out.txt 2>&1
  if grep -qiE "FAILED:|SemanticException" /tmp/beeline_out.txt; then
    echo "!! $f 执行失败"; grep -iE "FAILED:|SemanticException" /tmp/beeline_out.txt | head -3; exit 1
  fi
  echo "    OK"
done

echo ""
echo "=== 校验 KPI（期望 GMV 14151214.68 / 5642 单） ==="
$HIVE "beeline -u jdbc:hive2://localhost:10000 --outputformat=tsv2 --silent=true -e 'SELECT CAST(gmv AS DECIMAL(14,2)), orders, repurchase_rate FROM ydsh_ads.ads_kpi_result' 2>/dev/null" | grep -v SLF4J
echo "=== 初始化完成 ==="
