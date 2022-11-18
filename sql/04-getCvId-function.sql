DROP FUNCTION IF EXISTS getCvId;
DELIMITER //
CREATE DEFINER = birdAdmin FUNCTION getCvId(context CHAR(255), definition CHAR(255))
RETURNS INT
DETERMINISTIC
BEGIN
  DECLARE v_cv_id int;

  SELECT id FROM cv WHERE name = context AND is_current = 1 INTO v_cv_id;

RETURN v_cv_id;

END//
DELIMITER ;
