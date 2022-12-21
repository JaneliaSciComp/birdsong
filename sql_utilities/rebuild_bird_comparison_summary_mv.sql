TRUNCATE bird_comparison_summary_mv;
INSERT INTO bird_comparison_summary_mv (comparison,relationship,cnt,mean) SELECT comparison,relationship,COUNT(1) AS cnt,AVG(ABS(value)) AS mean FROM bird_comparison_vw GROUP BY 1,2;
TRUNCATE bird_count_summary_mv;
INSERT INTO bird_count_summary_mv (comparison,cnt) SELECT comparison,COUNT(DISTINCT bird1)+1 FROM bird_comparison_vw GROUP BY 1
