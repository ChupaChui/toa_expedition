from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "expedition.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exception: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = sqlite3.connect(DATABASE)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            str_mod INTEGER NOT NULL DEFAULT 0,
            max_slots INTEGER NOT NULL DEFAULT 0,
            used_slots INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT ''
        )
        """
    )
    db.commit()
    db.close()


def get_member(member_id: int) -> sqlite3.Row:
    member = get_db().execute(
        "SELECT * FROM members WHERE id = ?", (member_id,)
    ).fetchone()
    if member is None:
        raise ValueError("Entry not found.")
    return member


@app.route("/")
def index() -> str:
    members = get_db().execute(
        """
        SELECT
            id,
            name,
            str_mod,
            max_slots,
            used_slots,
            note,
            max_slots - used_slots AS free_slots
        FROM members
        ORDER BY id DESC
        """
    ).fetchall()
    return render_template("index.html", members=members)


@app.route("/add", methods=["GET", "POST"])
def add_member() -> str:
    if request.method == "POST":
        form = parse_member_form(request.form)
        get_db().execute(
            """
            INSERT INTO members (name, str_mod, max_slots, used_slots, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                form["name"],
                form["str_mod"],
                form["max_slots"],
                form["used_slots"],
                form["note"],
            ),
        )
        get_db().commit()
        flash("Entry added.")
        return redirect(url_for("index"))
    return render_template("form.html", member=None, page_title="Add Entry")


@app.route("/edit/<int:member_id>", methods=["GET", "POST"])
def edit_member(member_id: int) -> str:
    member = get_member(member_id)
    if request.method == "POST":
        form = parse_member_form(request.form)
        get_db().execute(
            """
            UPDATE members
            SET name = ?, str_mod = ?, max_slots = ?, used_slots = ?, note = ?
            WHERE id = ?
            """,
            (
                form["name"],
                form["str_mod"],
                form["max_slots"],
                form["used_slots"],
                form["note"],
                member_id,
            ),
        )
        get_db().commit()
        flash("Entry updated.")
        return redirect(url_for("index"))
    return render_template("form.html", member=member, page_title="Edit Entry")


@app.post("/delete/<int:member_id>")
def delete_member(member_id: int) -> str:
    get_member(member_id)
    get_db().execute("DELETE FROM members WHERE id = ?", (member_id,))
    get_db().commit()
    flash("Entry deleted.")
    return redirect(url_for("index"))


def parse_member_form(form: dict) -> dict[str, int | str]:
    name = str(form.get("name", "")).strip()
    note = str(form.get("note", "")).strip()

    if not name:
        raise ValueError("Name is required.")

    try:
        str_mod = int(form.get("str_mod", 0))
        max_slots = int(form.get("max_slots", 0))
        used_slots = int(form.get("used_slots", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Strength mod and slots must be numbers.") from exc

    if max_slots < 0 or used_slots < 0:
        raise ValueError("Slots cannot be negative.")

    return {
        "name": name,
        "str_mod": str_mod,
        "max_slots": max_slots,
        "used_slots": used_slots,
        "note": note,
    }


@app.errorhandler(ValueError)
def handle_value_error(error: ValueError):
    flash(str(error))
    return redirect(request.referrer or url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
