-- ============================================================
-- 第4周 子任务5：Hive 查询优化对比（分区裁剪 / 全表扫描）
-- dwd_order 按 order_month 分区（12 个月分区），验证分区裁剪收益
-- 用法：python python/optimize_compare.py（脚本内计时执行）
-- ============================================================

-- 优化前：全表扫描（12 个分区全部读取）
SELECT COUNT(*) AS cnt_all, CAST(SUM(pay_amount) AS DECIMAL(14,2)) AS gmv_all
FROM ydsh_dwd.dwd_order
WHERE order_status = '已完成';

-- 优化后：分区裁剪（只读 1 个月分区）
SELECT COUNT(*) AS cnt_1m, CAST(SUM(pay_amount) AS DECIMAL(14,2)) AS gmv_1m
FROM ydsh_dwd.dwd_order
WHERE order_status = '已完成'
  AND order_month = '2024-08';

-- 优化后：分区裁剪（3 个月分区，与全表 GMV 可比）
SELECT COUNT(*) AS cnt_3m, CAST(SUM(pay_amount) AS DECIMAL(14,2)) AS gmv_3m
FROM ydsh_dwd.dwd_order
WHERE order_status = '已完成'
  AND order_month IN ('2024-08', '2024-09', '2024-10');
