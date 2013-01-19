# -*- coding:utf-8 -*-
# Database initialization and helper functions.
# Aleksi Pekkala 18.1.2013

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
        clauses = [] if kws else ""
        for key in kws:
            clauses.append("%s=$%s" % (key, key))
        if kws:
            clauses = " WHERE " + " AND ".join(clauses)
        if order_by:
            clauses += " ORDER BY %s" % order_by
        if limit:
            clauses += " LIMIT $limit"
        query = "SELECT " + values + " FROM " + tables + clauses
        kws["limit"] = limit
        return self.db.query(query, kws)

    def delete(self, table, id):
        """Deletes a row with given id from given table."""
        self.db.delete(table, vars=locals(), where="id=$id")

    def update(self, table, id, **kws):
        """Updates a row from selected table, kws determines which values are
        updated.

        >>> db = DatabaseHandler(); id=db.insert("users")
        >>> db.update("users", id, name="test", points=10);
        >>> user = db.select("users", id=id)[0]
        >>> user.name == "test" and user.points == 10
        True
        >>> db.delete("users", id)
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
        query = """SELECT courses.id, courses.code, courses.title,
                courses.faculty, count(materials.id) AS materials
                FROM courses, materials WHERE courses.id=materials.course_id
                """

        if id:
            query += " AND courses.id=$id"
        if order_by:
            query += " ORDER BY %s" % order_by
        if limit:
            query += " LIMIT $limit"

        return self.db.query(query, locals())

    def search_courses(self, query_word, code_only=False):
        """Selects courses whose code or title match the given query."""
        query_word = "%" + query_word + "%"
        query = "SELECT * from courses WHERE code LIKE $query_word"
        if not code_only:
            query += " OR title LIKE $query_word"
        return self.db.query(query, {"query_word": query_word})

    ### MATERIALS ###

    def get_materials(self, course_id=None, user_id=None, order_by=None, limit=None):
        """Returns either all selected materials or only a selected course's materials.
        Includes information about the course and the user who own's the material.

        >>> db = DatabaseHandler();uid = db.insert("users");cid = db.insert("courses");
        >>> mid = db.insert("materials", course_id=cid, user_id=uid)
        >>> db.get_materials(course_id=cid)[0].code == db.select("courses",id=cid)[0].code
        True
        >>> db.get_materials(user_id=uid)[0].name == db.select("users",id=uid)[0].name
        True
        >>> db.delete("materials",mid); db.delete("courses",cid); db.delete("users",uid)
        """
        query = """SELECT materials.id, materials.title, materials.description,
                materials.tags, materials.points, materials.date_added,
                materials.course_id, materials.user_id, materials.type,
                materials.size, courses.code,
                courses.title AS course_title, courses.faculty, users.name,
                users.points AS user_points FROM materials,courses,users
                 WHERE materials.user_id = users.id AND materials.course_id =
                 courses.id"""

        if course_id:
            query += " AND courses.id=$course_id"
        if user_id:
            query += " AND users.id=$user_id"
        if order_by:
            query += " ORDER BY %s" % order_by
        if limit:
            query += " LIMIT $limit"

        return self.db.query(query, locals())

    def get_materials_count(self, course_id):
        """Returns the number of materials a course has."""
        query = "SELECT count() FROM materials WHERE course_id=$course_id"
        return self.db.query(query, locals())[0]["count()"]

    def material_increase_points(self, id):
        """Increases the points of a material by one.

        >>> db = DatabaseHandler()
        >>> id = db.db.insert("materials",title="",description="",tags="",course_id=1,user_id=1)
        >>> db.select("materials", id=id)[0].points
        0
        >>> db.material_increase_points(id)
        >>> db.select("materials", id=id)[0].points
        1
        >>> db.delete("materials", id=id)
        """
        pts = self.select("materials", id=id)[0].points
        pts += 1
        self.db.update("materials", vars=locals(), where="id=$id", points=pts)

    ### COMMENTS ###

    def get_comments(self, material_id):
        return self.db.select("comments", locals(), where="material_id=$material_id", order="date_added")

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
                    points_given TEXT
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
        self.db.ctx.db.text_factory = str


if __name__=="__main__":
    db = DatabaseHandler()

def doctest():
    import doctest
    doctest.testmod()
