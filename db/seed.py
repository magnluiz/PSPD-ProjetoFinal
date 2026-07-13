"""
Seed data generator for the hospital pseudo-prontuário database.

Usage:
    python seed.py --patients 500 --out seed.sql

Generates deterministic (seeded) synthetic data:
  - 5 médicos, 5 estagiários (each supervised by one médico)
  - 3 pesquisadores, with stable approved/suspended projects for repeatable tests
  - N patients, each assigned to a médico (and ~60% also to an estagiário)
  - 1-4 encounters per patient
  - 2-6 clinical_events per patient (mix of Condicao/Observacao/Medicacao),
    weighted so cohorts for Diabetes/Hipertensao/Obesidade are non-trivial
"""
import argparse
import random
from datetime import date, timedelta

try:
    from faker import Faker

    fake = Faker("pt_BR")
    HAS_FAKER = True
except ModuleNotFoundError:
    HAS_FAKER = False

    class SimpleFake:
        first_names = [
            "Ana", "Bruno", "Carla", "Daniel", "Eduarda", "Felipe", "Gabriela",
            "Henrique", "Isabela", "Joao", "Larissa", "Marcos", "Natalia",
            "Paulo", "Renata", "Sofia", "Tiago", "Vanessa",
        ]
        last_names = [
            "Silva", "Souza", "Oliveira", "Santos", "Pereira", "Costa",
            "Almeida", "Ferreira", "Rodrigues", "Gomes",
        ]
        cities = ["Brasilia", "Goiania", "Sao Paulo", "Belo Horizonte", "Salvador"]

        def name(self):
            return f"{random.choice(self.first_names)} {random.choice(self.last_names)}"

        def city(self):
            return random.choice(self.cities)

        def cpf(self):
            digits = "".join(random.choices("0123456789", k=11))
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

        def date_of_birth(self, minimum_age=1, maximum_age=95):
            today = date.today()
            age = random.randint(minimum_age, maximum_age)
            days_offset = random.randint(0, 364)
            return today - timedelta(days=age * 365 + days_offset)

        def date_time_between(self, start_date="-1y", end_date="now"):
            import datetime

            years = 1
            if isinstance(start_date, str) and start_date.endswith("y"):
                years = abs(int(start_date[:-1]))
            start = datetime.datetime.now() - datetime.timedelta(days=365 * years)
            end = datetime.datetime.now()
            delta = end - start
            return start + datetime.timedelta(seconds=random.randint(0, int(delta.total_seconds())))

    fake = SimpleFake()

MEDICOS = ["med.cardoso", "med.lima", "med.almeida", "med.rocha", "med.monteiro"]
ESTAGIARIOS = ["est.ferreira", "est.gomes", "est.costa", "est.melo", "est.dias"]
PESQUISADORES = ["pes.mendes", "pes.araujo", "pes.silveira"]

SETORES = [
    "CARDIOLOGY", "ENDOCRINOLOGY", "NEPHROLOGY", "PULMONOLOGY",
    "INTERNAL_MEDICINE", "EMERGENCY", "ICU", "PEDIATRICS", "GERIATRICS",
]
TIPOS_ATENDIMENTO = ["AMBULATORIAL", "EMERGENCY", "INPATIENT", "ICU", "FOLLOW_UP", "TELEHEALTH"]

CONDICOES = ["Diabetes", "Hipertensao", "Obesidade", "Asma", "Depressao"]
OBSERVACOES = {
    "HbA1c": ("%", 4.5, 12.0),
    "Glicemia": ("mg/dL", 70, 300),
    "PressaoSistolica": ("mmHg", 90, 190),
    "IMC": ("kg/m2", 18, 45),
    "Creatinina": ("mg/dL", 0.5, 3.0),
}
MEDICAMENTOS = ["Metformina 850mg", "Losartana 50mg", "Insulina NPH", "Sinvastatina 20mg", "Enalapril 10mg"]

STATES = ["DF", "GO", "SP", "MG", "BA"]


def esc(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def gen_patients(n):
    rows = []
    for i in range(1, n + 1):
        pid = f"P{i:06d}"
        rows.append(
            {
                "patient_id": pid,
                "full_name": fake.name(),
                "birth_date": fake.date_of_birth(minimum_age=1, maximum_age=95),
                "gender": random.choice(["male", "female"]),
                "city": fake.city(),
                "state": random.choice(STATES),
                "cpf": fake.cpf(),
                "cns": "".join(random.choices("0123456789", k=15)),
            }
        )
    return rows


def gen_encounters(patients):
    rows = []
    encounter_number = 1
    for p in patients:
        for _ in range(random.randint(1, 4)):
            start = fake.date_time_between(start_date="-2y", end_date="now")
            end = start + timedelta(hours=random.randint(1, 48))
            rows.append(
                {
                    "encounter_id": f"E{encounter_number:07d}",
                    "patient_id": p["patient_id"],
                    "start_date": start,
                    "end_date": end,
                    "encounter_type": random.choice(TIPOS_ATENDIMENTO),
                    "department": random.choice(SETORES),
                }
            )
            encounter_number += 1
    return rows


def gen_clinical_events(patients, encounters):
    rows = []
    event_number = 1
    encounters_by_patient = {}
    for encounter in encounters:
        encounters_by_patient.setdefault(encounter["patient_id"], []).append(encounter)
    for p in patients:
        # each patient has a 55% chance per condition of having it (gives
        # decently sized, overlapping cohorts for research queries)
        conditions_for_patient = [c for c in CONDICOES if random.random() < 0.35]
        for c in conditions_for_patient:
            rows.append(
                {
                    "event_id": f"EV{event_number:07d}",
                    "patient_id": p["patient_id"],
                    "encounter_id": random.choice(encounters_by_patient[p["patient_id"]])["encounter_id"],
                    "event_type": "CONDITION",
                    "code": c,
                    "description": f"Diagnostico de {c}",
                    "event_date": fake.date_time_between(start_date="-2y", end_date="now"),
                    "value": None,
                    "unit": None,
                }
            )
            event_number += 1
        for _ in range(random.randint(1, 3)):
            code = random.choice(list(OBSERVACOES.keys()))
            unit, lo, hi = OBSERVACOES[code]
            rows.append(
                {
                    "event_id": f"EV{event_number:07d}",
                    "patient_id": p["patient_id"],
                    "encounter_id": random.choice(encounters_by_patient[p["patient_id"]])["encounter_id"],
                    "event_type": "OBSERVATION",
                    "code": code,
                    "description": f"Resultado de {code}",
                    "event_date": fake.date_time_between(start_date="-1y", end_date="now"),
                    "value": str(round(random.uniform(lo, hi), 2)),
                    "unit": unit,
                }
            )
            event_number += 1
        if conditions_for_patient:
            for _ in range(random.randint(1, 2)):
                rows.append(
                    {
                        "event_id": f"EV{event_number:07d}",
                        "patient_id": p["patient_id"],
                        "encounter_id": random.choice(encounters_by_patient[p["patient_id"]])["encounter_id"],
                        "event_type": "MEDICATION",
                        "code": random.choice(MEDICAMENTOS),
                        "description": "Uso continuo",
                        "event_date": fake.date_time_between(start_date="-1y", end_date="now"),
                        "value": None,
                        "unit": None,
                    }
                )
                event_number += 1
    return rows


def gen_assignments(patients):
    rows = []
    for p in patients:
        if p["patient_id"] == "P000001":
            medico = "med.cardoso"
        else:
            medico = random.choice(MEDICOS)
        rows.append(
            {
                "assignment_id": f"A-MED-{p['patient_id']}",
                "username": medico,
                "patient_id": p["patient_id"],
                "assignment_type": "ATTENDING",
                "supervisor_username": None,
                "active": True,
            }
        )
        if p["patient_id"] == "P000010":
            estagiario = "est.ferreira"
        elif random.random() < 0.6:
            estagiario = random.choice(ESTAGIARIOS)
        else:
            estagiario = None
        if estagiario:
            rows.append(
                {
                    "assignment_id": f"A-EST-{p['patient_id']}",
                    "username": estagiario,
                    "patient_id": p["patient_id"],
                    "assignment_type": "TRAINEE",
                    "supervisor_username": medico,
                    "active": True,
                }
            )
    return rows


def gen_projects():
    rows = [
        {
            "project_id": "PRJ01",
            "title": "Estudo sobre Depressao - pes.mendes",
            "researcher_username": "pes.mendes",
            "target_condition_code": "Depressao",
            "status": "APPROVED",
            "valid_until": date.today() + timedelta(days=255),
        },
        {
            "project_id": "PRJ02",
            "title": "Estudo sobre Hipertensao - pes.mendes",
            "researcher_username": "pes.mendes",
            "target_condition_code": "Hipertensao",
            "status": "APPROVED",
            "valid_until": date.today() + timedelta(days=160),
        },
        {
            "project_id": "PRJ03",
            "title": "Estudo sobre Hipertensao - pes.araujo",
            "researcher_username": "pes.araujo",
            "target_condition_code": "Hipertensao",
            "status": "SUSPENDED",
            "valid_until": date.today() + timedelta(days=345),
        },
    ]
    for index, pesq in enumerate(PESQUISADORES, start=4):
        for _ in range(1):
            rows.append(
                {
                    "project_id": f"PRJ{index:02d}",
                    "title": f"Estudo clinico - {pesq}",
                    "researcher_username": pesq,
                    "target_condition_code": random.choice(CONDICOES),
                    "status": random.choices(["APPROVED", "EXPIRED", "SUSPENDED"], weights=[80, 10, 10])[0],
                    "valid_until": date.today() + timedelta(days=random.randint(-30, 365)),
                }
            )
    return rows


def to_sql(table, rows, cols):
    if not rows:
        return ""
    lines = [f"INSERT INTO {table} ({', '.join(cols)}) VALUES"]
    values = []
    for r in rows:
        vals = []
        for c in cols:
            v = r[c]
            if v is None:
                vals.append("NULL")
            elif isinstance(v, (int, float)):
                vals.append(str(v))
            else:
                vals.append(esc(v))
        values.append("(" + ", ".join(vals) + ")")
    lines.append(",\n".join(values) + " ON CONFLICT DO NOTHING;")
    return "\n".join(lines) + "\n\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="seed.sql")
    args = ap.parse_args()

    random.seed(args.seed)
    if HAS_FAKER:
        Faker.seed(args.seed)

    patients = gen_patients(args.patients)
    encounters = gen_encounters(patients)
    events = gen_clinical_events(patients, encounters)
    assignments = gen_assignments(patients)
    projects = gen_projects()

    sql = "-- Auto-generated seed data. Do not edit by hand; regenerate with seed.py\n\n"
    sql += to_sql("patients", patients, ["patient_id", "full_name", "birth_date", "gender", "city", "state", "cpf", "cns"])
    sql += to_sql("encounters", encounters, ["encounter_id", "patient_id", "start_date", "end_date", "encounter_type", "department"])
    sql += to_sql("clinical_events", events, ["event_id", "patient_id", "encounter_id", "event_type", "code", "description", "value", "unit", "event_date"])
    sql += to_sql("user_patient_assignments", assignments, ["assignment_id", "username", "patient_id", "assignment_type", "supervisor_username", "active"])
    sql += to_sql("projects", projects, ["project_id", "title", "researcher_username", "target_condition_code", "status", "valid_until"])

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(sql)

    print(f"Generated {len(patients)} patients, {len(encounters)} encounters, "
          f"{len(events)} clinical events, {len(assignments)} assignments, "
          f"{len(projects)} projects -> {args.out}")


if __name__ == "__main__":
    main()
