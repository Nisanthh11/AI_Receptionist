CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE TABLE conversations (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    session_token VARCHAR(64) NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_conversations PRIMARY KEY (id), 
    CONSTRAINT uq_conversations_session_token UNIQUE (session_token)
);

CREATE TABLE departments (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    name VARCHAR(100) NOT NULL, 
    description TEXT, 
    location VARCHAR(150), 
    phone VARCHAR(30), 
    working_hours VARCHAR(150), 
    is_active BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_departments PRIMARY KEY (id), 
    CONSTRAINT uq_departments_name UNIQUE (name)
);

CREATE TABLE faqs (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    question VARCHAR(300) NOT NULL, 
    answer TEXT NOT NULL, 
    keywords VARCHAR(500), 
    category VARCHAR(80), 
    is_active BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_faqs PRIMARY KEY (id)
);

CREATE INDEX ix_faqs_category ON faqs (category);

CREATE TABLE organization_info (
    `key` VARCHAR(60) NOT NULL, 
    value TEXT NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_organization_info PRIMARY KEY (`key`)
);

CREATE TABLE roles (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    name VARCHAR(30) NOT NULL, 
    description VARCHAR(255), 
    CONSTRAINT pk_roles PRIMARY KEY (id), 
    CONSTRAINT uq_roles_name UNIQUE (name)
);

CREATE TABLE visitors (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    full_name VARCHAR(100) NOT NULL, 
    phone VARCHAR(20) NOT NULL, 
    email VARCHAR(255), 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_visitors PRIMARY KEY (id)
);

CREATE INDEX ix_visitors_phone_name ON visitors (phone, full_name);

CREATE TABLE messages (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    conversation_id INTEGER NOT NULL, 
    sender VARCHAR(20) NOT NULL, 
    content TEXT NOT NULL, 
    intent VARCHAR(40), 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_messages PRIMARY KEY (id), 
    CONSTRAINT ck_messages_sender_valid CHECK (sender IN ('visitor','receptionist')), 
    CONSTRAINT fk_messages_conversation_id_conversations FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);

CREATE TABLE staff (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    department_id INTEGER NOT NULL, 
    full_name VARCHAR(100) NOT NULL, 
    designation VARCHAR(100), 
    email VARCHAR(255), 
    is_active BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_staff PRIMARY KEY (id), 
    CONSTRAINT fk_staff_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT
);

CREATE INDEX ix_staff_department_id ON staff (department_id);

CREATE TABLE users (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    email VARCHAR(255) NOT NULL, 
    full_name VARCHAR(100) NOT NULL, 
    hashed_password VARCHAR(255) NOT NULL, 
    role_id INTEGER NOT NULL, 
    is_active BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    last_login_at DATETIME, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT fk_users_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE appointments (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    reference_code VARCHAR(20) NOT NULL, 
    visitor_id INTEGER NOT NULL, 
    staff_id INTEGER NOT NULL, 
    department_id INTEGER NOT NULL, 
    start_at DATETIME NOT NULL, 
    end_at DATETIME NOT NULL, 
    purpose VARCHAR(255) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    notes TEXT, 
    cancelled_reason VARCHAR(255), 
    slot_key VARCHAR(40), 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_appointments PRIMARY KEY (id), 
    CONSTRAINT ck_appointments_status_valid CHECK (status IN ('pending','confirmed','completed','cancelled')), 
    CONSTRAINT ck_appointments_time_order CHECK (end_at > start_at), 
    CONSTRAINT fk_appointments_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointments_staff_id_staff FOREIGN KEY(staff_id) REFERENCES staff (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointments_visitor_id_visitors FOREIGN KEY(visitor_id) REFERENCES visitors (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_appointments_reference_code UNIQUE (reference_code), 
    CONSTRAINT uq_appointments_slot_key UNIQUE (slot_key)
);

CREATE INDEX ix_appointments_department_id ON appointments (department_id);

CREATE INDEX ix_appointments_staff_start ON appointments (staff_id, start_at);

CREATE INDEX ix_appointments_start_at ON appointments (start_at);

CREATE INDEX ix_appointments_status ON appointments (status);

CREATE INDEX ix_appointments_visitor_id ON appointments (visitor_id);

CREATE TABLE staff_availability (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    staff_id INTEGER NOT NULL, 
    weekday SMALLINT NOT NULL, 
    start_time TIME NOT NULL, 
    end_time TIME NOT NULL, 
    CONSTRAINT pk_staff_availability PRIMARY KEY (id), 
    CONSTRAINT ck_staff_availability_window_order CHECK (end_time > start_time), 
    CONSTRAINT ck_staff_availability_weekday_range CHECK (weekday BETWEEN 0 AND 6), 
    CONSTRAINT fk_staff_availability_staff_id_staff FOREIGN KEY(staff_id) REFERENCES staff (id) ON DELETE CASCADE, 
    CONSTRAINT staff_window UNIQUE (staff_id, weekday, start_time)
);

CREATE INDEX ix_staff_availability_staff_id ON staff_availability (staff_id);

CREATE TABLE notifications (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    type VARCHAR(40) NOT NULL, 
    message VARCHAR(255) NOT NULL, 
    channel VARCHAR(20) NOT NULL, 
    appointment_id INTEGER, 
    is_read BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_notifications PRIMARY KEY (id), 
    CONSTRAINT fk_notifications_appointment_id_appointments FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
);

CREATE INDEX ix_notifications_created_at ON notifications (created_at);

CREATE TABLE visit_logs (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    reference_code VARCHAR(20) NOT NULL, 
    visitor_id INTEGER NOT NULL, 
    staff_id INTEGER, 
    appointment_id INTEGER, 
    purpose VARCHAR(255) NOT NULL, 
    registered_at DATETIME NOT NULL, 
    check_in_at DATETIME, 
    check_out_at DATETIME, 
    checked_in_by INTEGER, 
    checked_out_by INTEGER, 
    CONSTRAINT pk_visit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_visit_logs_appointment_id_appointments FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL, 
    CONSTRAINT fk_visit_logs_checked_in_by_users FOREIGN KEY(checked_in_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_visit_logs_checked_out_by_users FOREIGN KEY(checked_out_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_visit_logs_staff_id_staff FOREIGN KEY(staff_id) REFERENCES staff (id) ON DELETE SET NULL, 
    CONSTRAINT fk_visit_logs_visitor_id_visitors FOREIGN KEY(visitor_id) REFERENCES visitors (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_visit_logs_reference_code UNIQUE (reference_code)
);

CREATE INDEX ix_visit_logs_check_in_at ON visit_logs (check_in_at);

CREATE INDEX ix_visit_logs_visitor_id ON visit_logs (visitor_id);

INSERT INTO alembic_version (version_num) VALUES ('0001');

