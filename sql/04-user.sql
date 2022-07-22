-- ============= --
-- Create Users  --
-- ============= --
-- CREATE USER 'birdAdmin'@'%' IDENTIFIED WITH mysql_native_password BY 'birdAdmin'; --
DROP USER birdAdmin;
CREATE USER 'birdAdmin'@'%' IDENTIFIED BY 'birdAdmin';
DROP USER birdApp;
CREATE USER 'birdApp'@'%' IDENTIFIED BY 'birdApp';
DROP USER birdRead;
CREATE USER 'birdRead'@'%' IDENTIFIED BY 'birdRead';

-- ====================== --
-- Apply User Privileges
-- ====================== --

GRANT ALL PRIVILEGES ON birdsong.* TO birdAdmin@'%' WITH GRANT OPTION;
GRANT SUPER ON *.* TO birdAdmin@'%' WITH GRANT OPTION;
GRANT SELECT,INSERT,UPDATE,DELETE,EXECUTE,SHOW VIEW ON birdsong.* TO birdApp@'%';
GRANT SELECT,SHOW VIEW,EXECUTE ON birdsong.* TO birdRead@'%';
