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

MEDICOS = ["med.cardoso", "med.souza", "med.lima", "med.alves", "med.rocha"]
ESTAGIARIOS = ["est.silva", "est.pereira", "est.costa", "est.santos", "est.oliveira"]
PESQUISADORES = ["pesq.franca", "pesq.dias", "pesq.moura"]

SETORES = ["Cardiologia", "Endocrinologia", "Pediatria", "Ambulatorio Geral", "Emergencia"]
TIPOS_ATENDIMENTO = ["Ambulatorial", "Emergencia", "Internacao", "Retorno"]

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
    for p in patients:
        for _ in range(random.randint(1, 4)):
            start = fake.date_time_between(start_date="-2y", end_date="now")
            end = start + timedelta(hours=random.randint(1, 48))
            rows.append(
                {
                    "patient_id": p["patient_id"],
                    "data_inicio": start,
                    "data_fim": end,
                    "tipo_atendimento": random.choice(TIPOS_ATENDIMENTO),
                    "setor": random.choice(SETORES),
                }
            )
    return rows


def gen_clinical_events(patients):
    rows = []
    for p in patients:
        # each patient has a 55% chance per condition of having it (gives
        # decently sized, overlapping cohorts for research queries)
        conditions_for_patient = [c for c in CONDICOES if random.random() < 0.35]
        for c in conditions_for_patient:
            rows.append(
                {
                    "patient_id": p["patient_id"],
                    "tipo_evento": "Condicao",
                    "codigo_evento": c,
                    "descricao": f"Diagnostico de {c}",
                    "data_evento": fake.date_time_between(start_date="-2y", end_date="now"),
                    "valor": None,
                    "unidade": None,
                }
            )
        for _ in range(random.randint(1, 3)):
            code = random.choice(list(OBSERVACOES.keys()))
            unit, lo, hi = OBSERVACOES[code]
            rows.append(
                {
                    "patient_id": p["patient_id"],
                    "tipo_evento": "Observacao",
                    "codigo_evento": code,
                    "descricao": "",
                    "data_evento": fake.date_time_between(start_date="-1y", end_date="now"),
                    "valor": round(random.uniform(lo, hi), 2),
                    "unidade": unit,
                }
            )
        if conditions_for_patient:
            for _ in range(random.randint(1, 2)):
                rows.append(
                    {
                        "patient_id": p["patient_id"],
                        "tipo_evento": "Medicacao",
                        "codigo_evento": random.choice(MEDICAMENTOS),
                        "descricao": "Uso continuo",
                        "data_evento": fake.date_time_between(start_date="-1y", end_date="now"),
                        "valor": None,
                        "unidade": None,
                    }
                )
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
                "username_cuidador": medico,
                "patient_id": p["patient_id"],
                "tipo_vinculo": "medico",
                "username_supervisor": None,
                "status": "ativo",
            }
        )
        if p["patient_id"] == "P000010":
            estagiario = "est.silva"
        elif random.random() < 0.6:
            estagiario = random.choice(ESTAGIARIOS)
        else:
            estagiario = None
        if estagiario:
            rows.append(
                {
                    "username_cuidador": estagiario,
                    "patient_id": p["patient_id"],
                    "tipo_vinculo": "estagiario",
                    "username_supervisor": medico,
                    "status": "ativo",
                }
            )
    return rows


def gen_projects():
    rows = [
        {
            "titulo": "Estudo sobre Depressao - pesq.franca",
            "username_pesquisador": "pesq.franca",
            "codigo_condicao": "Depressao",
            "status": "Aprovado",
            "data_validade": date.today() + timedelta(days=255),
        },
        {
            "titulo": "Estudo sobre Hipertensao - pesq.franca",
            "username_pesquisador": "pesq.franca",
            "codigo_condicao": "Hipertensao",
            "status": "Aprovado",
            "data_validade": date.today() + timedelta(days=160),
        },
        {
            "titulo": "Estudo sobre Hipertensao - pesq.dias",
            "username_pesquisador": "pesq.dias",
            "codigo_condicao": "Hipertensao",
            "status": "Suspenso",
            "data_validade": date.today() + timedelta(days=345),
        },
    ]
    for pesq in PESQUISADORES:
        for _ in range(1):
            rows.append(
                {
                    "titulo": f"Estudo sobre {random.choice(CONDICOES)} - {pesq}",
                    "username_pesquisador": pesq,
                    "codigo_condicao": random.choice(CONDICOES),
                    "status": random.choices(["Aprovado", "Expirado", "Suspenso"], weights=[80, 10, 10])[0],
                    "data_validade": date.today() + timedelta(days=random.randint(-30, 365)),
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
    lines.append(",\n".join(values) + ";")
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
    events = gen_clinical_events(patients)
    assignments = gen_assignments(patients)
    projects = gen_projects()

    sql = "-- Auto-generated seed data. Do not edit by hand; regenerate with seed.py\n\n"
    sql += to_sql("patients", patients, ["patient_id", "full_name", "birth_date", "gender", "city", "state", "cpf", "cns"])
    sql += to_sql("encounters", encounters, ["patient_id", "data_inicio", "data_fim", "tipo_atendimento", "setor"])
    sql += to_sql("clinical_events", events, ["patient_id", "tipo_evento", "codigo_evento", "descricao", "data_evento", "valor", "unidade"])
    sql += to_sql("user_patient_assignments", assignments, ["username_cuidador", "patient_id", "tipo_vinculo", "username_supervisor", "status"])
    sql += to_sql("projects", projects, ["titulo", "username_pesquisador", "codigo_condicao", "status", "data_validade"])

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(sql)

    print(f"Generated {len(patients)} patients, {len(encounters)} encounters, "
          f"{len(events)} clinical events, {len(assignments)} assignments, "
          f"{len(projects)} projects -> {args.out}")


if __name__ == "__main__":
    main()
