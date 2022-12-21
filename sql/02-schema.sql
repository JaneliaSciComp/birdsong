SET FOREIGN_KEY_CHECKS=0;
--
-- Table structure for table `cv`
--
DROP TABLE IF EXISTS `cv`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `cv` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `definition` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `version` tinyint(3) unsigned NOT NULL,
  `is_current` tinyint(3) unsigned NOT NULL,
  `display_name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `cv_name_uk_ind` (`name`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=60 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;


--
-- Table structure for table `cv_term`
--
DROP TABLE IF EXISTS `cv_term`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `cv_term` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `cv_id` int(10) unsigned NOT NULL,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `definition` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `is_current` tinyint(3) unsigned NOT NULL,
  `display_name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `data_type` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `cv_term_name_uk_ind` (`cv_id`,`name`) USING BTREE,
  KEY `cv_term_cv_id_fk_ind` (`cv_id`) USING BTREE,
  CONSTRAINT `cv_term_cv_id_fk` FOREIGN KEY (`cv_id`) REFERENCES `cv` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1822 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `cv_relationship`
--
DROP TABLE IF EXISTS `cv_relationship`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `cv_relationship` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `type_id` int(10) unsigned NOT NULL,
  `subject_id` int(10) unsigned NOT NULL,
  `object_id` int(10) unsigned NOT NULL,
  `is_current` tinyint(3) unsigned NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `cv_relationship_uk_ind` (`type_id`,`subject_id`,`object_id`) USING BTREE,
  KEY `cv_relationship_type_id_fk_ind` (`type_id`) USING BTREE,
  KEY `cv_relationship_subject_id_fk_ind` (`subject_id`) USING BTREE,
  KEY `cv_relationship_object_id_fk_ind` (`object_id`) USING BTREE,
  CONSTRAINT `cv_relationship_subject_id_fk` FOREIGN KEY (`subject_id`) REFERENCES `cv` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `cv_relationship_object_id_fk` FOREIGN KEY (`object_id`) REFERENCES `cv` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `cv_relationship_type_id_fk` FOREIGN KEY (`type_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=22 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `cv_term_relationship`
--
DROP TABLE IF EXISTS `cv_term_relationship`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `cv_term_relationship` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `type_id` int(10) unsigned NOT NULL,
  `subject_id` int(10) unsigned NOT NULL,
  `object_id` int(10) unsigned NOT NULL,
  `is_current` tinyint(3) unsigned NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `cv_term_relationship_uk_ind` (`type_id`,`subject_id`,`object_id`) USING BTREE,
  KEY `cv_term_relationship_type_id_fk_ind` (`type_id`) USING BTREE,
  KEY `cv_term_relationship_subject_id_fk_ind` (`subject_id`) USING BTREE,
  KEY `cv_term_relationship_object_id_fk_ind` (`object_id`) USING BTREE,
  CONSTRAINT `cv_term_relationship_type_id_fk` FOREIGN KEY (`type_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `cv_term_relationship_object_id_fk` FOREIGN KEY (`object_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `cv_term_relationship_subject_id_fk` FOREIGN KEY (`subject_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `species`
--
DROP TABLE IF EXISTS `species`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `species` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `common_name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `genus` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `species` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `taxonomy_id` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `code` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `species_common_name_key_uk_ind` (`common_name`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bird`
--
DROP TABLE IF EXISTS `bird`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `bird` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `species_id` int(10) unsigned NOT NULL,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `band` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `nest_id` int(10) unsigned,
  `birth_nest_id` int(10) unsigned,
  `vendor_id` int(10) unsigned DEFAULT NULL,
  `clutch_id` int(10) unsigned,
  `location_id` int(10) unsigned NOT NULL,
  `user_id` int(10) unsigned,
  `sex` varchar(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `alive` tinyint(3) unsigned NOT NULL,
  `update_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `hatch_early` timestamp,
  `hatch_late` timestamp,
  `death_date` timestamp,
  PRIMARY KEY (`id`),
  UNIQUE KEY `bird_name_key_uk_ind` (`name`) USING BTREE,
  CONSTRAINT `bird_species_id_fk` FOREIGN KEY (`species_id`) REFERENCES `species` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_nest_id_fk` FOREIGN KEY (`nest_id`) REFERENCES `nest` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_birth_nest_id_fk` FOREIGN KEY (`birth_nest_id`) REFERENCES `nest` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_clutch_id_fk` FOREIGN KEY (`clutch_id`) REFERENCES `clutch` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_location_id_fk` FOREIGN KEY (`location_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_user_id_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bird_property`
--
DROP TABLE IF EXISTS `bird_property`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `bird_property` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `bird_id` int(10) unsigned NOT NULL,
  `type_id` int(10) unsigned NOT NULL,
  `value` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `bird_property_type_uk_ind` (`type_id`,`bird_id`) USING BTREE,
  KEY `bird_property_line_id_fk_ind` (`bird_id`) USING BTREE,
  KEY `bird_property_type_id_fk_ind` (`type_id`) USING BTREE,
  CONSTRAINT `bird_property_bird_id_fk` FOREIGN KEY (`bird_id`) REFERENCES `bird` (`id`) ON DELETE CASCADE ON UPDATE NO ACTION,
  CONSTRAINT `bird_property_type_id_fk` FOREIGN KEY (`type_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=64766 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bird_tutor`
--
DROP TABLE IF EXISTS `bird_tutor`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `bird_tutor` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `bird_id` int(10) unsigned NOT NULL,
  `type` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `tutor_id` int(10) unsigned DEFAULT NULL,
  `computer_id` int(10) unsigned DEFAULT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `bird_tutor_id_uk_ind` (`id`) USING BTREE,
  CONSTRAINT `bird_tutor_bird_id_fk` FOREIGN KEY (`bird_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_tutor_tutor_id_fk` FOREIGN KEY (`tutor_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_tutor_computer_id_fk` FOREIGN KEY (`computer_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bird_relationship`
--
DROP TABLE IF EXISTS `bird_relationship`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `bird_relationship` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `type_id` int(10) unsigned NOT NULL,
  `subject_id` int(10) unsigned NOT NULL,
  `object_id` int(10) unsigned NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `bird_relationship_id_uk_ind` (`id`) USING BTREE,
  CONSTRAINT `bird_relationship_type_id_fk` FOREIGN KEY (`type_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_relationship_subject_id_fk` FOREIGN KEY (`subject_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_relationship_object_id_fk` FOREIGN KEY (`object_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bird_comparison`
--
DROP TABLE IF EXISTS `bird_comparison`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `bird_comparison` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `bird1_id` int(10) unsigned NOT NULL,
  `bird1_session_id` int(10) unsigned NOT NULL,
  `comparison_id` int(10) unsigned NOT NULL,
  `bird2_id` int(10) unsigned NOT NULL,
  `bird2_session_id` int(10) unsigned NOT NULL,
  `value` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `bird_comparison_uk_ind` (`bird1_id`,`bird1_session_id`,`comparison_id`,`bird2_id`,`bird2_session_id`) USING BTREE,
  KEY `bird_comparison_id_uk_ind` (`id`) USING BTREE,
  CONSTRAINT `bird_comparison_type_id_fk` FOREIGN KEY (`comparison_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_comparison_bird1_id_fk` FOREIGN KEY (`bird1_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_comparison_bird1_session_id_fk` FOREIGN KEY (`bird1_session_id`) REFERENCES `session` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_comparison_bird2_id_fk` FOREIGN KEY (`bird2_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_comparison_bird2_session_id_fk` FOREIGN KEY (`bird2_session_id`) REFERENCES `session` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for naterialized view `bird_comparison_summary_mv`
--
DROP TABLE IF EXISTS bird_comparison_summary_mv;
CREATE TABLE bird_comparison_summary_mv (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `comparison` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `relationship` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `cnt` int(10) unsigned,
  `mean` decimal(12,8),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=60 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for naterialized view `bird_count_summary_mv`
--
DROP TABLE IF EXISTS bird_count_summary_mv;
CREATE TABLE bird_count_summary_mv (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `comparison` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `cnt` int(10) unsigned,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=60 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bird_event`
--
DROP TABLE IF EXISTS `bird_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `bird_event` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `bird_id` int(10) unsigned NOT NULL,
  `nest_id` int(10) unsigned DEFAULT NULL,
  `location_id` int(10) unsigned DEFAULT NULL,
  `status_id` int(10) unsigned NOT NULL,
  `terminal` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `user_id` int(10) unsigned NOT NULL,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `event_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `bird_event_bird_id_uk_ind` (`bird_id`) USING BTREE,
  CONSTRAINT `bird_event_bird_id_fk` FOREIGN KEY (`bird_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_event_nest_id_fk` FOREIGN KEY (`nest_id`) REFERENCES `nest` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_event_location_id_fk` FOREIGN KEY (`location_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_event_status_id_fk` FOREIGN KEY (`status_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `bird_event_user_id_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `clutch`
--
DROP TABLE IF EXISTS `clutch`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `clutch` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `nest_id` int(10) unsigned NOT NULL,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `clutch_early` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `clutch_late` timestamp,
  PRIMARY KEY (`id`),
  UNIQUE KEY `clutch_name_key_uk_ind` (`name`) USING BTREE,
  CONSTRAINT `clutch_nest_id_fk` FOREIGN KEY (`nest_id`) REFERENCES `nest` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `nest`
--
DROP TABLE IF EXISTS `nest`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `nest` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `band` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `sire_id` int(10) unsigned NULL,
  `damsel_id` int(10) unsigned NULL,
  `female1_id` int(10) unsigned NULL,
  `female2_id` int(10) unsigned NULL,
  `female3_id` int(10) unsigned NULL,
  `location_id` int(10) unsigned NOT NULL,
  `active` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `breeding` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `fostering` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `tutoring` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `nest_name_key_uk_ind` (`name`) USING BTREE,
  CONSTRAINT `nest_sire_id_fk` FOREIGN KEY (`sire_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `nest_damsel_id_fk` FOREIGN KEY (`damsel_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `nest_location_id_fk` FOREIGN KEY (`location_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `nest_event`
--
DROP TABLE IF EXISTS `nest_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `nest_event` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `number` int(10) unsigned,
  `nest_id` int(10) unsigned NOT NULL,
  `status_id` int(10) unsigned NOT NULL,
  `user_id` int(10) unsigned NOT NULL,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `event_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `nest_event_nest_id_uk_ind` (`nest_id`) USING BTREE,
  CONSTRAINT `nest_event_nest_id_fk` FOREIGN KEY (`nest_id`) REFERENCES `nest` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `nest_event_status_id_fk` FOREIGN KEY (`status_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `nest_event_user_id_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `claim`
--
DROP TABLE IF EXISTS `claim`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `claim` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `bird_id` int(10) unsigned NOT NULL,
  `user_id` int(10) unsigned NOT NULL,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `claim_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `claim_bird_id_fk` FOREIGN KEY (`bird_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `claim_user_id_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `session`
--
DROP TABLE IF EXISTS `session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `session` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `type_id` int(10) unsigned NOT NULL,
  `bird_id` int(10) unsigned NOT NULL,
  `user_id` int(10) unsigned NOT NULL,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `session_type_id_fk` FOREIGN KEY (`type_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `session_bird_id_fk` FOREIGN KEY (`bird_id`) REFERENCES `bird` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `session_user_id_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `score`
--
DROP TABLE IF EXISTS `score`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `score` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `session_id` int(10) unsigned NOT NULL,
  `type_id` int(10) unsigned NOT NULL,
  `value` varchar(256) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `score_session_id_fk` FOREIGN KEY (`session_id`) REFERENCES `session` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `score_type_id_fk` FOREIGN KEY (`type_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `state`
--
DROP TABLE IF EXISTS `state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `state` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `session_id` int(10) unsigned NOT NULL,
  `marker` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `state` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `state_session_id_fk` FOREIGN KEY (`session_id`) REFERENCES `session` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for naterialized view `phenotype_state_mv`
--
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

--
-- Table structure for table `user`
--
DROP TABLE IF EXISTS `user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user` ( 
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `first` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `last` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `janelia_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `email` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `organization` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `active` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_name_uk_ind` (`name`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user_permission`
--
DROP TABLE IF EXISTS `user_permission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_permission` ( 
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `user_id` int(10) unsigned NOT NULL,
  `permission_id` int(10) unsigned NOT NULL,
  `create_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_permission_uk_ind` (`user_id`,`permission_id`) USING BTREE,
  CONSTRAINT `user_permission_user_id_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `user_permission_permission_id_fk` FOREIGN KEY (`permission_id`) REFERENCES `cv_term` (`id`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB AUTO_INCREMENT=1001 DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

SET FOREIGN_KEY_CHECKS=0;
