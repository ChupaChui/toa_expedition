from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "expedition.db"
BASE_SLOTS = 10
WATER_STEP = 5

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exception: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def create_db() -> None:
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            str_mod INTEGER NOT NULL DEFAULT 0,
            max_slots INTEGER NOT NULL DEFAULT 0,
            used_slots INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS extra_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS party_supplies (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            food INTEGER NOT NULL DEFAULT 0,
            water INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS loot_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    db.execute(
        """
        INSERT INTO party_supplies (id, food, water)
        VALUES (1, 0, 0)
        ON CONFLICT(id) DO NOTHING
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


def get_member_extra_slots(member_id: int) -> list[sqlite3.Row]:
    return get_db().execute(
        """
        SELECT id, name, amount
        FROM extra_slots
        WHERE member_id = ?
        ORDER BY id
        """,
        (member_id,),
    ).fetchall()


def get_party_supplies() -> sqlite3.Row:
    supplies = get_db().execute(
        "SELECT food, water FROM party_supplies WHERE id = 1"
    ).fetchone()
    if supplies is None:
        get_db().execute(
            "INSERT INTO party_supplies (id, food, water) VALUES (1, 0, 0)"
        )
        get_db().commit()
        supplies = get_db().execute(
            "SELECT food, water FROM party_supplies WHERE id = 1"
        ).fetchone()
    return supplies


def get_loot_items() -> list[sqlite3.Row]:
    return get_db().execute(
        """
        SELECT id, name, amount
        FROM loot_items
        ORDER BY id DESC
        """
    ).fetchall()


def slots_for_supply(amount: int) -> int:
    if amount <= 0:
        return 0
    return (amount + 4) // 5


@app.route("/")
def index() -> str:
    rows = get_db().execute(
        """
        SELECT
            m.id,
            m.name,
            m.str_mod,
            COALESCE(SUM(e.amount), 0) AS extra_slots_total
        FROM members AS m
        LEFT JOIN extra_slots AS e ON e.member_id = m.id
        GROUP BY m.id, m.name, m.str_mod
        ORDER BY m.id DESC
        """
    ).fetchall()

    members = []
    for row in rows:
        extra_slots = get_member_extra_slots(row["id"])
        member_max_slots = BASE_SLOTS + row["str_mod"] + row["extra_slots_total"]
        members.append(
            {
                "id": row["id"],
                "name": row["name"],
                "str_mod": row["str_mod"],
                "extra_slots_total": row["extra_slots_total"],
                "max_slots": member_max_slots,
                "extra_slots": extra_slots,
            }
        )

    supplies = get_party_supplies()
    loot_items = get_loot_items()

    food_slots = slots_for_supply(supplies["food"])
    water_slots = slots_for_supply(supplies["water"])
    loot_slots = sum(item["amount"] for item in loot_items)
    max_party_slots = sum(member["max_slots"] for member in members)
    occupied_slots = food_slots + water_slots + loot_slots

    return render_template(
        "index.html",
        members=members,
        supplies=supplies,
        loot_items=loot_items,
        party_summary={
            "max_party_slots": max_party_slots,
            "occupied_slots": occupied_slots,
            "free_party_slots": max_party_slots - occupied_slots,
            "food_slots": food_slots,
            "water_slots": water_slots,
            "loot_slots": loot_slots,
        },
    )


@app.route("/add", methods=["GET", "POST"])
def add_member() -> str:
    if request.method == "POST":
        form = parse_member_form(request.form)
        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO members (name, str_mod, max_slots, used_slots)
            VALUES (?, ?, ?, 0)
            """,
            (
                form["name"],
                form["str_mod"],
                BASE_SLOTS + form["str_mod"],
            ),
        )
        member_id = cursor.lastrowid
        save_extra_slots(db, member_id, form["extra_slots"])
        db.commit()
        flash("Entry added.")
        return redirect(url_for("index"))

    return render_template(
        "form.html",
        member=None,
        extra_slots=[{"name": "", "amount": 0}],
        page_title="Add Entry",
    )


@app.route("/edit/<int:member_id>", methods=["GET", "POST"])
def edit_member(member_id: int) -> str:
    member = get_member(member_id)
    if request.method == "POST":
        form = parse_member_form(request.form)
        db = get_db()
        db.execute(
            """
            UPDATE members
            SET name = ?, str_mod = ?, max_slots = ?, used_slots = 0
            WHERE id = ?
            """,
            (
                form["name"],
                form["str_mod"],
                BASE_SLOTS + form["str_mod"],
                member_id,
            ),
        )
        db.execute("DELETE FROM extra_slots WHERE member_id = ?", (member_id,))
        save_extra_slots(db, member_id, form["extra_slots"])
        db.commit()
        flash("Entry updated.")
        return redirect(url_for("index"))

    extra_slots = [
        {"name": row["name"], "amount": row["amount"]}
        for row in get_member_extra_slots(member_id)
    ]
    if not extra_slots:
        extra_slots = [{"name": "", "amount": 0}]

    return render_template(
        "form.html",
        member=member,
        extra_slots=extra_slots,
        page_title="Edit Entry",
    )


@app.post("/delete/<int:member_id>")
def delete_member(member_id: int) -> str:
    get_member(member_id)
    get_db().execute("DELETE FROM members WHERE id = ?", (member_id,))
    get_db().commit()
    flash("Entry deleted.")
    return redirect(url_for("index"))


@app.post("/supplies/update")
def update_supplies() -> str:
    resource = str(request.form.get("resource", "")).strip()
    direction = str(request.form.get("direction", "")).strip()

    if resource not in {"food", "water"}:
        raise ValueError("Unknown supply type.")
    if direction not in {"add", "remove"}:
        raise ValueError("Unknown supply action.")

    step = WATER_STEP if resource == "water" else 1
    delta = step if direction == "add" else -step

    supplies = get_party_supplies()
    next_amount = max(0, supplies[resource] + delta)
    get_db().execute(
        f"UPDATE party_supplies SET {resource} = ? WHERE id = 1",
        (next_amount,),
    )
    get_db().commit()
    return redirect(url_for("index"))


@app.post("/loot/add")
def add_loot() -> str:
    name = str(request.form.get("name", "")).strip()
    if not name:
        raise ValueError("Loot name is required.")

    try:
        amount = int(request.form.get("amount", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Loot weight must be a number.") from exc

    if amount <= 0:
        raise ValueError("Loot weight must be greater than 0.")

    get_db().execute(
        """
        INSERT INTO loot_items (name, amount)
        VALUES (?, ?)
        """,
        (name, amount),
    )
    get_db().commit()
    flash("Loot added.")
    return redirect(url_for("index"))


@app.post("/loot/delete/<int:loot_id>")
def delete_loot(loot_id: int) -> str:
    get_db().execute("DELETE FROM loot_items WHERE id = ?", (loot_id,))
    get_db().commit()
    flash("Loot removed.")
    return redirect(url_for("index"))


def save_extra_slots(
    db: sqlite3.Connection, member_id: int, extra_slots: list[dict[str, int | str]]
) -> None:
    for item in extra_slots:
        db.execute(
            """
            INSERT INTO extra_slots (member_id, name, amount)
            VALUES (?, ?, ?)
            """,
            (member_id, item["name"], item["amount"]),
        )


def parse_member_form(form: dict) -> dict[str, int | str | list[dict[str, int | str]]]:
    name = str(form.get("name", "")).strip()

    if not name:
        raise ValueError("Name is required.")

    try:
        str_mod = int(form.get("str_mod", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Strength mod must be a number.") from exc

    extra_slot_names = form.getlist("extra_slots_name")
    extra_slot_amounts = form.getlist("extra_slots_amount")
    extra_slots: list[dict[str, int | str]] = []

    for raw_name, raw_amount in zip(extra_slot_names, extra_slot_amounts):
        extra_name = str(raw_name).strip()
        amount_text = str(raw_amount).strip()

        if not extra_name and not amount_text:
            continue

        try:
            extra_amount = int(amount_text or 0)
        except ValueError as exc:
            raise ValueError("Extra slot amounts must be numbers.") from exc

        if extra_amount < 0:
            raise ValueError("Slots cannot be negative.")
        if extra_amount > 0 and not extra_name:
            raise ValueError("Each extra slot row needs a name.")
        if extra_name and extra_amount == 0:
            raise ValueError("Each extra slot row needs an amount.")

        extra_slots.append({"name": extra_name, "amount": extra_amount})

    return {
        "name": name,
        "str_mod": str_mod,
        "extra_slots": extra_slots,
    }


@app.errorhandler(ValueError)
def handle_value_error(error: ValueError):
    flash(str(error))
    return redirect(request.referrer or url_for("index"))


if __name__ == "__main__":
    create_db()
    app.run(debug=True)
