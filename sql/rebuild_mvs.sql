TRUNCATE phenotype_state_mv;
INSERT INTO phenotype_state_mv (type,marker,state,svalues,count) SELECT * FROM phenotype_state_build_vw;
