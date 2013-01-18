# -*- encoding: utf-8 -*-

import os
import web
import models
import hashlib
import re
import uuid
import socket
import cgi
import sys

### INITIALIZATION ###

urls = (
  "/", "Index",
  "/login", "Login",
  "/logout", "Logout",
  "/courses", "Courses",
  "/materials", "Materials",
  "/courses/(\d+)", "Course",
  "/register", "Register",
  "/confirm", "SendConfirmation",
  "/confirm/(.*)", "Confirm",
  "/add", "Add",
  "/add/(\d+)", "Upload"
  )

# App sends emails using a Gmail account:
web.config.smtp_server = "smtp.gmail.com"
web.config.smtp_port = 587
web.config.smtp_username = "kurssimateriaalit@gmail.com"
web.config.smtp_starttls = True
# Read Gmail account password from a separate file:
try:
    f = open("gmailpassword.txt", "r")
    web.config.smtp_password = f.read()
    f.close()
except IOError:
    sys.exit("You need a 'gmailpassword.txt' file with a password for the mail account")


# Maximum upload file size:
cgi.maxlen = 3 * 1024 * 1024


store = web.session.DiskStore("sessions")
app = web.application(urls, globals())
db = models.DatabaseHandler()

# Every users will have a unique session object:
if web.config.get('_session') is None:
    session = web.session.Session(app, store, initializer={"login": 0, "privilege": 0, "user": None, "id": None})
    web.config._session = session
else:
    session = web.config._session


### PAGES ###

class Upload:
    def GET(self, id):
        """Renders a form for adding a new material."""
        try:
            course = db.select("courses", id)[0]
        except:
            return "404"  # TODO

        render = create_render(session.privilege)
        return render.upload(id, course.code, course.title)

    def POST(self, id):
        """Adds a new material."""
        title = web.input().title.strip().capitalize()
        description = web.input().description.strip().capitalize()
        tags = web.input().tags.strip()

        print title
        print description
        print tags

        id = int(id)

        # Add material info to database:
        material_id = db.add_material(title, description, tags, id, session.id)  # TODO exception
        material_id_str = str(material_id)

        # Upload file:
        path = (6 - len(material_id_str)) * "0" + material_id_str
        folder = path[:3]
        path = folder + "/" + path[3:]
        if not os.path.exists("./static/uploads/" + folder):
            os.makedirs("./static/uploads/" + folder)

        try:
            f = web.input(myfile={})
            if "myfile" in f:
                file_to_upload = f["myfile"]
                filepath = file_to_upload.filename.replace("\\", "/")
                filename = filepath.split("/")[-1]
                filetype = filename.split(".")[-1]
                if not filetype in ["jpeg", "jpg", "pdf"]:
                    db.delete("materials", material_id)
                    raise web.seeother("/add/%d?error=bad_filetype" % id)
                fout = open("static/uploads/" + path + "." + filetype, "wb")
                fout.write(file_to_upload.file.read())
                fout.close()
                size = os.path.getsize("./static/uploads/" + path + "." + filetype)
                # Update file size and type to database:
                db.material_update_file(material_id, filetype, size)
            raise web.seeother("/")
        except ValueError:
            db.delete("materials", material_id)
            raise web.seeother("/add/%d?error=too_large_file" % id)
        except Exception, e:
            return e


class Add:
    def GET(self):
        """Renders a page where user can pick a course to add materials to."""
        if session.privilege == 0:
            raise web.seeother("/register")  # TODO lisää virheilmoitus

        render = create_render(session.privilege)
        query = web.input(query=None).query
        error = web.input(error=None).error

        if not query:
            # Render a search form without results:
            return render.add(courses=False, previous_query="itka123", error=error)

        courses = db.search_courses(query).list()
        # Render a search form with possible results:
        return render.add(courses=courses, previous_query=query, error=error)

    def POST(self):
        """Adds a new course, redirects to page where user can add material
        related to this course. Notifies user if given information is
        invalid or the course already exists."""
        code = web.input().code.strip().upper()
        title = web.input().title.strip().capitalize()
        faculty = web.input().faculty

        # First check for empty fields:
        if "" in [code, title]:
            raise web.seeother("/add?error=empty_fields")

        # Then check if a course with a same code already exists:
        if db.search_courses(code, code_only=True).list():
            raise web.seeother("/add?query=%s&error=course_exists" % code)

        # Finally check that submitted forms are valid:
        if re.match(r"^[A-Z0-9]{4}\d{3}$", code) == None:
            raise web.seeother("add?error=bad_code")
        title = re.sub(" +", " ", title)  # Remove multiple spaces from title.
        if re.match(r"^.{1,50}$", title) == None:  # TODO parempi regex?
            raise web.seeother("/add?error=bad_title")
        if not faculty in ["HUM", "IT", "JSBE", "EDU", "SPORT",
                           "SCIENCE", "YTK", "KIELI", "MUU"]:
            raise web.seeother("/add?error=bad_faculty")

        # Information is valid, add course to database:
        id = db.add_course(code, title, faculty)
        # Redirect to material submission page:
        raise web.seeother("/add/" + str(id))


class Confirm:
    def GET(self, conf_code):
        """Renders a page with a button for account verification
        and another for account deletion."""
        try:
            user = db.get_user(conf_code=conf_code)[0]
        except IndexError:
            return "404"  # TODO

        # Log in:
        session.login = 1
        session.privilege = user.privilege
        session.user = user.name
        session.id = user.id

        activated = web.input(activated=None).activated
        render = create_render(session.privilege)
        return render.confirm(activated)

    def POST(self, conf_code):
        print "trying to activate, id:", session.id
        try:
            db.user_activate(session.id)
        except Exception, e:
            return e  # TODO!!
        path = web.ctx.env.get("HTTP_REFERER", "/")
        if path != "/":
            path += "?activated=1"
        raise web.seeother(path)


class SendConfirmation:
    def GET(self):
        """Renders a form for user's email."""
        user = db.select("users", session.id).list()
        if not user:
            return "404"  # TODO
        error = web.input(error=None).error
        email_sent = web.input(email_sent=None).email_sent
        render = create_render(session.privilege)
        return render.send_confirm_email(error, email_sent)

    def POST(self):
        """Sends confirmation email to given address."""
        email = web.input(email="").email
        user = db.select("users", session.id).list()
        if not user:
            return "Käyttäjää ei löytynyt"  # TODO

        email_re = r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,4}$"
        if re.match(email_re, email, re.IGNORECASE) == None:  # Invalid email.
            raise web.seeother("/confirm?error=bad_email")

        conf_code = user[0].conf_code
        conf_url = "http://%s:8080/confirm/%s" % (socket.gethostbyname(socket.gethostname()), str(conf_code))  # TODO
        subject = "Kurssimateriaalit - Aktivoi käyttäjätilisi"
        message = """Aktivoi käyttäjätilisi osoitteessa %s

                  Spämmiä? Ei hätää; käyttäjätilin poistaminen onnistuu saman
                  osoitteen kautta""" % conf_url

        try:
            web.sendmail(web.config.smtp_username, email, subject, message)
        except:
            return "Sähköpostin lähetys epäonnistui"  # TODO
        web.seeother("/confirm?email_sent=1")


class Register:
    def GET(self):
        """Renders a login/register form."""
        error = web.input(error=None).error
        username = web.input(username="").username

        render = create_render(session.privilege)
        return render.register(error, username)

    def POST(self):
        """Validates registration form, adds a new user and redirects."""
        i = web.input(username=None, password1=None, password2=None)
        name, passwd1, passwd2 = i["username"], i["password1"], i["password2"]

        username_re = r"^[a-zåäöA-ZÅÄÖ0-9]{4,20}$"
        password_re = r"^(?=.*\d)(?=.*[a-zåäö])(?=.*[A-ZÅÄÖ])[0-9a-zåäöA-ZÅÄÖ!@#%]{8,80}$"

        validators = [
            ((lambda n, p1, p2: not n or not p1 or not p2), "empty_reg_fields"),
            ((lambda n, p1, p2: p1 != p2), "bad_match"),
            ((lambda n, p1, p2: re.match(username_re, n) == None), "bad_reg_username"),
            ((lambda n, p1, p2: re.match(password_re, p1) == None), "bad_reg_password"),
            ((lambda n, p1, p2: db.get_user(n).list()), "username_taken")
        ]

        for (f, msg) in validators:
            if f(name, passwd1, passwd2):
                raise web.seeother("/register?error=%s&username=%s" % (msg, name))

        # Input validated, add user to database:
        salt = uuid.uuid4().hex
        hash = hashlib.sha256(passwd1 + salt).hexdigest()
        conf_code = hashlib.md5(uuid.uuid4().hex + name).hexdigest()
        id = db.add_user(name, hash, salt, conf_code, 0)

        # Log in:
        session.login = 1
        session.privilege = 0
        session.id = id

        raise web.seeother("/confirm")


class Login:
    def POST(self):
        """Tries to log in and redirects accordingly."""
        i = web.input(username="", password="")
        name, passwd = i["username"], i["password"]

        try:
            ident = db.get_user(name)[0]
        except IndexError:  # Username not found.
            return web.seeother("/register?error=bad_login&username=%s" % name)

        try:
            # Login OK:
            if hashlib.sha256(passwd + ident.salt).hexdigest() == ident.hash:
                session.login = 1
                session.privilege = ident.privilege
                session.user = ident.name
                session.id = ident.id
                db.user_set_last_login(ident.id)
                raise web.seeother("/")
            # Wrong password:
            else:
                session.login = 0
                session.privilege = 0
                return web.seeother("/register?error=bad_login&username=%s" % name)
        except Exception, e:
            return e  # TODO 404 page


class Course:
    def GET(self, id):
        id = int(id)
        course = db.select("courses", id).list()
        if course:
            course = course[0]
        else:
            raise web.seeother("/")

        materials = db.get_materials(id)

        render = create_render(session.privilege)
        return render.course(course, materials)


class Courses:
    def GET(self):
        courses_iterator = db.select("courses", limit=10)
        courses = []
        for c in courses_iterator:
            c["materials"] = db.get_materials_num(c.id)
            courses.append(c)

        render = create_render(session.privilege)
        return render.courses(courses)


class Materials:
    def GET(self):
        materials = db.select("materials", limit=10)

        render = create_render(session.privilege)
        return render.materials(materials)


class Index:
    def GET(self):
        """Index page with lists of newest and most popular materials."""
        new_materials = db.get_materials(order_by="materials.date_added desc", limit=10)
        top_materials = db.get_materials(order_by="materials.points desc", limit=10)

        render = create_render(session.privilege)
        return render.index(new_materials, top_materials)


class Logout:
    """Kill the session."""
    def POST(self):
        path = web.ctx.env.get("HTTP_REFERER", "/")  # Previous page or index.
        session.login = 0
        session.kill()
        raise web.seeother(path)


### UTILITIES ###

def logged():
    if session.login == 1:
        return True
    return False


def path(material):
    id_str = str(material.id)
    id_str = (6 - len(id_str)) * "0" + id_str
    path = id_str[:3] + "/" + id_str[3:]
    return "/static/uploads/" + path + "." + material.type


def create_render(privilege):
    my_globals = {"session": session, "path": path}
    if logged():
        if privilege == 0:
            render = web.template.render('templates/reader', base='base', globals=my_globals)
        elif privilege == 1:
            render = web.template.render('templates/user', base='base', globals=my_globals)
        elif privilege == 2:
            render = web.template.render('templates/admin', base='base', globals=my_globals)
    else:
        render = web.template.render('templates/reader', base='base', globals=my_globals)
    return render


def format_date(date):
    """Formats a date string from 'YYYY-MM-DD' to 'DD.MM.YYYY'

    >>> db.format_date("2013-01-01")
    "01.01.2013"
    """
    parts = date.split("-")
    return "%s.%s.%s" % (parts[2], parts[1], parts[0])

if __name__ == "__main__":
    app.run()
