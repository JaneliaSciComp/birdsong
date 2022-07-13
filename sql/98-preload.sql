SET FOREIGN_KEY_CHECKS=0;

--
-- Truncate tables
--
TRUNCATE TABLE bird;
TRUNCATE TABLE bird_event;
TRUNCATE TABLE bird_property;
TRUNCATE TABLE bird_relationship;
TRUNCATE TABLE claim;
TRUNCATE TABLE clutch;
TRUNCATE TABLE cv;
TRUNCATE TABLE cv_relationship;
TRUNCATE TABLE cv_term;
TRUNCATE TABLE cv_term_relationship;
TRUNCATE TABLE nest;
TRUNCATE TABLE nest_event;
TRUNCATE TABLE species;
TRUNCATE TABLE user;
TRUNCATE TABLE user_permission;

--
-- Relationship CV terms
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'schema','relationships defined in the schema','relationships defined in the schema');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('schema',''),1,'associated_with',NULL,NULL);

--
-- CV terms to populate from SQLite
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'location','Location','Location');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId("location",""),1,"UNKNOWN","UNKNOWN","UNKNOWN");

--
-- Color CV terms
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'color','Color','Color');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'pink','pk','#ffc0cb');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'black','bk','#000');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'white','wh','#fff');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'purple','pu','#a020f0');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'orange','or','#ffa500');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'blue','bu','#00f');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'green','gr','#0f0');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'red','rd','#f00');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'yellow','yw','#ff0');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'brown','br','#8b4513');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('color',''),1,'tut','tut','#fafad2');

--
-- Vendor CV terms
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'vendor','Vendor','Vendor');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('vendor',''),1,'magnolia','Magnolia','Magnolia');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('vendor',''),1,'bb','B&B','B&B');

--
-- Bird status CV terms
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'bird_status','Bird status','Bird status');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'hatched','Bird hatched in colony','Bird hatched in colony');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'acquired','Bird acquired from vendor','Bird acquired from vendor');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'claimed','Bird claimed','Bird claimed');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'unclaimed','Bird unclaimed','Bird unclaimed');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'banded','Bird banded','Bird banded');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'moved','Bird moved','Bird moved');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'procedure','Non-surgical procedure performed','Non-surgical procedure performed');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'surgery','Surgery performed','Surgery performed');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'died','Bird died','Bird died');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('bird_status',''),1,'euthanized','Bird euthanized','Bird euthanized');

--
-- Nest status CV terms
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'nest_status','Nest status','Nest status');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'fledged','Fledged','Fledged');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'found','Found','Found');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'transferred_from','Transferred from','Transferred from');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'fertilized','Fertilized','Fertilized');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'graduated','Graduated','Graduated');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'nest_cleaned','Nest cleaned','Nest cleaned');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'missing','Missing','Missing');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'hatched','Hatched','Hatched');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'discarded','Discarded','Discarded');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'found_dead','Found dead','Found dead');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'new_father','New father','New father');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'new_mother','New mother','New mother');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'transferred_to','Transferred to','Transferred to');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('nest_status',''),1,'NA','NA','NA');

--
-- Session CV terms
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'genotype','Genotype','Genotype');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('genotype',''),1,'allelic_state','Allelic state','Allelic state');
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'phenotype','Phenotype','Phenotype');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('phenotype',''),1,'median_tempo','Median song tempo','Median song tempo');

--
-- Permission CV terms
--
INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'permission','Permission','User permission');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId("permission",""),1,"admin","Administrator","Administrator");
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId("permission",""),1,"manager","Lab manager","Lab manager");
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId("permission",""),1,"edit","Edit birds","Edit birds");

--
-- Species
--
INSERT INTO species (common_name,genus,species,taxonomy_id,code) VALUES ("Bengalese finch","Lonchura","striata domestica","299123","BF");


--
-- Users
--
INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (31,'msb1066@gmail.com','Michael','Brainard','brainardm','msb@phy.ucsf.edu','SOO - UC San Francisco');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='brainardm'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (30,'adria@gmail.com','Adria','Arteseros','arteserosa','adriaa@phy.ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='arteserosa'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (10,'breeder@gmail.com','Breeder','Breeder','breeder','unknown@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='breeder'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (2,'bradley.colquitt@gmail.com','Bradley','Colquitt','colquittb','bradley.colquitt@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='colquittb'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (44,'cady.kurtzmiott@gmail.com','Cady','Kurtz-Miott','kurtzmiottc','unknown@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='kurtzmiottc'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (25,'no_login@gmail.com','David','Mets','metsd','dmets@phy.ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='metsd'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (39,'emily@gmail.com','Emily','Merfeld','emily','emily.merfeld@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='emily'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (23,'foad@gmail.com','Foad','Unknown','foad','foad@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='foad'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (36,'eszter@gmail.com','Eszter','Unknown','eszter','eszter@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='eszter'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (28,'w.hamish@gmail.com','Hamish','Mehaffey','mehaffeyw','hamish@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='mehaffeyw'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (40,'huangi@gmail.com','Issac','Huang','huangi','b20ihuang@berkeley.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='huangi'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (19,'joanne@gmail.com','Joanne','Unknown','joanne','joanne@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='joanne'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (41,'li.kelly97@gmail.com','Kelly','Li','lij7','li@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='lij7'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (38,'kurtis@gmail.com','Kurtis','Unknown','kurtis','kurtis@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='kurtis'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (29,'lena@gmail.com','Lena','Unknown','lena','lena@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='lena'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (18,'lucas@gmail.com','Lucas','Unknown','lucas','lucas@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='lucas'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (16,'mark@gmail.com','Mark','Miller','millerm12','millerm@phy.ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='millerm12'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (26,'paul@gmail.com','Paul','Unknown','paul','paul@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='paul'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (37,'robert@gmail.com','Robert','Veline','veliner','robert.veline@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='veliner'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (32,'sofia@gmail.com','Sofia','Unknown','sofia','sofia@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='sofia'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (45,'josh@gmail.com','Josh','Steighner','josh','josh@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='josh'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (24,'sooyoon@gmail.com','SooYoon','','sooyoon','sooyoon@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='sooyoon'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (id,name,first,last,janelia_id,email,organization) VALUES (5,'stim@gmail.com','Tim','','tim','tim@ucsf.edu','Dr. Michael Brainard Lab');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='tim'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (name,first,last,janelia_id,email,organization) VALUES ('robsvi@gmail.com','Rob','Svirskas','svirskasr','svirskasr@hhmi.org','Software Solutions');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),(SELECT id FROM cv_term WHERE name="admin" AND cv_id=getCVId("permission","")));
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

INSERT INTO user (name,first,last,janelia_id,email,organization) VALUES ('gowantervo@gmail.com','Gowan','Tervo','tervod','tervod@janelia.hhmi.org','Mechanistic Cognitive Neuroscience');
INSERT INTO user_permission (user_id,permission_id) VALUES ((SELECT id FROM user WHERE janelia_id='tervod'),(SELECT id FROM cv_term WHERE name="edit" AND cv_id=getCVId("permission","")));

SET FOREIGN_KEY_CHECKS=1;
