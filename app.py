#!/usr/bin/python
# -*- encoding: utf-8 -*-
"""A web app for sharing course materials, such as notes."""
__author__ = "Aleksi Pekkala"

import os
import web
import models
import hashlib
import re
import uuid
import socket
import cgi
import sys
import zipfile
import datetime
import json
import mimetypes
import shelve

### INITIALIZATION ###

urls = (                           # GET/POST
  "/", "Index",                    # Index/-
  "/login", "Login",               # Login/-
  "/logout", "Logout",             # Logout/-
  "/courses", "Courses",           # Results of a course search./-
  "/coursesJSON", "CoursesJSON",   # Top 10 courses in JSON/-
  "/register", "Register",         # Login and register form/Registration
  "/confirm", "SendConfirmation",  # Form for email address/Send conf. email
  "/confirm/(.*)", "Confirm",      # Page for confirming activation/Activation
  "/add", "Add",                   # Form for courses/Add a course
  "/add/(\d+)", "Upload",          # Form for materials/Upload a material
  "/download/(\d+)", "Download",   # Serving a file/-
  "/like", "Like",                 # Liking a material/-
  "/delete/(\d+)", "Delete",       # Deleting a material/-
  "/materials", "Materials",       # Multiple materials/-
  "/materials/(\d+)", "Material",  # A material with comments/Add a comment
  "/timezone", "SetTimezone"       # -/Set user timezone
)

UPLOAD_DIR = os.path.join(".", "uploads")
ALLOWED_FILETYPES = ["jpg", "jpeg", "png", "gif", "bmp", "zip", "pdf", "mpg",
                     "doc", "docx", "xls", "csv", "txt", "rtf", "html", "htm",
                     "xlsx", "ppt", "pptx", "odt", "mp3", "m4a", "ogg", "wav",
                     "mp4", "m4v", "wmv", "avi"]

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

# Maximum file upload size:
cgi.maxlen = 10 * 1024 * 1024

app = web.application(urls, globals(), True)
# application = app.wsgifunc()
db = models.DatabaseHandler()

# Every user will have a unique session object:
if web.config.get("_session") is None:
    initializer = {"login": 0, "privilege": 0, "user": None,
                   "id": None, "timezone": None}
    store = web.session.ShelfStore(shelve.open("sessions.shelf"))
    session = web.session.Session(app, store, initializer)
    web.config._session = session
else:
    session = web.config._session


### UTILITIES ###

def logged():
    """Returns True if user is logged in."""
    if session.login == 1:
        return True
    return False


def create_path(id):
    """Returns a file path based on given material id.

    >>> create_path(13) == os.path.join(UPLOAD_DIR, "000", "013")
    True
    """
    id = str(id)
    path = (6 - len(id)) * "0" + id
    folder = path[:3]
    return os.path.join(UPLOAD_DIR, folder, path[3:])


def is_valid_zip(path):
    """Returns False if a zip file contains any disallowed filetypes."""
    for content in zipfile.ZipFile(path).namelist():
        content_type = content.split(".")[-1]
        if content_type == content or not content_type in ALLOWED_FILETYPES:
            return False
    return True


def delete_file(path):
    """Deletes a file at given path, returns True if deleted successfully.

    >>> delete_file(UPLOAD_DIR + "\\..\\something_important")
    False
    >>> delete_file("C:\\System32")
    False"""
    regex = r"^((\\|/)\d{3}){2}\.\w{1,4}$"
    if not path.startswith(UPLOAD_DIR):
        return False
    if re.match(regex, path[len(UPLOAD_DIR):], re.IGNORECASE) == None:
        return False
    try:
        os.remove(path)
    except:
        return False
    return True


def create_render(privilege, base=True):
    """Create a render object based on user's privilege; different privileges
    use different HTML templates."""
    my_globals = {"session": session,
                  "format_date": format_date,
                  "format_size": format_size,
                  "format_time": format_time,
                  "csrf_token": csrf_token}
    base = "base" if base else None
    if logged():
        if privilege == 0:
            render = web.template.render("templates/reader", base=base, globals=my_globals)
        elif privilege == 1:
            render = web.template.render("templates/user", base=base, globals=my_globals)
        elif privilege == 2:
            render = web.template.render("templates/admin", base=base, globals=my_globals)
    else:
        render = web.template.render("templates/reader", base=base, globals=my_globals)
    return render


def csrf_protected(f):
    """Checks for CSRF by comparing tokens, or in case of AJAX requests,
    checking that the request was made with a XMLHttpRequest which doesn't
    allow third party connections."""
    def decorated(*args, **kws):
        if web.ctx.env.get("HTTP_X_REQUESTED_WITH") != "XMLHttpRequest":
            inp = web.input(csrf_token="")
            if not (inp.csrf_token == session.csrf_token):
                raise web.HTTPError(
                    "400 Bad request",
                    {"content-type": "text/html"},
                    "Possible CSRF attempt."
                )
        return f(*args, **kws)
    return decorated


### TEMPLATE FUNCTIONS ###

def csrf_token():
    """Assigns user a random string which is used to mark each csrf-protected
    non-AJAX form."""
    if not "csrf_token" in session:
        session.csrf_token = uuid.uuid4().hex
        print "token:", session.csrf_token
    return session.csrf_token


def format_date(date_str):
    """Formats a date string from 'YYYY-MM-DD' to 'D.M.YYYY'

    >>> format_date("2013-01-01") == "1.1.2013"
    True
    """
    parts = date_str.split("-")
    return "%d.%d.%s" % (int(parts[2]), int(parts[1]), parts[0])


def format_time(time_str):
    """Formats a datetime string into something more readable.

    >>> minute = datetime.timedelta(0, 60); hour = 60 * minute; day = 24 * hour
    >>> now = datetime.datetime.now; today = datetime.date.today
    >>> format = "%Y-%m-%d %H:%M:%S"; session.timezone = None
    >>> time_str = lambda time: datetime.datetime.strftime(time, format)
    >>> format_time(time_str(now()))
    '0 minuuttia sitten'
    >>> format_time(time_str(now() - 15 * minute))
    '15 minuuttia sitten'
    >>> format_time(time_str(now() - 25 * hour))
    'eilen'
    """
    time = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    if session.timezone:
        time += datetime.timedelta(0, session.timezone * 60 * 60)
    diff = datetime.datetime.now() - time
    if diff.days > 1:
        return format_date(time_str.split(" ")[0])
    elif diff.days == 1:
        return "eilen"
    elif diff.seconds > 60 * 60:
        return "%d tuntia sitten" % (diff.seconds / (60 * 60))
    return "%d minuuttia sitten" % (diff.seconds / 60)


def format_size(size):
    """Formats a file size into a string.

    >>> format_size(1023) == "<1MB" and format_size(2800) == "2.8MB"
    True
    """
    size_str = str(size)
    if size < 1024:
        return "<1MB"
    if size < 10000:
        return size_str[0] + "." + size_str[1] + "MB"
    return size_str[:2] + "." + size_str[2] + "MB"


def doctest():
    """Run doctests."""
    import doctest
    doctest.testmod()


### PAGES ###

class Index:
    def GET(self):
        """Renders an index page."""
        render = create_render(session.privilege)
        return render.index()


class SetTimezone():
    @csrf_protected
    def POST(self):
        """Stores user's timezone offset to the session object.
        Timezone is obtained by Javascript."""
        offset = web.input(offset=None).offset
        if offset:
            offset = int(offset) / 60 * -1
        session.timezone = offset


class Logout:
    """Kill the session, redirect to index."""
    def GET(self):
        session.login = 0
        session.kill()
        raise web.seeother("/")


class Download():
    def GET(self, id):
        """Serves a file."""
        try:
            material = db.select("materials", id=int(id))[0]
        except IndexError:
            raise web.notfound()  # Material doesn't exist.

        path = create_path(id) + "." + material.type
        if not os.path.exists(path):
            raise web.notfound()  # File doesn't exist.
        try:
            content_type = mimetypes.types_map["." + material.type]
            web.header("Content-Type", content_type)
        except KeyError:
            pass  # Content type is unknown.

        web.header("Transfer-Encoding", "chunked")
        f = open(path, 'rb')
        while 1:
            buf = f.read(1024)  # Doesn't load the whole file into memory.
            if not buf:
                f.close()
                break
            yield buf


class Upload:
    def GET(self, id):
        """Renders a form for adding a new material."""
        if session.privilege < 1:
            raise web.seeother("/register")
        try:
            course = db.select("courses", id=id)[0]
        except IndexError:
            raise web.notfound()

        render = create_render(session.privilege)
        return render.upload(course)

    @csrf_protected
    def POST(self, id):
        """Validates material submission form, adds a new material entry and
        uploads the corresponding file. Returns an error message or an empty
        string if nothing went wrong."""
        course_id = int(id)
        title = web.input().title.strip().capitalize()
        tags = web.input().tags.strip().replace(",", " ").split()[:5]
        tags = " ".join([tag for tag in tags if len(tag) < 20])
        description = web.input().description.strip().capitalize()
        if len(description) > 300:
            description = description[:300] + "..."

        if re.match(r"^.{4,40}$", title) == None:
            return "Materiaalin nimi ei ole annetussa muodossa."

        # Insert material to database, use row id to generate file path:
        material_id = db.insert("materials", title=title, description=description,
            tags=tags, course_id=course_id, user_id=session.id)

        # Create a path from id, eg. 11 becomes ".\\uploads\\000\\011"
        path = create_path(material_id)
        if not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))

        try:
            x = web.input(myfile={})
            if "myfile" in x:
                file_to_upload = x["myfile"]
                filepath = file_to_upload.filename.replace("\\", "/")
                filename = filepath.split("/")[-1]
                filetype = filename.split(".")[-1]
                path += "." + filetype

                # Check for illegal file types:
                if not filetype in ALLOWED_FILETYPES or filetype == filename:
                    db.delete("materials", id=material_id)
                    return "Tiedostotyyppi ei ole sallittu."

                # Upload file:
                fout = open(path, "wb")
                fout.write(file_to_upload.file.read())
                fout.close()

                # If file is zipped, check contents:
                if filetype == "zip" and not is_valid_zip(path):
                    db.delete("materials", id=material_id)
                    delete_file(path)
                    return "Zip-tiedosto sisältää ei sallittuja tiedostoja."

                # Update file size and type to database:
                size = os.path.getsize(path) / 1024
                db.update("materials", material_id, type=filetype, size=size)
            else:
                db.delete("materials", id=material_id)
                return "Lataaminen epäonnistui, yritä hetken kuluttua uudestaan."
            return ""
        except ValueError:  # File is too large.
            db.delete("materials", id=material_id)
            delete_file(path)
            return "Tiedoston maksimikoko on 10MB."


class Like:
    @csrf_protected
    def GET(self):
        """'Likes' a material, i.e. inreases it's points by one and adds
        the material's id to user's 'liked' column. Returns current points if
        succeed, otherwise an empty string."""
        id = web.input(id=None).id
        if not id or session.privilege < 1:
            return ""

        user = db.select("users", id=session.id)[0]
        material = db.select("materials", id=int(id))[0]
        liked = db.select("users", id=session.id)[0].liked

        # Don't like if user has already liked this material or owns the material:
        if liked and id in liked.split(" ") or material.user_id == user.id:
            return ""

        points = db.like_material(material_id=int(id), user_id=session.id)
        return str(points)


class Add:
    def GET(self):
        """Renders a page where user can pick a course to add materials to."""
        if session.privilege == 0:
            if session.login:
                raise web.seeother("/confirm")
            raise web.seeother("/register")

        render = create_render(session.privilege)
        return render.choose_course()

    @csrf_protected
    def POST(self):
        """Validates the course form, sends a JSON response which either has a
        redirect url or an error message. If form is valid, adds the course."""
        code = web.input().code.strip().upper()
        title = web.input().title.strip().capitalize()
        title = re.sub(" +", " ", title)
        faculty = web.input().faculty
        course = db.select("courses", code=code.upper()).list()
        resp = ""

        # First check for empty fields:
        if "" in [code, title]:
            resp = {"error": "Lomake sisältää tyhjiä kenttiä."}

        # Then check if a course with the same code already exists:
        elif course:
            resp = {"redirect": "/add/" + str(course[0].id)}

        # Finally check that submitted forms are valid:
        elif re.match(r"^[A-Z0-9]{5}\d{2}$", code) == None:
            resp = {"error": "Kurssikoodi ei ole sallitussa muodossa."}
        elif re.match(r"^.{1,50}$", title) == None:  # TODO parempi regex?
            resp = {"error": "Kurssin nimi ei ole sallitussa muodossa."}
        elif not faculty in ["HUM", "IT", "JSBE", "EDU", "SPORT",
                             "SCIENCE", "YTK", "KIELI", "MUU"]:
            resp = {"error": "Valitse kurssin organisaatio."}

        # Information is valid, add course to database:
        else:
            id = db.insert("courses", code=code, title=title, faculty=faculty)
            resp = {"redirect": "/add/" + str(id)}

        web.header("Content-Type", "application/json")
        return json.dumps(resp)


class Confirm:
    def GET(self, conf_code):
        """Renders a page with a button for account verification
        and another for account deletion."""
        try:
            user = db.select("users", conf_code=conf_code)[0]
        except IndexError:
            raise web.notfound()

        # Log in:
        session.login = 1
        session.privilege = user.privilege
        session.user = user.name
        session.id = user.id

        activated = web.input(activated=None).activated
        render = create_render(session.privilege)
        return render.confirm(activated)

    def POST(self, conf_code):
        """Activates an user, ie. updates privilege to 1."""
        db.update("users", session.id, privilege=1)
        path = web.ctx.env.get("HTTP_REFERER", "/")
        if path != "/":
            path += "?activated=1"
        raise web.seeother(path)


class SendConfirmation:
    def GET(self):
        """Renders a form for user's email."""
        user = db.select("users", id=session.id).list()
        if not user or session.privilege != 0:
            raise web.notfound()
        error = web.input(error=None).error
        email_sent = web.input(email_sent=None).email_sent
        render = create_render(session.privilege)
        return render.send_confirm_email(error, email_sent)

    @csrf_protected
    def POST(self):
        """Sends confirmation email to given address."""
        email = web.input(email="").email
        user = db.select("users", id=session.id)[0]

        email_re = r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,4}$"
        if re.match(email_re, email, re.IGNORECASE) == None:  # Invalid email.
            raise web.seeother("/confirm?error=bad_email")

        conf_code = user.conf_code
        ip = socket.gethostbyname(socket.gethostname())
        conf_url = "http://toimiiks.cloudapp.net/confirm/%s" % str(conf_code)  # TODO osoitteen automaattinen tunnistus
        subject = "Kurssimateriaalit - Aktivoi käyttäjätilisi"
        message = u"Aktivoi käyttäjätilisi '%s' osoitteessa %s" % (user.name, conf_url)

        try:
            web.sendmail(web.config.smtp_username, email, subject, message)
        except:
            raise web.seeother("/confirm")
        raise web.seeother("/confirm?email_sent=1")


class Register:
    def GET(self):
        """Renders a login/register form."""
        render = create_render(session.privilege)
        return render.register()

    @csrf_protected
    def POST(self):
        """Validates registration form, adds a new user and redirects."""
        i = web.input(username=None, password1=None, password2=None)
        name, passwd1, passwd2 = i["username"], i["password1"], i["password2"]
        username_re = r"[A-ZÅÄÖ0-9]{4,20}"
        password_re = r"^(?=.*\d)(?=.*[a-zåäö])(?=.*[A-ZÅÄÖ])[0-9a-zöäåA-ZÅÄÖ!@#%]{8,80}$"

        validators = [
            ((lambda n, p1, p2: not n or not p1 or not p2),
              "Täytä kaikki kentät."),
            ((lambda n, p1, p2: p1 != p2),
              "Salasana ei vastaa varmistusta."),
            ((lambda n, p1, p2: re.match(username_re, n, re.IGNORECASE) == None),
              "Käyttäjänimi ei ole sallitussa muodossa."),
            ((lambda n, p1, p2: re.match(password_re, p1) == None),
              "Salasana ei ole sallitussa muodossa."),
            ((lambda n, p1, p2: db.select("users", name=n).list()),
              "Käyttäjänimi on varattu.")
        ]

        for (f, msg) in validators:
            if f(name, passwd1, passwd2):
                return msg

        # Input validated, add user to database:
        salt = unicode(uuid.uuid4().hex)
        hash = unicode(hashlib.sha256(passwd1.encode("utf-8") + salt).hexdigest())
        conf_code = unicode(hashlib.md5(uuid.uuid4().hex + name.encode("utf-8")).hexdigest())
        id = db.insert("users", name=name, hash=hash, salt=salt,
            conf_code=conf_code, privilege=0)

        # Log in:
        session.login = 1
        session.privilege = 0
        session.id = id
        return ""


class Login:
    @csrf_protected
    def POST(self):
        """Tries to log in, returns an error message or an empty string."""
        i = web.input(username="", password="")
        name, passwd = i["username"], i["password"]
        try:
            ident = db.select("users", name=name)[0]
        except IndexError:  # Username not found.
            return "Virheellinen käyttäjänimi tai salasana."

        try:
            salted_pass = passwd.encode("utf-8") + str(ident.salt)
            # Login OK:
            if hashlib.sha256(salted_pass).hexdigest() == ident.hash:
                session.login = 1
                session.privilege = ident.privilege
                session.user = ident.name
                session.id = ident.id
                # Update user's last login date:
                date = str(datetime.date.today())
                db.update("users", ident.id, last_login=date)
                return ""
            # Wrong password:
            else:
                session.login = 0
                session.privilege = 0
                return "Virheellinen käyttäjänimi tai salasana."
        except Exception:
            return "Kirjautuminen epäonnistui."


class Courses:
    @csrf_protected
    def GET(self):
        """Returns an HTML snippet containing a table of the courses that
        matched the query, and a form for adding a new course."""
        render = create_render(session.privilege, base=False)
        query = web.input(query="").query
        if not query:
            return render.course_results(None)
        courses = db.search_courses(query).list()
        return render.course_results(courses)


class CoursesJSON:
    @csrf_protected
    def GET(self):
        """Returns JSON that contains the ids and codes of the most popular
        courses, plus the amount of materials each one has."""
        courses = db.get_courses(order_by="materials desc",
            limit=10)
        obj = []
        for c in courses:
            obj.append({"id": c.id, "code": c.code, "materials": c.materials})

        web.header("Content-Type", "application/json")
        return json.dumps(obj)


class Delete:
    def GET(self, id):
        """Deletes a material and its corresponding file."""
        id = int(id)
        try:
            material = db.select("materials", id=id)[0]
        except IndexError:
            raise web.notfound()
        # Only a material's owner or an admin can delete:
        if not (session.id == material.user_id or session.privilege == 2):
            raise web.notfound()

        filetype = material.type
        db.delete_material(id)
        delete_file(create_path(id) + "." + filetype)
        raise web.seeother("/")


class Materials:
    @csrf_protected
    def GET(self):
        """Returns an html snippet containing materials in table rows."""
        sorts = {"NEW": "materials.date_added desc",
                 "HOT": "materials.comments desc",
                 "TOP": "materials.points desc"}
        faculties = ["HUM", "IT", "JSBE", "EDU", "SPORT",
                     "SCIENCE", "YTK", "KIELI", "MUU"]

        query = web.input(query="").query
        key = web.input(key="").key
        user_id = web.input(user_id="").user_id
        course_id = web.input(course_id="").course_id

        if query:
            materials = db.get_materials(search=query, limit=30)
        elif key:
            if key in sorts:
                materials = db.get_materials(order_by=sorts[key], limit=30)
            elif key in faculties:
                materials = db.get_materials(faculty=key, limit=30)
        elif user_id:
            materials = db.get_materials(user_id=user_id, limit=30)
        elif course_id:
            materials = db.get_materials(course_id=course_id, limit=30)
        else:
            materials = None

        render = create_render(session.privilege, base=False)
        return render.list_all(materials)


class Material:
    @csrf_protected
    def GET(self, id):
        """Returns an HTML snippet containing a material and its comments."""
        id = int(id)

        material = db.get_materials(id=id)[0]
        comments = db.get_comments(material_id=id)

        render = create_render(session.privilege, base=False)
        return render.list_single(material, comments)

    @csrf_protected
    def POST(self, id):
        """Add a comment to a material. Returns an error message string if
        fails, otherwise an empty string."""
        if session.privilege < 1:
            return "Kirjaudu sisään kommentoidaksesi."

        comment = web.input().comment

        if len(comment) > 300:
            return "Kommentin maksimipituus on 300 merkkiä"
        db.add_comment(comment, session.id, int(id))
        return ""

if __name__ == "__main__":
    app.run()
