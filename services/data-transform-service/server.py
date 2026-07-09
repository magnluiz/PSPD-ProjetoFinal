"""
Data Transform Service
------------------------
Converts raw clinical rows into HL7/FHIR resources, applying the redaction
rules for each access_level (FULL / PARTIAL / ANONYMIZED / AGGREGATED),
and computes aggregated statistics for the AGGREGATED level.
"""
import hashlib
import json
import logging
import os
from concurrent import futures

import grpc
from prometheus_client import Counter, Histogram, start_http_server

import hospital_pb2
import hospital_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [transform] %(message)s")
log = logging.getLogger(__name__)

REQUEST_COUNT = Counter(
    "transform_requests_total", "Total requests handled", ["method", "access_level"]
)
REQUEST_LATENCY = Histogram(
    "transform_request_latency_seconds", "Request latency in seconds", ["method"]
)


def _age_bracket_from_birthdate(birth_date_str):
    import datetime

    try:
        bd = datetime.date.fromisoformat(birth_date_str)
    except ValueError:
        return "unknown"
    today = datetime.date.today()
    age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    if age < 18:
        return "0-17"
    if age < 40:
        return "18-39"
    if age < 60:
        return "40-59"
    return "60+"


def _pseudonymize(patient_id: str) -> str:
    return "hash" + hashlib.sha256(patient_id.encode()).hexdigest()[:8]


def redact_patient(patient, access_level: str) -> dict:
    """Apply the redaction rules per access_level and return a plain dict
    (easier to serialize to FHIR from here)."""
    base = {
        "patient_id": patient.patient_id,
        "gender": patient.gender,
        "conditions": list(patient.conditions),
        "observations": list(patient.observations),
        "medications": list(patient.medications),
        "encounters": list(patient.encounters),
    }

    if access_level == "FULL":
        base.update(
            {
                "full_name": patient.full_name,
                "birth_date": patient.birth_date,
                "city": patient.city,
                "state": patient.state,
                "cpf": patient.cpf,
                "cns": patient.cns,
            }
        )
    elif access_level == "PARTIAL":
        initials = "".join(p[0] for p in patient.full_name.split() if p)[:3]
        base.update(
            {
                "full_name": initials,
                "birth_year": patient.birth_date[:4] if patient.birth_date else "",
                "city": patient.city,
                "state": patient.state,
                # CPF, CNS, endereço completo, telefone removidos
            }
        )
    elif access_level == "ANONYMIZED":
        base.update(
            {
                "patient_id": _pseudonymize(patient.patient_id),
                "age_bracket": _age_bracket_from_birthdate(patient.birth_date),
                "state": patient.state,
                # nome, CPF, CNS, cidade, data de nascimento exata removidos
            }
        )
    else:
        raise ValueError(f"redact_patient called with non-per-patient level: {access_level}")

    return base


def to_fhir_patient(patient, access_level: str) -> dict:
    redacted = redact_patient(patient, access_level)
    resource = {"resourceType": "Patient", "id": redacted["patient_id"]}
    if "full_name" in redacted:
        resource["name"] = [{"text": redacted["full_name"]}]
    if "birth_date" in redacted:
        resource["birthDate"] = redacted["birth_date"]
    elif "birth_year" in redacted:
        resource["birthDate"] = redacted["birth_year"]
    resource["gender"] = redacted["gender"]
    if redacted.get("city") or redacted.get("state"):
        resource["address"] = [
            {"city": redacted.get("city", ""), "state": redacted.get("state", "")}
        ]
    if "age_bracket" in redacted:
        resource["extension"] = [
            {"url": "age-bracket", "valueString": redacted["age_bracket"]}
        ]
    return resource


def to_fhir_condition(patient_id, event) -> dict:
    return {
        "resourceType": "Condition",
        "id": str(event.evento_id),
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"text": event.codigo_evento},
        "recordedDate": event.data_evento,
        "note": [{"text": event.descricao}] if event.descricao else [],
    }


def to_fhir_encounter(patient_id, encounter) -> dict:
    resource = {
        "resourceType": "Encounter",
        "id": str(encounter.encounter_id),
        "subject": {"reference": f"Patient/{patient_id}"},
        "class": {"code": encounter.tipo_atendimento or "unknown"},
        "serviceType": {"text": encounter.setor},
        "period": {"start": encounter.data_inicio},
    }
    if encounter.data_fim:
        resource["period"]["end"] = encounter.data_fim
    return resource


def to_fhir_observation(patient_id, event) -> dict:
    return {
        "resourceType": "Observation",
        "id": str(event.evento_id),
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"text": event.codigo_evento},
        "effectiveDateTime": event.data_evento,
        "valueQuantity": {"value": event.valor, "unit": event.unidade},
    }


def to_fhir_medication_request(patient_id, event) -> dict:
    return {
        "resourceType": "MedicationRequest",
        "id": str(event.evento_id),
        "subject": {"reference": f"Patient/{patient_id}"},
        "medicationCodeableConcept": {"text": event.codigo_evento},
        "authoredOn": event.data_evento,
        "dosageInstruction": [{"text": event.descricao}] if event.descricao else [],
    }


def to_fhir_bundle_for_patient(patient, access_level: str) -> list:
    """Builds the full set of FHIR resources for one patient at the given
    access level. Returns [] for AGGREGATED (handled separately)."""
    if access_level == "AGGREGATED":
        return []

    redacted_id = redact_patient(patient, access_level)["patient_id"]
    resources = [to_fhir_patient(patient, access_level)]
    for e in patient.encounters:
        resources.append(to_fhir_encounter(redacted_id, e))
    for c in patient.conditions:
        resources.append(to_fhir_condition(redacted_id, c))
    for o in patient.observations:
        resources.append(to_fhir_observation(redacted_id, o))
    for m in patient.medications:
        resources.append(to_fhir_medication_request(redacted_id, m))
    return resources


class DataTransformServicer(hospital_pb2_grpc.DataTransformServiceServicer):
    def ToFHIRPatient(self, request, context):
        with REQUEST_LATENCY.labels("ToFHIRPatient").time():
            REQUEST_COUNT.labels("ToFHIRPatient", request.access_level).inc()
            resource = to_fhir_patient(request.patient, request.access_level)
            return hospital_pb2.FHIRResource(
                resource_type="Patient", json_payload=json.dumps(resource, ensure_ascii=False)
            )

    def ToFHIRBundle(self, request, context):
        with REQUEST_LATENCY.labels("ToFHIRBundle").time():
            REQUEST_COUNT.labels("ToFHIRBundle", request.access_level).inc()
            entries = []
            for patient in request.patients:
                for resource in to_fhir_bundle_for_patient(patient, request.access_level):
                    entries.append(
                        hospital_pb2.FHIRResource(
                            resource_type=resource["resourceType"],
                            json_payload=json.dumps(resource, ensure_ascii=False),
                        )
                    )
            return hospital_pb2.FHIRBundle(entries=entries)

    def Aggregate(self, request, context):
        # Delegates to the same distribution logic used by PatientDataService
        # for consistency; kept here too so DataTransformService can also
        # aggregate cohorts it received directly (e.g. via streaming).
        with REQUEST_LATENCY.labels("Aggregate").time():
            REQUEST_COUNT.labels("Aggregate", "AGGREGATED").inc()
            patients = request.patients
            total = len(patients)
            if total == 0:
                return hospital_pb2.AggregatedStatsResponse(total_patients=0)

            genders = [p.gender for p in patients]
            gender_dist = _dist(genders)

            ages = [_age_bracket_from_birthdate(p.birth_date) for p in patients]
            age_dist = _dist(ages)

            depts = [e.setor for p in patients for e in p.encounters if e.setor]
            dept_dist = _dist(depts)

            values_by_code = {}
            for p in patients:
                for o in p.observations:
                    values_by_code.setdefault(o.codigo_evento, []).append(o.valor)
            avg_values = {
                k: round(sum(v) / len(v), 2) for k, v in values_by_code.items() if v
            }

            return hospital_pb2.AggregatedStatsResponse(
                total_patients=total,
                gender_distribution=gender_dist,
                age_distribution=age_dist,
                department_distribution=dept_dist,
                avg_values=avg_values,
            )

    def CollectFHIRBundle(self, request_iterator, context):
        """Client streaming: gateway streams TransformRequests (e.g. as they
        arrive from PatientDataService.StreamCohortData); we collect them
        all and return one consolidated FHIRBundle at the end."""
        entries = []
        access_level = None
        for req in request_iterator:
            access_level = req.access_level
            REQUEST_COUNT.labels("CollectFHIRBundle", access_level).inc()
            for resource in to_fhir_bundle_for_patient(req.patient, access_level):
                entries.append(
                    hospital_pb2.FHIRResource(
                        resource_type=resource["resourceType"],
                        json_payload=json.dumps(resource, ensure_ascii=False),
                    )
                )
        return hospital_pb2.FHIRBundle(entries=entries)

    def TransformPipeline(self, request_iterator, context):
        """Bidirectional streaming: transforms and yields each patient's FHIR
        resources as soon as raw data arrives, instead of waiting for the
        whole cohort. This keeps the cohort exams endpoint streaming while
        still returning clinical resources, not only Patient."""
        for req in request_iterator:
            REQUEST_COUNT.labels("TransformPipeline", req.access_level).inc()
            for resource in to_fhir_bundle_for_patient(req.patient, req.access_level):
                yield hospital_pb2.FHIRResource(
                    resource_type=resource["resourceType"],
                    json_payload=json.dumps(resource, ensure_ascii=False),
                )


def _dist(values):
    if not values:
        return {}
    total = len(values)
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return {k: round(v / total, 4) for k, v in counts.items()}


def serve():
    port = os.environ.get("GRPC_PORT", "50053")
    metrics_port = int(os.environ.get("METRICS_PORT", "9102"))
    start_http_server(metrics_port)
    log.info(f"Prometheus metrics exposed on :{metrics_port}/metrics")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    hospital_pb2_grpc.add_DataTransformServiceServicer_to_server(
        DataTransformServicer(), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    log.info(f"DataTransformService listening on :{port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
