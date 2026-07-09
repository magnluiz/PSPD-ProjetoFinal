-- Hospital pseudo-prontuário schema
-- Matches the tables described in the PSPD project spec.

CREATE TABLE IF NOT EXISTS patients (
    patient_id      VARCHAR(10) PRIMARY KEY,
    full_name       VARCHAR(200) NOT NULL,
    birth_date      DATE NOT NULL,
    gender          VARCHAR(10) NOT NULL,
    city            VARCHAR(100),
    state           VARCHAR(2),
    cpf             VARCHAR(14),
    cns             VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS encounters (
    encounter_id    SERIAL PRIMARY KEY,
    patient_id      VARCHAR(10) REFERENCES patients(patient_id),
    data_inicio     TIMESTAMP NOT NULL,
    data_fim        TIMESTAMP,
    tipo_atendimento VARCHAR(50),
    setor           VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS clinical_events (
    evento_id       SERIAL PRIMARY KEY,
    patient_id      VARCHAR(10) REFERENCES patients(patient_id),
    encounter_id    INTEGER REFERENCES encounters(encounter_id),
    tipo_evento     VARCHAR(20) NOT NULL CHECK (tipo_evento IN ('Condicao','Observacao','Medicacao')),
    codigo_evento   VARCHAR(50) NOT NULL,
    descricao       TEXT,
    data_evento     TIMESTAMP NOT NULL,
    valor           NUMERIC,
    unidade         VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS user_patient_assignments (
    vinculo_id      SERIAL PRIMARY KEY,
    username_cuidador VARCHAR(50) NOT NULL,
    patient_id      VARCHAR(10) REFERENCES patients(patient_id),
    tipo_vinculo    VARCHAR(20) NOT NULL CHECK (tipo_vinculo IN ('medico','estagiario')),
    username_supervisor VARCHAR(50),
    status          VARCHAR(20) NOT NULL CHECK (status IN ('ativo','encerrado'))
);

CREATE TABLE IF NOT EXISTS projects (
    projeto_id      SERIAL PRIMARY KEY,
    titulo          VARCHAR(200),
    username_pesquisador VARCHAR(50) NOT NULL,
    codigo_condicao VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL CHECK (status IN ('Aprovado','Expirado','Suspenso')),
    data_validade   DATE
);

CREATE INDEX IF NOT EXISTS idx_encounters_patient ON encounters(patient_id);
CREATE INDEX IF NOT EXISTS idx_events_patient ON clinical_events(patient_id);
CREATE INDEX IF NOT EXISTS idx_events_codigo ON clinical_events(codigo_evento);
CREATE INDEX IF NOT EXISTS idx_upa_cuidador ON user_patient_assignments(username_cuidador);
CREATE INDEX IF NOT EXISTS idx_upa_patient ON user_patient_assignments(patient_id);
CREATE INDEX IF NOT EXISTS idx_projects_pesquisador ON projects(username_pesquisador);
