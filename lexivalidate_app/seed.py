"""Run once to set up the database: python seed.py
Creates the tables, an admin account, one sample annotator, and loads
data/base_lexicon.xlsx as a starter project so there's something to click through."""

import os
from app import app
from extensions import db
from models import User, Project, Entry
from lexparse import parse_lexicon_file

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "base_lexicon.xlsx")


def run():
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(username="admin").first():
            admin = User(username="admin", role="admin")
            admin.set_password("changeme123")
            db.session.add(admin)

        if not User.query.filter_by(username="annotator1").first():
            ann = User(username="annotator1", role="annotator")
            ann.set_password("changeme123")
            db.session.add(ann)

        db.session.commit()

        if Project.query.count() == 0 and os.path.exists(DATA_FILE):
            with open(DATA_FILE, "rb") as f:
                rows = parse_lexicon_file("base_lexicon.xlsx", f.read())
            project = Project(name="Ewe Base Lexicon", description="Imported from base_lexicon.xlsx")
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
            print(f"Loaded {len(rows)} entries into '{project.name}'.")
        else:
            print("Projects already exist or no data file found - skipping lexicon import.")

        print("Admin login: admin / changeme123")
        print("Annotator login: annotator1 / changeme123")
        print("Change both passwords after your first login.")


if __name__ == "__main__":
    run()
