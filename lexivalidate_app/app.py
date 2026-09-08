import csv
import io
import os
from collections import Counter
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db, login_manager
from models import User, Project, Entry, Assignment, Annotation, Adjudication, CHOICES
from lexparse import parse_lexicon_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("LEXIVALIDATE_SECRET", "change-this-before-you-deploy")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "lexivalidate.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

db.init_app(app)
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if not current_user.is_admin():
            flash("Admins only.", "error")
            return redirect(url_for("dashboard"))
        return view(*a, **kw)
    return wrapped


# ---------- auth ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username", "").strip()).first()
        if u and u.check_password(request.form.get("password", "")):
            login_user(u)
            return redirect(url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    if current_user.is_admin():
        return redirect(url_for("admin_home"))
    my_projects = (
        db.session.query(Project)
        .join(Assignment, Assignment.project_id == Project.id)
        .filter(Assignment.user_id == current_user.id)
        .all()
    )
    progress = {}
    for p in my_projects:
        total = len(p.entries)
        done = Annotation.query.filter(
            Annotation.user_id == current_user.id,
            Annotation.entry_id.in_([e.id for e in p.entries]) if p.entries else False,
        ).count()
        progress[p.id] = (done, total)
    return render_template("annotator_home.html", projects=my_projects, progress=progress)


# ---------- admin ----------

@app.route("/admin")
@admin_required
def admin_home():
    projects = Project.query.order_by(Project.created_at.desc()).all()
    stats = {}
    for p in projects:
        total = len(p.entries)
        entry_ids = [e.id for e in p.entries]
        annotated_entries = (
            db.session.query(Annotation.entry_id).filter(Annotation.entry_id.in_(entry_ids)).distinct().count()
            if entry_ids else 0
        )
        stats[p.id] = {"total": total, "annotated": annotated_entries}
    return render_template("admin_dashboard.html", projects=projects, stats=stats)


@app.route("/admin/project/new", methods=["GET", "POST"])
@admin_required
def new_project():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        f = request.files.get("lexicon_file")
        if not name or not f or f.filename == "":
            flash("Give the project a name and pick a lexicon file.", "error")
            return redirect(url_for("new_project"))
        try:
            rows = parse_lexicon_file(f.filename, f.read())
        except Exception as exc:
            flash(f"Could not read that file: {exc}", "error")
            return redirect(url_for("new_project"))
        if not rows:
            flash("No usable rows found in that file - check the column headers.", "error")
            return redirect(url_for("new_project"))

        project = Project(name=name, description=description, created_by=current_user.id)
        db.session.add(project)
        db.session.flush()
        for r in rows:
            db.session.add(Entry(
                project_id=project.id,
                source_ref=r.get("source_ref"),
                english=r.get("english"),
                french=r.get("french"),
                gpt_ewe=r.get("gpt_ewe"),
                gpt_twi=r.get("gpt_twi"),
                confidence=r.get("confidence"),
                ai_sentiment=r.get("ai_sentiment"),
                ai_pos=r.get("ai_pos"),
                ai_comment=r.get("ai_comment"),
            ))
        db.session.commit()
        flash(f"Project created with {len(rows)} entries.", "ok")
        return redirect(url_for("project_detail", project_id=project.id))
    return render_template("new_project.html")


@app.route("/admin/project/<int:project_id>")
@admin_required
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    annotators = User.query.filter(User.role.in_(["annotator", "adjudicator"])).order_by(User.username).all()
    assigned_ids = {a.user_id for a in project.assignments}

    entry_ids = [e.id for e in project.entries]
    total = len(entry_ids)
    annotated = (
        db.session.query(Annotation.entry_id).filter(Annotation.entry_id.in_(entry_ids)).distinct().count()
        if entry_ids else 0
    )
    disagreements = count_disagreements(project)

    return render_template(
        "project_detail.html", project=project, annotators=annotators, assigned_ids=assigned_ids,
        total=total, annotated=annotated, disagreements=disagreements,
    )


@app.route("/admin/project/<int:project_id>/assign", methods=["POST"])
@admin_required
def assign_user(project_id):
    project = Project.query.get_or_404(project_id)
    user_id = int(request.form["user_id"])
    existing = Assignment.query.filter_by(project_id=project.id, user_id=user_id).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Assignment(project_id=project.id, user_id=user_id))
    db.session.commit()
    return redirect(url_for("project_detail", project_id=project.id))


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def manage_users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "annotator")
        if not username or not password:
            flash("Username and password are both required.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is taken.", "error")
        else:
            u = User(username=username, role=role)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash(f"Created account for {username}.", "ok")
        return redirect(url_for("manage_users"))
    users = User.query.order_by(User.role, User.username).all()
    return render_template("manage_users.html", users=users)


def count_disagreements(project):
    entry_ids = [e.id for e in project.entries]
    if not entry_ids:
        return 0
    rows = db.session.query(Annotation.entry_id, Annotation.choice).filter(
        Annotation.entry_id.in_(entry_ids)
    ).all()
    by_entry = {}
    for eid, choice in rows:
        by_entry.setdefault(eid, set()).add(choice)
    adjudicated = {a.entry_id for a in db.session.query(Adjudication.entry_id).filter(
        Adjudication.entry_id.in_(entry_ids)
    )}
    return sum(1 for eid, choices in by_entry.items() if len(choices) > 1 and eid not in adjudicated)


@app.route("/admin/project/<int:project_id>/disagreements")
@admin_required
def disagreements(project_id):
    project = Project.query.get_or_404(project_id)
    entry_ids = [e.id for e in project.entries]
    rows = db.session.query(Annotation.entry_id, Annotation.choice).filter(
        Annotation.entry_id.in_(entry_ids)
    ).all() if entry_ids else []
    by_entry = {}
    for eid, choice in rows:
        by_entry.setdefault(eid, set()).add(choice)
    adjudicated_ids = {a.entry_id for a in Adjudication.query.filter(Adjudication.entry_id.in_(entry_ids))} if entry_ids else set()
    flagged_ids = [eid for eid, choices in by_entry.items() if len(choices) > 1 and eid not in adjudicated_ids]
    flagged_entries = Entry.query.filter(Entry.id.in_(flagged_ids)).all() if flagged_ids else []
    return render_template("disagreements.html", project=project, entries=flagged_entries)


@app.route("/admin/project/<int:project_id>/adjudicate/<int:entry_id>", methods=["GET", "POST"])
@admin_required
def adjudicate(project_id, entry_id):
    project = Project.query.get_or_404(project_id)
    entry = Entry.query.get_or_404(entry_id)
    anns = Annotation.query.filter_by(entry_id=entry.id).all()

    if request.method == "POST":
        final_choice = request.form.get("final_choice")
        final_translation = request.form.get("final_translation", "").strip()
        note = request.form.get("note", "").strip()
        existing = Adjudication.query.filter_by(entry_id=entry.id).first()
        if existing:
            existing.final_choice = final_choice
            existing.final_translation = final_translation
            existing.note = note
            existing.adjudicator_id = current_user.id
        else:
            db.session.add(Adjudication(
                entry_id=entry.id, adjudicator_id=current_user.id,
                final_choice=final_choice, final_translation=final_translation, note=note,
            ))
        db.session.commit()
        flash("Adjudication saved.", "ok")
        return redirect(url_for("disagreements", project_id=project.id))

    return render_template("adjudicate.html", project=project, entry=entry, annotations=anns)


@app.route("/admin/project/<int:project_id>/export")
@admin_required
def export_project(project_id):
    project = Project.query.get_or_404(project_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "entry_id", "english", "french", "gpt_ewe", "gpt_twi",
        "annotator", "choice", "correction", "comment",
        "adjudicated_choice", "adjudicated_translation", "adjudication_note",
    ])
    for e in project.entries:
        adj = e.adjudication
        anns = e.annotations
        if not anns:
            writer.writerow([
                e.id, e.english, e.french, e.gpt_ewe, e.gpt_twi,
                "", "", "", "",
                adj.final_choice if adj else "", adj.final_translation if adj else "", adj.note if adj else "",
            ])
        for a in anns:
            writer.writerow([
                e.id, e.english, e.french, e.gpt_ewe, e.gpt_twi,
                a.user.username, a.choice, a.correction or "", a.comment or "",
                adj.final_choice if adj else "", adj.final_translation if adj else "", adj.note if adj else "",
            ])
    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f"attachment; filename=project_{project.id}_export.csv"
    return resp


# ---------- annotator ----------

@app.route("/annotate/<int:project_id>")
@login_required
def annotate(project_id):
    project = Project.query.get_or_404(project_id)
    assigned = Assignment.query.filter_by(project_id=project.id, user_id=current_user.id).first()
    if not assigned and not current_user.is_admin():
        flash("You're not assigned to this project.", "error")
        return redirect(url_for("dashboard"))

    done_ids = {a.entry_id for a in Annotation.query.filter_by(user_id=current_user.id)}
    next_entry = next((e for e in project.entries if e.id not in done_ids), None)
    total = len(project.entries)
    done_count = sum(1 for e in project.entries if e.id in done_ids)

    if next_entry is None:
        return render_template("annotate.html", project=project, entry=None, total=total, done_count=done_count)

    return render_template(
        "annotate.html", project=project, entry=next_entry, total=total, done_count=done_count,
        choices=CHOICES,
    )


@app.route("/annotate/<int:project_id>/entry/<int:entry_id>", methods=["POST"])
@login_required
def submit_annotation(project_id, entry_id):
    choice = request.form.get("choice")
    if choice not in CHOICES:
        flash("Pick one of the options first.", "error")
        return redirect(url_for("annotate", project_id=project_id))

    existing = Annotation.query.filter_by(entry_id=entry_id, user_id=current_user.id).first()
    correction = request.form.get("correction", "").strip()
    comment = request.form.get("comment", "").strip()
    if existing:
        existing.choice = choice
        existing.correction = correction
        existing.comment = comment
    else:
        db.session.add(Annotation(
            entry_id=entry_id, user_id=current_user.id,
            choice=choice, correction=correction, comment=comment,
        ))
    db.session.commit()
    return redirect(url_for("annotate", project_id=project_id))


# ---------- small read-only API, per the spec's "backend should expose an API" requirement ----------

@app.route("/api/projects")
@login_required
def api_projects():
    projects = Project.query.all()
    return jsonify([{"id": p.id, "name": p.name, "entries": len(p.entries)} for p in projects])


@app.route("/api/project/<int:project_id>/entries")
@login_required
def api_entries(project_id):
    project = Project.query.get_or_404(project_id)
    out = []
    for e in project.entries:
        out.append({
            "id": e.id, "english": e.english, "french": e.french,
            "gpt_ewe": e.gpt_ewe, "gpt_twi": e.gpt_twi,
            "annotations": [{"user": a.user.username, "choice": a.choice, "correction": a.correction}
                             for a in e.annotations],
        })
    return jsonify(out)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
