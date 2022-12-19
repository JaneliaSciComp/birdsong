TRUNCATE bird_comparison_summary_mv;
INSERT INTO bird_comparison_summary_mv (comparison,relationship,cnt,mean) SELECT comparison,relationship,COUNT(1) AS cnt,AVG(value) AS mean FROM bird_comparison_vw GROUP BY 1,2;
