CREATE OR REPLACE VIEW cv_term_vw AS
SELECT cv.name          AS cv
      ,cvt.id           AS id
      ,cvt.name         AS cv_term
      ,cvt.definition   AS definition
      ,cvt.display_name AS display_name
      ,cvt.data_type    AS data_type
      ,cvt.is_current   AS is_current 
      ,cvt.create_date  AS create_date
FROM cv
JOIN cv_term cvt ON (cv.id = cvt.cv_id)
;

CREATE OR REPLACE VIEW cv_relationship_vw AS
SELECT cv.id    AS context_id
      ,cv.name  AS context
      ,cv1.id   AS subject_id
      ,cv1.name AS subject
      ,cvt.id   AS relationship_id
      ,cvt.name AS relationship
      ,cv2.id   AS object_id
      ,cv2.name AS object
FROM cv
    ,cv_relationship cr
    ,cv_term cvt
    ,cv cv1
    ,cv cv2
WHERE cr.type_id = cvt.id
  AND cr.subject_id = cv1.id
  AND cr.object_id = cv2.id
  AND cr.is_current = 1
  AND cvt.is_current = 1
  AND cv1.is_current = 1
  AND cv2.is_current = 1
  AND cv.id = cvt.cv_id
;

CREATE OR REPLACE VIEW cv_term_relationship_vw AS
SELECT cv_subject.id    AS subject_context_id
      ,cv_subject.name  AS subject_context
      ,cvt_subject.id   AS subject_id
      ,cvt_subject.name AS subject
      ,cv_rel.id        AS relationship_context_id
      ,cv_rel.name      AS relationship_context
      ,cvt_rel.id       AS relationship_id
      ,cvt_rel.name     AS relationship
      ,cv_object.id     AS object_context_id
      ,cv_object.name   AS object_context
      ,cvt_object.id    AS object_id
      ,cvt_object.name  AS object
FROM cv_term_relationship cr
    ,cv_term cvt_rel
    ,cv cv_rel
    ,cv_term cvt_subject
    ,cv cv_subject
    ,cv_term cvt_object
    ,cv cv_object
WHERE cr.type_id = cvt_rel.id
  AND cv_rel.id = cvt_rel.cv_id
  AND cr.subject_id = cvt_subject.id
  AND cv_subject.id = cvt_subject.cv_id
  AND cr.object_id = cvt_object.id
  AND cv_object.id = cvt_object.cv_id
  AND cr.is_current = 1
  AND cvt_rel.is_current = 1
  AND cvt_subject.is_current = 1
  AND cvt_object.is_current = 1
;

CREATE OR REPLACE VIEW cv_term_to_table_mapping_vw AS
SELECT cv_subject.name AS cv
      ,subject.id      AS cv_term_id
      ,subject.name    AS cv_term
      ,type.name       AS relationship
      ,object.name     AS schema_term
FROM cv_term_relationship 
JOIN cv_term type ON (type.id = cv_term_relationship.type_id)
JOIN cv cv_type ON (cv_type.id = type.cv_id)
JOIN cv_term subject ON (subject.id = cv_term_relationship.subject_id)
JOIN cv cv_subject ON (cv_subject.id = subject.cv_id)
JOIN cv_term object ON (object.id = cv_term_relationship.object_id)
WHERE cv_type.name = 'schema'
;

CREATE OR REPLACE VIEW cv_term_validation_vw AS
SELECT cv_subject.name AS term_context
      ,subject.id AS term_id
      ,subject.name AS term
      ,type.name AS relationship
      ,object.name AS rule
FROM cv_term_relationship 
JOIN cv_term type ON (type.id = cv_term_relationship.type_id)
JOIN cv_term subject ON (subject.id = cv_term_relationship.subject_id)
JOIN cv cv_subject ON (cv_subject.id = subject.cv_id)
JOIN cv_term object ON (object.id = cv_term_relationship.object_id)
JOIN cv cv_type ON (cv_type.id = type.cv_id)
WHERE type.name = 'validated_by'
;

CREATE OR REPLACE VIEW bird_vw AS
SELECT b.id           AS id
      ,b.name         AS name
      ,b.band         AS band
      ,n.name         AS nest
      ,v.display_name AS vendor
      ,nl.name        AS nest_location
      ,c.name         AS clutch
      ,b1.name        AS sire
      ,b2.name        AS damsel
      ,b.tutor        AS tutor
      ,l.name         AS location
      ,u.name         AS user
      ,CASE WHEN LENGTH(u.last) THEN CONCAT_WS(", ",u.last,u.first) ELSE NULL END AS username
      ,b.sex          AS sex
      ,b.notes        AS notes
      ,IF(b.alive=1,DATEDIFF(CURRENT_DATE,b.hatch_early),NULL) AS current_age
      ,b.alive        AS alive
      ,b.hatch_early  AS hatch_early
      ,b.hatch_late   AS hatch_late
      ,b.death_date   AS death_date
FROM bird b
LEFT OUTER JOIN nest n ON (n.id=b.nest_id)
LEFT OUTER JOIN cv_term nl ON (nl.id=n.location_id)
LEFT OUTER JOIN clutch c ON (c.id=b.clutch_id)
LEFT OUTER JOIN bird_relationship r ON (r.type="genetic" AND r.bird_id=b.id)
LEFT OUTER JOIN bird b1 ON (b1.id=r.sire_id)
LEFT OUTER JOIN bird b2 ON (b2.id=r.damsel_id)
LEFT OUTER JOIN cv_term l ON (l.id=b.location_id)
LEFT OUTER JOIN user u ON (b.user_id = u.id)
LEFT OUTER JOIN cv_term v ON (v.id=b.vendor_id)
;

CREATE OR REPLACE VIEW bird_event_vw AS
SELECT be.id          AS id
      ,b.name         AS name
      ,n.name         AS nest
      ,l.name         AS location
      ,s.display_name AS status
      ,be.terminal    AS terminal
      ,u.name         AS user
      ,CASE WHEN LENGTH(u.last) THEN CONCAT_WS(", ",u.last,u.first) ELSE NULL END AS username
      ,be.notes       AS notes
      ,be.event_date  AS event_date
FROM bird_event be
JOIN bird b ON (b.id=be.bird_id)
LEFT OUTER JOIN nest n ON (n.id=be.nest_id)
LEFT OUTER JOIN cv_term l ON (l.cv_id=getCvId("location",NULL) AND l.id=be.location_id)
JOIN cv_term s ON (s.cv_id=getCvId("bird_status",NULL) AND s.id=be.status_id)
JOIN user u ON (u.id = be.user_id)
;

CREATE OR REPLACE VIEW bird_property_vw AS
SELECT bp.id                AS id
      ,b.id                 AS project_id
      ,b.name               AS name
      ,cv.name              AS cv
      ,cv_term.name         AS type
      ,cv_term.display_name AS type_display
      ,bp.value             AS value
      ,bp.create_date       AS create_date
FROM bird_property bp
JOIN bird b ON (bp.bird_id = b.id)
JOIN cv_term ON (bp.type_id = cv_term.id)
JOIN cv ON (cv_term.cv_id = cv.id)
;

CREATE OR REPLACE VIEW bird_relationship_vw AS
SELECT br.id                 AS id
      ,br.type               AS type
      ,b1.name               AS bird
      ,b2.name               AS sire
      ,b3.name               AS damsel
      ,br.notes              AS notes
      ,br.relationship_start AS relationship_start
      ,br.relationship_end   AS relationship_end
FROM bird_relationship br
JOIN bird b1 ON (br.bird_id=b1.id)
LEFT OUTER JOIN bird b2 ON (br.sire_id=b2.id)
LEFT OUTER JOIN bird b3 ON (br.damsel_id=b3.id)
;

CREATE OR REPLACE VIEW clutch_vw AS
SELECT c.id           AS id
      ,c.name         AS name
      ,n.name         AS nest
      ,nl.name        AS nest_location
      ,c.notes        AS notes
      ,c.clutch_early AS clutch_early
      ,c.clutch_late  AS clutch_late
FROM clutch c
JOIN nest n ON (n.id=c.nest_id)
LEFT OUTER JOIN cv_term nl ON (nl.cv_id=getCvId("location",NULL) AND nl.id=n.location_id)
;

CREATE OR REPLACE VIEW nest_vw AS
SELECT n.id          AS id
      ,n.name        AS name
      ,n.band        AS band
      ,b1.name       AS sire
      ,b2.name       AS damsel
      ,f1.name       AS female1
      ,f2.name       AS female2
      ,f3.name       AS female3
      ,l.name        AS location
      ,n.active      AS active
      ,n.breeding    AS breeding
      ,n.fostering   AS fostering
      ,n.tutoring    AS tutoring
      ,n.notes       AS notes
      ,n.create_date AS create_date
FROM nest n
LEFT OUTER JOIN bird b1 ON (b1.id=n.sire_id)
LEFT OUTER JOIN bird b2 ON (b2.id=n.damsel_id)
LEFT OUTER JOIN bird f1 ON (f1.id=n.female1_id)
LEFT OUTER JOIN bird f2 ON (f2.id=n.female2_id)
LEFT OUTER JOIN bird f3 ON (f3.id=n.female3_id)
LEFT OUTER JOIN cv_term l ON (n.location_id=l.id)
;

CREATE OR REPLACE VIEW nest_event_vw AS
SELECT ne.id          AS id
      ,ne.number      AS number
      ,n.name         AS name
      ,s.display_name AS status
      ,u.name         AS user
      ,CASE WHEN LENGTH(u.last) THEN CONCAT_WS(", ",u.last,u.first) ELSE NULL END AS username
      ,ne.notes       AS notes
      ,ne.event_date  AS event_date
FROM nest_event ne
JOIN nest n ON (n.id=ne.nest_id)
JOIN cv_term s ON (s.cv_id=getCvId("nest_status",NULL) AND s.id=ne.status_id)
JOIN user u ON (u.id= ne.user_id)
;

CREATE OR REPLACE VIEW session_vw AS
SELECT s.id
       ,s.name
       ,cv.display_name AS cv
       ,cvt.display_name AS type
       ,b.name AS bird
       ,u.name AS user
       ,s.notes
       ,s.create_date
FROM session s
JOIN cv_term cvt ON (s.type_id=cvt.id)
JOIN cv cv ON (cvt.cv_id=cv.id)
JOIN bird b ON (s.bird_id=b.id)
JOIN user u ON (u.id=s.user_id)
;

CREATE OR REPLACE VIEW score_vw AS
SELECT s.id
       ,ss.id AS session_id
       ,ss.name AS session
       ,cv.display_name AS cv
       ,cvt.display_name AS type
       ,b.name AS bird
       ,s.value
       ,u.name AS user
       ,s.create_date
FROM score s
JOIN session ss ON (s.session_id=ss.id)
JOIN cv_term cvt ON (s.type_id=cvt.id)
JOIN cv cv ON (cvt.cv_id=cv.id)
JOIN bird b ON (ss.bird_id=b.id)
JOIN user u ON (u.id=ss.user_id)
;

CREATE OR REPLACE VIEW state_vw AS
SELECT s.id
       ,ss.id AS session_id
       ,ss.name AS session
       ,b.name AS bird
       ,marker
       ,state
       ,s.create_date
FROM state s
JOIN session ss ON (s.session_id=ss.id)
JOIN bird b ON (ss.bird_id=b.id)
;

DROP TABLE IF EXISTS phenotype_state_mv;
CREATE TABLE phenotype_state_mv (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `type` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `marker` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `state` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `svalues` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `count` int(10) unsigned,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=60 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;
  
CREATE OR REPLACE VIEW phenotype_state_build_vw AS
SELECT c.display_name AS type
       ,marker
       ,state
       ,GROUP_CONCAT(value) AS svalues
       ,COUNT(1) AS count
FROM state st
JOIN session ss1 ON (st.session_id=ss1.id)
JOIN score sc
JOIN cv_term c ON (sc.type_id=c.id)
JOIN session ss2 ON (sc.session_id=ss2.id AND ss1.bird_id=ss2.bird_id)
group by 1,2,3
;

CREATE OR REPLACE VIEW user_vw AS
SELECT u.name
      ,first
      ,last
      ,janelia_id
      ,email
      ,organization
      ,GROUP_CONCAT(p.name) AS permissions
FROM user_permission up
LEFT OUTER JOIN cv_term p ON (p.cv_id=getCvId("permission",NULL) AND p.id=up.permission_id)
RIGHT OUTER JOIN user u ON (u.id=up.user_id)
GROUP BY name
;

CREATE OR REPLACE VIEW user_permission_vw AS
SELECT u.name AS name
      ,p.name AS permission
FROM user_permission up
JOIN user u ON (u.id=up.user_id)
LEFT OUTER JOIN cv_term p ON (p.cv_id=getCvId("permission",NULL) AND p.id=up.permission_id)
;
