-- BarberTrack: full schema. Import this once in phpMyAdmin (Import tab).
CREATE DATABASE IF NOT EXISTS barbertrack CHARACTER SET utf8mb4;
USE barbertrack;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(120) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  photo VARCHAR(255) DEFAULT '',
  otp_hash VARCHAR(255) NULL,
  otp_expires DATETIME NULL,
  otp_attempts INT NOT NULL DEFAULT 0,
  failed_logins INT NOT NULL DEFAULT 0,
  locked_until DATETIME NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS barbers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  phone VARCHAR(30) DEFAULT '',
  commission_rate DECIMAL(5,2) NOT NULL DEFAULT 50.00
);

CREATE TABLE IF NOT EXISTS services (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  stock INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transactions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  barber_id INT NULL,
  service_id INT NULL,
  product_id INT NULL,
  product_qty INT NOT NULL DEFAULT 0,
  product_total DECIMAL(10,2) NOT NULL DEFAULT 0,
  customer_name VARCHAR(100) DEFAULT '',
  amount DECIMAL(10,2) NOT NULL,
  commission DECIMAL(10,2) NOT NULL,
  shop_share DECIMAL(10,2) NOT NULL,
  payment_method VARCHAR(20) NOT NULL DEFAULT 'Cash',
  txn_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (barber_id) REFERENCES barbers(id),
  FOREIGN KEY (service_id) REFERENCES services(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS queue_entries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  queue_date DATE NOT NULL,
  queue_no INT NOT NULL,
  customer_name VARCHAR(100) NOT NULL DEFAULT '',
  service_id INT NULL,
  barber_id INT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'Waiting',
  transaction_id INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_queue_day_no (queue_date, queue_no),
  FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE SET NULL,
  FOREIGN KEY (barber_id) REFERENCES barbers(id) ON DELETE SET NULL,
  FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE SET NULL
);
