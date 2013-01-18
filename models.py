# -*- coding:utf-8 -*-
# Everything database-related
# Aleksi Pekkala 13.1.2013

import web
import sqlite3
import datetime


class DatabaseHandler:
    """A database wrapper class."""
    def select(self, table, id=None, order_by="id", limit=100):
        if id:
            return self.db.select(table, locals(), where="id=$id", order=order_by, limit=limit)
        return self.db.select(table, order=order_by, limit=limit)

    def delete(self, table, id):
        self.db.delete(table, vars=locals(), where="id=$id")

    ### USERS ###

    def get_user(self, name=None, conf_code=None):
        if name:
            return self.db.select("users", locals(), where="name=$name")
        return self.db.select("users", locals(), where="conf_code=$conf_code")

    def add_user(self, name, hash, salt, conf_code, privilege):
        return self.db.insert("users", name=name, hash=hash, salt=salt,
            conf_code=conf_code, privilege=privilege)

    def user_activate(self, id):
        self.db.update("users", where="id=" + str(id), privilege=1)

    def user_update_hash(self, id, hash, salt):
        self.db.update("users", where="id=" + str(id), hash=hash, salt=salt)

    def user_increase_points(self, id):
        try:
            pts = self.select("users", id)[0].points + 1
        except:
            return False
        self.db.update("users", where="id=" + str(id), points=pts)
        return True

    def user_set_last_login(self, id):
        date = str(datetime.date.today())
        self.db.update("users", where="id=" + str(id), last_login=date)

    ### COURSES ###

    def add_course(self, code, title, faculty):
        return self.db.insert("courses", code=code, title=title, faculty=faculty)

    def search_courses(self, query_word, code_only=False):
        query_word = "%" + query_word + "%"
        query = "SELECT * from courses WHERE code LIKE $query_word"
        if not code_only:
            query += " OR title LIKE $query_word"
        return self.db.query(query, vars={"query_word": query_word})

    ### MATERIALS ###

    def add_material(self, title, description, tags, course_id, user_id):
        return self.db.insert("materials", title=title, description=description,
            course_id=course_id, user_id=user_id)

    def get_materials(self, course_id=None, user_id=None, order_by=None, limit=10):
        """Returns either all selected materials or only a selected course's materials.
        Includes information about the course and the user who own's the material.

        >>> db = DatabaseHandler(); uid = db.add_user("doctest","","",0)
        >>> cid = db.add_course("","",""); mid = db.add_material("","","",cid,uid)
        >>> db.get_materials(course_id=cid)[0].code == db.select("courses",cid)[0].code
        True
        >>> db.get_materials(user_id=uid)[0].name == db.select("users",uid)[0].name
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
                 courses.id%s"""

        params = ""
        if course_id:
            params += " AND courses.id=%d" % course_id
        if user_id:
            params += " AND users.id=%d" % user_id
        if order_by:
            params += " ORDER BY %s" % order_by
        params += " LIMIT %d" % limit

        return self.db.query(query % params)

    def get_materials_num(self, course_id):
        """Returns the number of materials a course has."""
        return len(self.db.select("materials", locals(), where="course_id=$course_id").list())

    def material_update_file(self, id, file_type, size):
        self.db.update("materials", where="id=" + str(id), type=file_type, size=size)

    def update_material(self, id, title, description, tags):
        self.db.update("materials", where="id=" + str(id), title=title,
            description=description, tags=tags)

    def material_increase_points(self, id):
        """Increases the points of a material by one.

        >>> db = DatabaseHandler()
        >>> id = db.add_material("","","",1,1)
        >>> db.select("materials", id)[0].points
        0
        >>> db.material_increase_points(id)
        True
        >>> db.select("materials", id)[0].points
        1
        >>> db.delete("materials", id)
        """
        try:
            pts = self.select("materials", id)[0].points
        except:
            return False
        pts += 1
        self.db.update("materials", where="id=" + str(id), points=pts)
        return True

    ### COMMENTS ###

    def add_comment(self, content, user_id, material_id):
        comments = self.select("materials", material_id)[0].comments
        comments += 1
        self.db.update("materials", where="id=" + str(material_id), comments=comments)
        return self.db.insert("comments", content=content, user_id=user_id,
            material_id=material_id)

    def get_comments(self, material_id):
        return self.db.select("comments", locals(), where="material_id=$material_id", order="date_added")

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
        self.db.ctx.db.text_factory = str

    ### UTILITIES ###

    def create_data(self):
        self.add_course("ITKA100", "Ohjelmointi 1",  "IT")
        self.add_course("ITKA123", "Algoritmit", "IT")
        self.add_course("FIL666", "Johdatus käsienheilutteluun",  "Humanistinen")
        self.add_course("KTTP100", "Kansantaloustieteen peruskurssi", "Kauppakorkeakoulu")
        self.add_course("SPOR123", "Jotain urheilua",  "Liikuntatieteellinen")
        self.add_course("PSY001", "Jedi mind tricks",  "Yhteiskuntatieteellinen")
        self.add_course("XXXXYYY", "Testi1",  "Matemaattis-luonnontieteell.")
        self.add_course("ITKA999", "Johdatus ohjelmistotekniikkaan", "IT")
        self.add_course("ITKP001", "Ohjelmointi 3", "IT")

        self.add_material("Irmelin muistiinpanot", "Ihan sika hyvät", "Irmeli ITKA100 Ohjemointi 1", 1, 1)
        self.add_material("Kallen ohjelmointidiat", "Niitä on yks kaks ja kolme", "Kallen diat algoritmit", 1, 1)
        self.add_material("Irmelin hum. muistiinpanot", "Ihan sika hyvät", "Irmeli ITKA100 Ohjemointi 1", 2, 1)
        self.add_material("Irmelin kttp muistiinpanot4", "Ihan sika hyvät", "Irmeli ITKA100 Ohjemointi 1", 3, 1)
        self.add_material("Irmelin sport muistiinpanot5", "Ihan sika hyvät", "Irmeli ITKA100 Ohjemointi 1", 4, 1)
        self.add_material("Irmelin psy muistiinpanot6", "Ihan sika hyvät", "Irmeli ITKA100 Ohjemointi 1", 5, 1)
        self.add_material("Irmelin jot muistiinpanot7", "Ihan sika hyvät", "Irmeli ITKA100 Ohjemointi 1", 6, 1)
        self.add_material("Irmelin ohj3 muistiinpanot8", "Ihan sika hyvät", "Irmeli ITKA100 Ohjemointi 1", 7, 1)

    def clear_data(self):
        for table in ["courses", "materials"]:
            for item in self.select(table):
                self.delete(table, item.id)


def doctest():
    import doctest
    doctest.testmod()
