# -*- coding:utf-8 -*-
"""Database initialization and helper functions."""
__author__ = "Aleksi Pekkala"

import web
import sqlite3


class DatabaseHandler:
    """A database wrapper class."""

    ### GENERAL ###

    def select(self, tables, values="*", order_by=None, limit=None, **kws):
        """Selects rows from given table, kws determines WHERE-clauses.

        >>> db=DatabaseHandler();id1=db.insert("users",name="u1",points=1)
        >>> id2 = db.insert("users", name="u1", points=2)
        >>> db.select("users", name="u1", points=1)[0].id == id1
        True
        >>> db.delete("users", id=id1); db.delete("users", id=id2)
        """
        if type(tables) == list:
            tables = ",".join(tables)

        clauses = " AND ".join(["%s=$%s" % (key, key) for key in kws])
        clauses = " WHERE " + clauses if clauses else ""
        if order_by:
            clauses += " ORDER BY %s" % order_by
        if limit:
            clauses += " LIMIT $limit"
        query = "SELECT " + values + " FROM " + tables + clauses
        kws["limit"] = limit
        return self.db.query(query, kws)

    def delete(self, table, **kws):
        """Deletes all rows or a given row from a table."""
        query = "DELETE FROM " + table
        clauses = " AND ".join(["%s=$%s" % (key, key) for key in kws])
        if clauses:
            query = query + " WHERE " + clauses
        self.db.query(query, kws)

    def update(self, table, id, **kws):
        """Updates a row from selected table, kws determines which values are
        updated.

        >>> db = DatabaseHandler(); id=db.insert("users")
        >>> db.update("users", id, name="test", points=10);
        >>> user = db.select("users", id=id)[0]
        >>> user.name == "test" and user.points == 10
        True
        >>> db.delete("users", id=id)
        """
        values = []
        for key in kws:
            values.append("%s=$%s" % (key, key))
        query = "UPDATE %s SET %s WHERE id=$id" % (table, ",".join(values))
        kws["id"] = id
        self.db.query(query, kws)

    ### USERS ###

    def user_increase_points(self, id):
        """Increases user's points by one."""
        pts = self.select("users", id)[0].points + 1
        self.db.update("users", id, points=pts)

    ### COURSES ###

    def get_courses(self, id=None, order_by=None, limit=None):
        """Selects courses and the number of materials they have."""
        query = """SELECT id, code, title, faculty,
                (SELECT count(*) FROM materials
                WHERE materials.course_id=courses.id)
                AS materials FROM courses"""
        if id:
            query += " WHERE id=$id"
        if order_by:
            query += " ORDER BY %s" % order_by
        if limit:
            query += " LIMIT $limit"

        return self.db.query(query, locals())

    def search_courses(self, search, code_only=False):
        """Selects courses whose code or title match the given query."""
        search = "%" + search + "%"
        query = "SELECT * from courses WHERE code LIKE $search"
        if not code_only:
            query += " OR title LIKE $search"
        return self.db.query(query, {"search": search})

    ### MATERIALS ###

    def get_materials(self, id=None, course_id=None, user_id=None,
        faculty=None, search=None, order_by=None, limit=None):
        """Returns all materials that match the given criteria.
        Includes information about the course and the user who submitted the material.

        >>> db = DatabaseHandler();uid = db.insert("users");cid = db.insert("courses");
        >>> mid = db.insert("materials", course_id=cid, user_id=uid)
        >>> db.get_materials(course_id=cid)[0].code == db.select("courses",id=cid)[0].code
        True
        >>> db.get_materials(user_id=uid)[0].name == db.select("users",id=uid)[0].name
        True
        >>> db.delete("materials",id=mid); db.delete("courses",id=cid); db.delete("users",id=uid)
        """
        args = locals()
        search = "%" + search + "%" if search else None
        query = """SELECT materials.*, courses.code, courses.title
                AS course_title, courses.faculty, users.name, users.points AS
                user_points FROM materials JOIN courses ON course_id=courses.id
                JOIN users ON user_id=users.id"""

        dict = {"id": "materials.id=$id",
                "course_id": "courses.id=$course_id",
                "user_id": "users.id=$user_id",
                "faculty": "courses.faculty=$faculty",
                "search": """courses.code LIKE $search
                          OR course_title LIKE $search
                          OR materials.title LIKE $search
                          OR tags LIKE $search
                          OR courses.faculty LIKE $search"""}
        clauses = " AND ".join([dict[key] for key in dict.keys() if args[key]])
        query += " WHERE " + clauses if clauses else ""

        if order_by:
            query += " ORDER BY %s" % order_by
        if limit:
            query += " LIMIT $limit"
        return self.db.query(query, locals())

    def like_material(self, material_id, user_id):
        """Increases the points of a material by one, adds material's id to
        user's "liked" column, so that it won't get liked twice by
        the same user. Returns the material's points after the increase.

        >>> db = DatabaseHandler(); uid = db.insert("users");
        >>> mid = db.insert("materials", user_id=uid)
        >>> db.like_material(mid, uid)
        1
        >>> db.select("materials", id=mid)[0].points
        1
        >>> db.select("users", id=uid)[0].liked.split(" ")[0] == str(mid)
        True
        >>> db.delete("materials", id=mid); db.delete("users", id=uid)
        """
        # Update material's points:
        material = self.select("materials", id=material_id)[0]
        pts = material.points + 1
        self.update("materials", id=material_id, points=pts)
        # Update material's owner's points:
        owner_pts = self.select("users", id=material.user_id)[0].points + 1
        self.update("users", id=material.user_id, points=owner_pts)
        # Update the user who liked the material:
        liked = self.select("users", id=user_id)[0].liked
        liked = liked + " " + str(material_id) if liked else str(material_id)
        self.update("users", id=user_id, liked=liked)
        return pts

    def delete_material(self, id):
        """Deletes a material and its comments from database, reduces
        owner's points accordingly."""
        self.delete("comments", material_id=id)
        material = self.select("materials", id=id)[0]
        points, user_id = material.points, material.user_id
        user_points = self.select("users", id=user_id)[0].points
        self.update("users", id=user_id, points=(user_points - points))
        self.delete("materials", id=id)

    ### COMMENTS ###

    def add_comment(self, content, user_id, material_id):
        """Add a comment, increase the material's amount of comments by one."""
        self.insert("comments", content=content, user_id=user_id,
            material_id=material_id)
        comments = self.select("materials", id=material_id)[0].comments + 1
        self.update("materials", material_id, comments=comments)
        return comments

    def get_comments(self, material_id):
        """Returns a given material's comments."""
        query = """SELECT id, content, user_id, material_id, date_added,
                (SELECT name FROM users WHERE users.id = user_id) AS name
                FROM comments WHERE material_id = $material_id
                ORDER BY date_added LIMIT 100
                """
        return self.db.query(query, locals())

    ### INIT ###

    def __init__(self):
        """Initializes database tables if they don't already exist."""
        try:
            conn = sqlite3.connect("kurssit.db")
            c = conn.cursor()
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users(
                    id           INTEGER PRIMARY KEY,
                    name         TEXT,
                    hash         TEXT,
                    salt         TEXT,
                    conf_code    TEXT,
                    privilege    INTEGER DEFAULT 1,
                    date_joined  TEXT DEFAULT CURRENT_DATE,
                    last_login   TEXT DEFAULT CURRENT_DATE,
                    points       INTEGER DEFAULT 0,
                    liked        TEXT
                );
                CREATE TABLE IF NOT EXISTS courses(
                    id           INTEGER PRIMARY KEY,
                    code         TEXT,
                    title        TEXT,
                    faculty      TEXT
                );
                CREATE TABLE IF NOT EXISTS materials(
                    id           INTEGER PRIMARY KEY,
                    title        TEXT,
                    description  TEXT,
                    tags         TEXT,
                    points       INTEGER DEFAULT 0,
                    date_added   TEXT DEFAULT CURRENT_DATE,
                    course_id    INTEGER,
                    user_id      INTEGER,
                    comments     INTEGER DEFAULT 0,
                    size         INTEGER,
                    type         TEXT
                );
                CREATE TABLE IF NOT EXISTS comments(
                    id           INTEGER PRIMARY KEY,
                    content      TEXT,
                    user_id      INTEGER,
                    material_id  INTEGER,
                    date_added   TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.close()

        except Exception, e:
            print e
            import sys
            sys.exit()

        self.db = web.database(dbn="sqlite", db="kurssit.db")
        self.insert = self.db.insert

if __name__ == "__main__":
    db = DatabaseHandler()


def doctest():
    import doctest
    doctest.testmod()
