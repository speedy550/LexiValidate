from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

CHOICES = ["correct", "understandable", "incorrect", "uncertain"]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="annotator")  # admin | annotator | adjudicator
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw,method='pbkdf2:sha256')

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def is_admin(self):
        return self.role == "admin"


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    entries = db.relationship("Entry", backref="project", lazy=True, cascade="all, delete-orphan")
    assignments = db.relationship("Assignment", backref="project", lazy=True, cascade="all, delete-orphan")


class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    source_ref = db.Column(db.Integer)  # original row id from the uploaded lexicon, for traceability
    english = db.Column(db.String(300))
    french = db.Column(db.String(300))
    gpt_ewe = db.Column(db.String(500))
    gpt_twi = db.Column(db.String(500))
    confidence = db.Column(db.String(50))
    ai_sentiment = db.Column(db.String(50))
    ai_pos = db.Column(db.String(50))
    ai_comment = db.Column(db.String(500))

    annotations = db.relationship("Annotation", backref="entry", lazy=True, cascade="all, delete-orphan")
    adjudication = db.relationship("Adjudication", backref="entry", uselist=False, cascade="all, delete-orphan")


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("project_id", "user_id", name="uq_assignment"),)

    user = db.relationship("User")


class Annotation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("entry.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    choice = db.Column(db.String(20), nullable=False)
    correction = db.Column(db.String(500))
    comment = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("entry_id", "user_id", name="uq_annotation"),)

    user = db.relationship("User")


class Adjudication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("entry.id"), nullable=False, unique=True)
    adjudicator_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    final_choice = db.Column(db.String(20))
    final_translation = db.Column(db.String(500))
    note = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
