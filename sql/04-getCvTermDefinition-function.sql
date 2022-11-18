DROP FUNCTION IF EXISTS getCvTermDefinition;
DELIMITER //
CREATE DEFINER = birdAdmin FUNCTION getCvTermDefinition(term_id int)
RETURNS CHAR(255)
DETERMINISTIC
BEGIN
  DECLARE v_cv_term_definition CHAR(255);

  SELECT definition FROM cv_term WHERE id = term_id INTO v_cv_term_definition;

RETURN v_cv_term_definition;

END//
DELIMITER ;
