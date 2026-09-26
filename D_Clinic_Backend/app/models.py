"""SQLAlchemy models mirroring Simple's public schema.

Table and column names follow simple-server
(https://simpledotorg.github.io/docs.simple/dbschema/public/) so that
integrating with a real Simple deployment is a mapping exercise. Only the
columns needed by this project are included.

Identity-bearing columns (full_name, phone number, street address) live here
because Simple stores them; they are never read by anything that builds a
model prompt (see ADR-0003).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    facility_type: Mapped[str | None] = mapped_column(String)  # PHC, CHC, District Hospital
    district: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String)
    facility_size: Mapped[str | None] = mapped_column(String)  # small, medium, large
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class User(Base):
    """Health workers and program staff (Simple `users`)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str | None] = mapped_column(String)  # nurse, counselor, medical_officer
    registration_facility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer)
    age_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String, nullable=False)  # female, male, transgender
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active, dead, migrated
    reminder_consent: Mapped[str] = mapped_column(String, nullable=False, default="granted")  # granted, denied
    registration_facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )
    assigned_facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )
    registration_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # registration time
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("index_patients_on_assigned_facility_id", "assigned_facility_id"),
        Index("index_patients_on_recorded_at", "recorded_at"),
    )


class PatientPhoneNumber(Base):
    __tablename__ = "patient_phone_numbers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    number: Mapped[str] = mapped_column(String, nullable=False)
    phone_type: Mapped[str] = mapped_column(String, nullable=False, default="mobile")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dnd_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("index_patient_phone_numbers_on_patient_id", "patient_id"),)


class Address(Base):
    """Simple `addresses`. `zone` is used here as a coarse distance band to the
    assigned facility (near / mid / far)."""

    __tablename__ = "addresses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    street_address: Mapped[str | None] = mapped_column(String)
    village_or_colony: Mapped[str | None] = mapped_column(String)
    district: Mapped[str | None] = mapped_column(String)
    zone: Mapped[str | None] = mapped_column(String)  # near, mid, far
    state: Mapped[str | None] = mapped_column(String)  # used ONLY for fairness audits
    country: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("index_addresses_on_patient_id", "patient_id"),)


class MedicalHistory(Base):
    __tablename__ = "medical_histories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    hypertension: Mapped[str] = mapped_column(String, nullable=False, default="yes")  # yes, no, unknown
    diabetes: Mapped[str] = mapped_column(String, nullable=False, default="no")
    prior_heart_attack: Mapped[str] = mapped_column(String, nullable=False, default="no")
    prior_stroke: Mapped[str] = mapped_column(String, nullable=False, default="no")
    chronic_kidney_disease: Mapped[str] = mapped_column(String, nullable=False, default="no")
    receiving_treatment_for_hypertension: Mapped[str] = mapped_column(String, nullable=False, default="yes")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("index_medical_histories_on_patient_id", "patient_id"),)


class BloodPressure(Base):
    __tablename__ = "blood_pressures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    systolic: Mapped[int] = mapped_column(Integer, nullable=False)
    diastolic: Mapped[int] = mapped_column(Integer, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("index_blood_pressures_on_patient_id_and_recorded_at", "patient_id", "recorded_at"),
        Index("index_blood_pressures_on_facility_id", "facility_id"),
        Index("index_blood_pressures_on_recorded_at", "recorded_at"),
    )


class BloodSugar(Base):
    __tablename__ = "blood_sugars"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    blood_sugar_type: Mapped[str] = mapped_column(String, nullable=False)  # random, fasting, post_prandial, hba1c
    blood_sugar_value: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("index_blood_sugars_on_patient_id_and_recorded_at", "patient_id", "recorded_at"),)


class PrescriptionDrug(Base):
    __tablename__ = "prescription_drugs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    rxnorm_code: Mapped[str | None] = mapped_column(String)
    dosage: Mapped[str | None] = mapped_column(String)  # e.g. "5 mg"
    frequency: Mapped[str | None] = mapped_column(String)  # OD, BD
    is_protocol_drug: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    device_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    device_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("index_prescription_drugs_on_patient_id", "patient_id"),)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    creation_facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # scheduled, visited, cancelled
    cancel_reason: Mapped[str | None] = mapped_column(String)  # not_responding, moved, dead, invalid_phone_number, ...
    remind_on: Mapped[date | None] = mapped_column(Date)
    agreed_to_visit: Mapped[bool | None] = mapped_column(Boolean)
    appointment_type: Mapped[str] = mapped_column(String, nullable=False, default="automatic")  # manual, automatic
    device_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # when the appointment was booked
    device_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("index_appointments_on_patient_id_and_scheduled_date", "patient_id", "scheduled_date"),
        Index("index_appointments_on_facility_id", "facility_id"),
        Index("index_appointments_on_scheduled_date", "scheduled_date"),
    )


class CallResult(Base):
    """Outcome of an overdue-patient call. Values follow Simple exactly."""

    __tablename__ = "call_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=False)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"))
    facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"))
    # agreed_to_visit | remind_to_call_later | removed_from_overdue_list
    result_type: Mapped[str] = mapped_column(String, nullable=False)
    # when removed: not_responding | moved | dead | invalid_phone_number | public_hospital_transfer |
    # moved_to_private | refused_to_return | other
    remove_reason: Mapped[str | None] = mapped_column(String)
    device_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    device_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("index_call_results_on_appointment_id", "appointment_id"),
        Index("index_call_results_patient_id_and_updated_at", "patient_id", "device_updated_at"),
    )


class Communication(Base):
    """SMS / call records. Simple stores delivery details in a separate table;
    here the message body and direction are kept inline for the MVP so the
    chatbot has training and evaluation data."""

    __tablename__ = "communications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("appointments.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    # sms | whatsapp | voip_call | missed_visit_sms_reminder | appointment_reminder
    communication_type: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)  # outbound, inbound
    body: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String)  # en, pcm (Pidgin), ha, yo
    delivery_status: Mapped[str | None] = mapped_column(String)  # queued, sent, delivered, failed, read
    device_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("index_communications_on_patient_id", "patient_id"),
        Index("index_communications_on_appointment_id", "appointment_id"),
    )
