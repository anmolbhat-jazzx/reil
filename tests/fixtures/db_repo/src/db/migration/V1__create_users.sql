CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    org_id INTEGER REFERENCES organizations(id),
    created_at TIMESTAMP DEFAULT now()
);
CREATE UNIQUE INDEX idx_users_email ON users (email);
