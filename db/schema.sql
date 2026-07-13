-- Hospital pseudo-prontuario schema.
-- Mirrors the schema provided for each group in the shared course database.

CREATE TABLE IF NOT EXISTS patients (
    patient_id VARCHAR(10) PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL,
    birth_date DATE NOT NULL,
    gender VARCHAR(10) NOT NULL CHECK (gender IN ('male', 'female')),
    city VARCHAR(100) NOT NULL,
    state CHAR(2) NOT NULL,
    cpf VARCHAR(14) NOT NULL UNIQUE,
    cns VARCHAR(20) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS encounters (
    encounter_id VARCHAR(20) PRIMARY KEY,
    patient_id VARCHAR(10) NOT NULL REFERENCES patients(patient_id),
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP,
    encounter_type VARCHAR(50) NOT NULL CHECK (
        encounter_type IN ('AMBULATORIAL', 'EMERGENCY', 'INPATIENT', 'ICU', 'FOLLOW_UP', 'TELEHEALTH')
    ),
    department VARCHAR(50) NOT NULL CHECK (
        department IN (
            'CARDIOLOGY', 'ENDOCRINOLOGY', 'NEPHROLOGY', 'PULMONOLOGY',
            'INTERNAL_MEDICINE', 'EMERGENCY', 'ICU', 'PEDIATRICS',
            'GERIATRICS', 'INFECTIOUS_DISEASES', 'SURGERY', 'OBSTETRICS',
            'ORTHOPEDICS', 'ONCOLOGY', 'TELEMEDICINE'
        )
    )
);

CREATE TABLE IF NOT EXISTS clinical_events (
    event_id VARCHAR(20) PRIMARY KEY,
    patient_id VARCHAR(10) NOT NULL REFERENCES patients(patient_id),
    encounter_id VARCHAR(20) NOT NULL REFERENCES encounters(encounter_id),
    event_type VARCHAR(20) NOT NULL CHECK (
        event_type IN ('CONDITION', 'OBSERVATION', 'MEDICATION')
    ),
    code VARCHAR(50) NOT NULL,
    description VARCHAR(255) NOT NULL,
    value VARCHAR(50),
    unit VARCHAR(20),
    event_date TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS user_patient_assignments (
    assignment_id VARCHAR(30) PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    patient_id VARCHAR(10) NOT NULL REFERENCES patients(patient_id),
    assignment_type VARCHAR(20) NOT NULL CHECK (
        assignment_type IN ('ATTENDING', 'TRAINEE')
    ),
    supervisor_username VARCHAR(50),
    active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS projects (
    project_id VARCHAR(20) PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    researcher_username VARCHAR(50) NOT NULL,
    target_condition_code VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (
        status IN ('APPROVED', 'PENDING', 'EXPIRED', 'REJECTED', 'SUSPENDED')
    ),
    valid_until DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_encounters_patient ON encounters(patient_id);
CREATE INDEX IF NOT EXISTS idx_events_patient ON clinical_events(patient_id);
CREATE INDEX IF NOT EXISTS idx_events_code ON clinical_events(code);
CREATE INDEX IF NOT EXISTS idx_events_cohort ON clinical_events(code, event_type, patient_id);
CREATE INDEX IF NOT EXISTS idx_assignments_user ON user_patient_assignments(username);
CREATE INDEX IF NOT EXISTS idx_assignments_patient ON user_patient_assignments(patient_id);
CREATE INDEX IF NOT EXISTS idx_assignments_access
    ON user_patient_assignments(username, patient_id, assignment_type, active);
CREATE INDEX IF NOT EXISTS idx_projects_researcher ON projects(researcher_username);
CREATE INDEX IF NOT EXISTS idx_projects_access
    ON projects(project_id, researcher_username, status, valid_until);
