# LexiValidate

Web app for native-speaker validation of machine-generated Ewe lexicon entries.
An admin uploads a lexicon file, creates a project, and assigns annotators.
Each annotator gets a one-item-at-a-time card: English word, the machine's
Ewe translation, and four choices (correct / understandable / incorrect /
uncertain), plus an optional correction and comment. When annotators disagree
on an entry, it shows up on the admin's disagreements page for adjudication.
Everything can be exported to CSV.

## Setup

```
python -m venv venv
source venv/bin/activate      # venv\Scripts\activate on Windows
pip install -r requirements.txt
python seed.py
python app.py
```

Then open http://localhost:5000

The seed script creates:
- admin / changeme123
- annotator1 / changeme123
- a project called "Ewe Base Lexicon" loaded from data/base_lexicon.xlsx

Change both passwords once you've logged in (there's no self-service
password change yet - do it from a Python shell or add users through
Users > Add a user with new passwords instead of reusing these).

## How it works

- `models.py` - the database tables (User, Project, Entry, Assignment,
  Annotation, Adjudication)
- `lexparse.py` - reads an uploaded .xlsx/.csv and maps its columns onto
  our Entry fields, matching header names loosely so it isn't fussy about
  exact column naming
- `app.py` - all the routes: login, admin project/user management,
  the annotation view, disagreement + adjudication, CSV export, and a
  couple of read-only JSON endpoints under /api

## What's deliberately not here yet

- Self-service registration or password reset
- Per-entry assignment (right now assigning a user to a project gives them
  every entry in it, not a subset)
- Any offline/mobile packaging - out of scope for this phase, see the
  product roadmap doc
