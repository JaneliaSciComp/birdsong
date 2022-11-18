DROP FUNCTION IF EXISTS getCvTermName;
DELIMITER //
CREATE DEFINER = birdAdmin FUNCTION getCvTermName(term_id int)
RETURNS CHAR(255)
DETERMINISTIC
BEGIN
  DECLARE v_cv_term_name CHAR(255);

  SELECT name FROM cv_term WHERE id = term_id INTO v_cv_term_name;

RETURN v_cv_term_name;

END//
DELIMITER ;
