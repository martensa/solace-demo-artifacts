CREATE DATABASE "order_management" OWNER postgres;

\c order_management;

-- ============================================
-- PostgreSQL Order Management Demo Database
-- Generated: 2026-02-05T12:31:59.270983
-- ============================================

-- Drop tables if they exist (for clean re-runs)
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS payment_methods CASCADE;

-- ============================================
-- Table: categories
-- ============================================
CREATE TABLE categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- Table: products
-- ============================================
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(200) NOT NULL,
    description TEXT,
    category_id INTEGER REFERENCES categories(category_id),
    unit_price DECIMAL(10, 2) NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    sku VARCHAR(50) UNIQUE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- Table: customers
-- ============================================
CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    address_line1 VARCHAR(255),
    address_line2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    postal_code VARCHAR(20),
    country VARCHAR(100),
    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- ============================================
-- Table: payment_methods
-- ============================================
CREATE TABLE payment_methods (
    payment_method_id SERIAL PRIMARY KEY,
    method_name VARCHAR(50) NOT NULL,
    description TEXT
);

-- ============================================
-- Table: orders
-- ============================================
CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    payment_method_id INTEGER REFERENCES payment_methods(payment_method_id),
    status VARCHAR(50) DEFAULT 'pending',
    subtotal DECIMAL(10, 2) NOT NULL,
    tax_amount DECIMAL(10, 2) DEFAULT 0.00,
    shipping_cost DECIMAL(10, 2) DEFAULT 0.00,
    total_amount DECIMAL(10, 2) NOT NULL,
    shipping_address_line1 VARCHAR(255),
    shipping_address_line2 VARCHAR(255),
    shipping_city VARCHAR(100),
    shipping_state VARCHAR(100),
    shipping_postal_code VARCHAR(20),
    shipping_country VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- Table: order_items
-- ============================================
CREATE TABLE order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(10, 2) NOT NULL,
    discount_amount DECIMAL(10, 2) DEFAULT 0.00,
    line_total DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- Indexes for better query performance
-- ============================================
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);

-- ============================================
-- Sample Data
-- ============================================

-- Insert categories
INSERT INTO categories (category_name, description) VALUES
('Electronics', 'Electronic devices and accessories'),
('Clothing', 'Apparel and fashion items'),
('Books', 'Physical and digital books'),
('Home & Garden', 'Home improvement and garden supplies'),
('Sports & Outdoors', 'Sports equipment and outdoor gear');

-- Insert products
INSERT INTO products (product_name, description, category_id, unit_price, stock_quantity, sku) VALUES
('Wireless Headphones', 'Bluetooth 5.0 noise-cancelling headphones', 1, 79.99, 150, 'ELEC-HP-001'),
('Laptop Stand', 'Ergonomic aluminum laptop stand', 1, 34.99, 200, 'ELEC-LS-002'),
('Cotton T-Shirt', 'Comfortable 100% cotton t-shirt', 2, 19.99, 500, 'CLTH-TS-001'),
('Running Shoes', 'Professional running shoes with cushioning', 5, 89.99, 120, 'SPRT-SH-001'),
('Programming Guide', 'Complete guide to modern programming', 3, 45.00, 80, 'BOOK-PG-001'),
('Smart Watch', 'Fitness tracking smart watch', 1, 199.99, 75, 'ELEC-SW-003'),
('Garden Tools Set', '5-piece gardening tool set', 4, 29.99, 100, 'HOME-GT-001'),
('Yoga Mat', 'Non-slip exercise yoga mat', 5, 24.99, 250, 'SPRT-YM-002');

-- Insert customers
INSERT INTO customers (first_name, last_name, email, phone, address_line1, city, state, postal_code, country) VALUES
('John', 'Doe', 'john.doe@email.com', '+1-555-0101', '123 Main St', 'New York', 'NY', '10001', 'USA'),
('Jane', 'Smith', 'jane.smith@email.com', '+1-555-0102', '456 Oak Ave', 'Los Angeles', 'CA', '90001', 'USA'),
('Robert', 'Johnson', 'robert.j@email.com', '+1-555-0103', '789 Pine Rd', 'Chicago', 'IL', '60601', 'USA'),
('Emily', 'Williams', 'emily.w@email.com', '+1-555-0104', '321 Elm St', 'Houston', 'TX', '77001', 'USA'),
('Michael', 'Brown', 'michael.b@email.com', '+1-555-0105', '654 Maple Dr', 'Phoenix', 'AZ', '85001', 'USA');

-- Insert payment methods
INSERT INTO payment_methods (method_name, description) VALUES
('Credit Card', 'Payment via credit card'),
('PayPal', 'Payment via PayPal account'),
('Bank Transfer', 'Direct bank transfer'),
('Cash on Delivery', 'Pay when order is delivered');

-- Insert sample orders
INSERT INTO orders (customer_id, payment_method_id, status, subtotal, tax_amount, shipping_cost, total_amount, 
                   shipping_address_line1, shipping_city, shipping_state, shipping_postal_code, shipping_country) VALUES
(1, 1, 'completed', 79.99, 6.40, 5.00, 91.39, '123 Main St', 'New York', 'NY', '10001', 'USA'),
(2, 2, 'shipped', 164.98, 13.20, 0.00, 178.18, '456 Oak Ave', 'Los Angeles', 'CA', '90001', 'USA'),
(3, 1, 'processing', 45.00, 3.60, 3.99, 52.59, '789 Pine Rd', 'Chicago', 'IL', '60601', 'USA'),
(4, 3, 'completed', 139.97, 11.20, 7.50, 158.67, '321 Elm St', 'Houston', 'TX', '77001', 'USA'),
(5, 1, 'pending', 199.99, 16.00, 0.00, 215.99, '654 Maple Dr', 'Phoenix', 'AZ', '85001', 'USA');

-- Insert order items
INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount_amount, line_total) VALUES
(1, 1, 1, 79.99, 0.00, 79.99),
(2, 3, 2, 19.99, 0.00, 39.98),
(2, 7, 1, 29.99, 0.00, 29.99),
(2, 8, 4, 24.99, 0.00, 99.96),
(3, 5, 1, 45.00, 0.00, 45.00),
(4, 4, 1, 89.99, 0.00, 89.99),
(4, 8, 2, 24.99, 0.00, 49.98),
(5, 6, 1, 199.99, 0.00, 199.99);

-- ============================================
-- Useful Views
-- ============================================

-- View: Order summary with customer details
CREATE VIEW order_summary AS
SELECT 
    o.order_id,
    o.order_date,
    CONCAT(c.first_name, ' ', c.last_name) AS customer_name,
    c.email,
    o.status,
    o.total_amount,
    COUNT(oi.order_item_id) AS item_count
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
LEFT JOIN order_items oi ON o.order_id = oi.order_id
GROUP BY o.order_id, o.order_date, c.first_name, c.last_name, c.email, o.status, o.total_amount;

-- View: Product sales summary
CREATE VIEW product_sales_summary AS
SELECT 
    p.product_id,
    p.product_name,
    cat.category_name,
    SUM(oi.quantity) AS total_sold,
    SUM(oi.line_total) AS total_revenue,
    COUNT(DISTINCT oi.order_id) AS order_count
FROM products p
LEFT JOIN order_items oi ON p.product_id = oi.product_id
LEFT JOIN categories cat ON p.category_id = cat.category_id
GROUP BY p.product_id, p.product_name, cat.category_name;

-- ============================================
-- Useful Functions
-- ============================================

-- Function: Calculate customer lifetime value
CREATE OR REPLACE FUNCTION get_customer_lifetime_value(cust_id INTEGER)
RETURNS DECIMAL(10,2) AS $$
    SELECT COALESCE(SUM(total_amount), 0.00)
    FROM orders
    WHERE customer_id = cust_id AND status = 'completed';
$$ LANGUAGE SQL;

-- ============================================
-- Comments for documentation
-- ============================================
COMMENT ON TABLE categories IS 'Product categories for organizing inventory';
COMMENT ON TABLE products IS 'Product catalog with pricing and inventory information';
COMMENT ON TABLE customers IS 'Customer information and contact details';
COMMENT ON TABLE orders IS 'Order header information including totals and shipping';
COMMENT ON TABLE order_items IS 'Individual line items for each order';
COMMENT ON TABLE payment_methods IS 'Available payment methods';

-- ============================================
-- End of schema
-- ============================================
