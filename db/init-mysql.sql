-- EC2 MySQL 초기 설정. root 로 한 번 실행한다. 비밀번호는 실행 전에 바꾼다.
--   sudo mysql < db/init-mysql.sql
CREATE DATABASE IF NOT EXISTS fitset_ml CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'fitset_ml'@'%' IDENTIFIED BY 'CHANGE-ME';
GRANT ALL PRIVILEGES ON fitset_ml.* TO 'fitset_ml'@'%';
FLUSH PRIVILEGES;
