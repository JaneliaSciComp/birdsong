mysql -h localhost -u root -proot <01-dbBuild.sql
echo "Creating tables"
mysql -h localhost -u root -proot birdsong <02-schema.sql 
echo "Adding users"
mysql -h localhost -u root -proot birdsong <03-user.sql 
echo "Defining functions"
mysql -h localhost -u root -proot birdsong <04-getCvId-function.sql 
mysql -h localhost -u root -proot birdsong <04-getCvTermDefinition-function.sql 
mysql -h localhost -u root -proot birdsong <04-getCvTermDisplayName-function.sql 
mysql -h localhost -u root -proot birdsong <04-getCvTermId-function.sql         
mysql -h localhost -u root -proot birdsong <04-getCvTermName-function.sql 
echo "Defining views"
mysql -h localhost -u root -proot birdsong <05-views.sql 
echo "Populating"
mysql -h localhost -u root -proot birdsong <99-initial_load.sql
