-- ============= --
-- Create Users  --
-- ============= --
-- CREATE USER 'birdAdmin'@'%' IDENTIFIED WITH mysql_native_password BY 'birdAdmin'; --
DROP USER IF EXISTS birdAdmin;
CREATE USER 'birdAdmin'@'%' IDENTIFIED BY '**********';
DROP USER IF EXISTS birdApp;
CREATE USER 'birdApp'@'%' IDENTIFIED BY '**********';
DROP USER IF EXISTS birdRead;
CREATE USER 'birdRead'@'%' IDENTIFIED BY '**********';

-- ====================== --
-- Apply User Privileges
-- ====================== --

GRANT ALL PRIVILEGES ON *.* TO birdAdmin@'%' WITH GRANT OPTION;
GRANT SUPER ON *.* TO birdAdmin@'%' WITH GRANT OPTION;
GRANT SELECT,INSERT,UPDATE,DELETE,EXECUTE,SHOW VIEW ON *.* TO birdApp@'%';
GRANT SELECT,SHOW VIEW,EXECUTE ON *.* TO birdRead@'%';
