DROP FUNCTION IF EXISTS getCvTermDisplayName;
DELIMITER //
CREATE DEFINER = birdAdmin FUNCTION getCvTermDisplayName(term_id int)
RETURNS CHAR(255)
DETERMINISTIC
BEGIN
  DECLARE v_cv_term_display_name CHAR(255);

  SELECT display_name FROM cv_term WHERE id = term_id INTO v_cv_term_display_name;

RETURN v_cv_term_display_name;

END//
DELIMITER ;
