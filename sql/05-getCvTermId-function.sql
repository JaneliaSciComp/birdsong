DROP FUNCTION IF EXISTS getCvTermId;
DELIMITER //
CREATE DEFINER = birdAdmin FUNCTION getCvTermId(context CHAR(255), term CHAR(255), definition CHAR(255))
RETURNS INT
DETERMINISTIC
BEGIN
  DECLARE v_cv_id int;
  DECLARE v_cv_term_id int;
  DECLARE v_relationship_id int;

   -- get cv id of cv passed in
  SELECT id FROM cv WHERE name = context AND is_current = 1 INTO v_cv_id;

   -- get cv_term id of term passed in for the cv passed in
  SELECT id FROM cv_term WHERE name = term AND cv_id = v_cv_id AND is_current = 1 INTO v_cv_term_id;

   -- get cv_term id of term passed in for the cv of the sub cv passed in
  IF v_cv_term_id is NULL THEN
    SELECT cv_term.id from cv_term, cv WHERE cv_term.name = 'is_sub_cv_of' AND cv.name = 'cv_relationship_types' AND cv_term.cv_id = cv.id INTO v_relationship_id;
    SELECT cv_term.id FROM cv_term, cv_relationship WHERE name = term AND cv_id = object_id AND subject_id = v_cv_id AND type_id = v_relationship_id AND cv_term.is_current = 1 INTO v_cv_term_id;
  END IF;

   -- get cv_term id of term passed in for the cv of the sub cv of the sub cv passed in
  IF v_cv_term_id is NULL THEN
    SELECT cv_term.id 
    FROM cv_term, cv_relationship 
    WHERE name = term
      AND cv_id = object_id 
      AND subject_id = (SELECT object_id FROM cv_relationship WHERE subject_id = v_cv_id AND type_id = v_relationship_id) 
      AND type_id = v_relationship_id 
      AND cv_term.is_current = 1 
     INTO v_cv_term_id;
  END IF;

  -- get cv_term for obsolete synonym passed in
  IF v_cv_term_id is NULL THEN
    SELECT cv_term.id from cv_term, cv WHERE cv_term.name = 'has_synonym' AND cv.name = 'obo' AND cv_term.cv_id = cv.id INTO v_relationship_id;
    select  id FROM cv_term WHERE name = term AND cv_id = v_cv_id AND is_current = 0 INTO v_cv_term_id;
    SELECT subject_id FROM cv_term_relationship WHERE object_id = v_cv_term_id AND type_id = v_relationship_id AND is_current = 1 INTO v_cv_term_id;
  END IF;

RETURN v_cv_term_id;

END//
DELIMITER ;
