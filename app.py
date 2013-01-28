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
import zipfile
import datetime
import urllib2
import json

### INITIALIZATION ###

urls = (
  "/", "Index",
  "/login", "Login",
  "/logout", "Logout",
  "/courses", "Courses",           # Load courses for the index course cloud
  "/register", "Register",
  "/confirm", "SendConfirmation",
  "/confirm/(.*)", "Confirm",
  "/add", "Add",
  "/add/(\d+)", "Upload",
  "/download/(\d+)", "Download",
  "/like", "Like",
  "/delete/(\d+)", "Delete",
  "/materials", "Materials",
  "/materials/(\d+)", "Material",
  "/timezone", "SetTimezone"
)

UPLOAD_DIR = os.path.join(".", "uploads")
# These files are allowed (contents of zipped files will be checked):
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

store = web.session.DiskStore("sessions")
app = web.application(urls, globals())
db = models.DatabaseHandler()

# Every user will have a unique session object:
if web.config.get("_session") is None:
    initializer = {"login": 0, "privilege": 0, "user": None,
                   "id": None, "timezone": None}
    session = web.session.Session(app, store, initializer)
    web.config._session = session
else:
    session = web.config._session


### PAGES ###

class Download():
    def GET(self, id):
        """Serves a file."""
        material = db.select("materials", id=int(id))[0]
        path = create_path(id) + "." + material.type
        if not os.path.exists(path):
            raise web.notfound()  # TODO!!
        # web.header("Content-Disposition", "attachment; filename=%s" % path.split("\\")[-1])
        web.header("Content-Type", material.type)  # TODO tyyppi!
        web.header('Transfer-Encoding', 'chunked')
        f = open(path, 'rb')
        while 1:
            buf = f.read(1024 * 2)
            if not buf:
                f.close()
                break
            yield buf


class Upload:
    def GET(self, id):
        """Renders a form for adding a new material."""
        try:
            course = db.select("courses", id=id)[0]
        except:
            return "404"  # TODO
        error = web.input(error="").error
        title = web.input(title="Materiaalin nimi").title
        description = web.input(description="").description
        tags = web.input(tags="").tags

        for param in [title, description, tags]:
            param = urldecode(param)

        render = create_render(session.privilege)
        return render.upload(id=id, code=course.code, course_title=course.title,
            error=error, material_title=title, description=description, tags=tags)

    def POST(self, id):
        """Validates material submission form, adds a new material entry and
        uploads the corresponding file."""
        course_id = int(id)
        title = web.input().title.strip().capitalize()
        tags = " ".join([tag[:30] for tag in web.input().tags.split(",")[:5]])
        description = web.input().description.strip().capitalize()
        if len(description) > 300:
            description = description[:300] + "..."

        # Create the URL that the user is redirected to if the form is invalid:
        redirect_url = lambda error: ("/add/%d?error=%s&title=%s&description=%s&tags=%s"
            % (course_id, error, urlencode(title), urlencode(description), urlencode(tags)))

        if re.match(r"^.{4,40}$", title) == None:  # TODO parempi regex?
            raise web.seeother(redirect_url("bad_title"))

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
                    db.delete("materials", material_id)
                    raise web.seeother(redirect_url("bad_filetype"))

                # Upload file:
                fout = open(path, "wb")
                fout.write(file_to_upload.file.read())
                fout.close()

                # If file is zipped, check contents:
                if filetype == "zip" and not is_valid_zip(path):
                    db.delete("materials", material_id)
                    delete_file(path)
                    raise web.seeother(redirect_url("bad_zip"))

                # Update file size and type to database:
                size = os.path.getsize(path) / 1024
                db.update("materials", material_id, type=filetype, size=size)
            else:
                db.delete("materials", material_id)
                return "upload epäonnistui; ei löydetty tiedostoa?"  # TODO
            raise web.seeother("/")
        except ValueError:  # File is too large.
            db.delete("materials", material_id)
            delete_file(path)
            raise web.seeother(redirect_url("bad_filesize"))


class Like:
    def GET(self):
        """'Likes' a material, i.e. inreases it's points by one and adds
        the material's id to user's 'liked' column. Returns current points if
        succeed, otherwise an empty string."""
        id = web.input(id=None).id
        if not id or session.privilege < 1:
            return ""

        user = db.select("users", id=session.id)[0]
        material = db.select("materials", id=int(id))[0]
        points_given = db.select("users", id=session.id)[0].points_given

        # Don't like if user has already liked this material or owns the material:
        if points_given and id in points_given.split(" ") or material.user_id == user.id:
            return ""

        points = db.like_material(material_id=int(id), user_id=session.id)
        return str(points)


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
        if re.match(r"^[A-Z0-9]{5}\d{2}$", code) == None:
            raise web.seeother("add?error=bad_code")
        title = re.sub(" +", " ", title)  # Remove multiple spaces from title.
        if re.match(r"^.{1,50}$", title) == None:  # TODO parempi regex?
            raise web.seeother("/add?error=bad_title")
        if not faculty in ["HUM", "IT", "JSBE", "EDU", "SPORT",
                           "SCIENCE", "YTK", "KIELI", "MUU"]:
            raise web.seeother("/add?error=bad_faculty")

        # Information is valid, add course to database:
        id = db.insert("courses", code=code, title=title, faculty=faculty)
        # Redirect to material submission page:
        raise web.seeother("/add/" + str(id))


class Confirm:
    def GET(self, conf_code):
        """Renders a page with a button for account verification
        and another for account deletion."""
        try:
            user = db.select("users", conf_code=conf_code)[0]
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
        try:
            db.update("users", session.id, privilege=1)
        except Exception, e:
            return e  # TODO!!
        path = web.ctx.env.get("HTTP_REFERER", "/")
        if path != "/":
            path += "?activated=1"
        raise web.seeother(path)


class SendConfirmation:
    def GET(self):
        """Renders a form for user's email."""
        user = db.select("users", id=session.id).list()
        if not user:
            return "404"  # TODO
        error = web.input(error=None).error
        email_sent = web.input(email_sent=None).email_sent
        render = create_render(session.privilege)
        return render.send_confirm_email(error, email_sent)

    def POST(self):
        """Sends confirmation email to given address."""
        email = web.input(email="").email
        try:
            user = db.select("users", id=session.id)[0]
        except IndexError:
            return "Käyttäjää ei löytynyt"  # TODO

        email_re = r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,4}$"
        if re.match(email_re, email, re.IGNORECASE) == None:  # Invalid email.
            raise web.seeother("/confirm?error=bad_email")

        conf_code = user.conf_code
        conf_url = "http://%s:8080/confirm/%s" % (socket.gethostbyname(socket.gethostname()), str(conf_code))  # TODO
        subject = "Kurssimateriaalit - Aktivoi käyttäjätilisi"
        message = u"""Aktivoi käyttäjätilisi '%s' osoitteessa %s

                  Spämmiä? Ei hätää; käyttäjätilin poistaminen onnistuu saman
                  osoitteen kautta""" % (user.name, conf_url)

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

        username_re = r"[A-ZÅÄÖ0-9]{4,20}"
        password_re = r"^(?=.*\d)(?=.*[a-zåäö])(?=.*[A-ZÅÄÖ])[0-9a-zöäåA-ZÅÄÖ!@#%]{8,80}$"

        validators = [
            ((lambda n, p1, p2: not n or not p1 or not p2), "empty_reg_fields"),
            ((lambda n, p1, p2: p1 != p2), "bad_match"),
            ((lambda n, p1, p2: re.match(username_re, n, re.IGNORECASE) == None), "bad_reg_username"),
            ((lambda n, p1, p2: re.match(password_re, p1) == None), "bad_reg_password"),
            ((lambda n, p1, p2: db.select("users", name=n).list()), "username_taken")
        ]

        for (f, msg) in validators:
            if f(name, passwd1, passwd2):
                raise web.seeother("/register?error=%s&username=%s" % (msg, name))

        # Input validated, add user to database:
        salt = unicode(uuid.uuid4().hex)
        hash = unicode(hashlib.sha256(passwd1.encode("utf-8") + salt).hexdigest())
        conf_code = unicode(hashlib.md5(uuid.uuid4().hex + name.encode("utf-8")).hexdigest())
        print db.db.ctx.db.text_factory
        id = db.insert("users", name=name, hash=hash, salt=salt,
            conf_code=conf_code, privilege=0)

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
            ident = db.select("users", name=name)[0]
        except IndexError:  # Username not found.
            return web.seeother("/register?error=bad_login&username=%s" % name)

        try:
            # Login OK:
            if hashlib.sha256(passwd.encode("utf-8") + str(ident.salt)).hexdigest() == ident.hash:
                session.login = 1
                session.privilege = ident.privilege
                session.user = ident.name
                session.id = ident.id
                # Update user's last login date:
                date = str(datetime.date.today())
                db.update("users", ident.id, last_login=date)

                raise web.seeother("/")
            # Wrong password:
            else:
                session.login = 0
                session.privilege = 0
                return web.seeother("/register?error=bad_login&username=%s" % name)
        except Exception, e:
            return e  # TODO 404 page


class Courses:
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
        material = db.select("materials", id=id)[0]
        filetype = material.type
        if session.id != material.user_id:
            return "not your material"  # TODO

        db.delete_material(id)
        delete_file(create_path(id) + "." + filetype)
        raise web.seeother("/")


class Materials:
    def GET(self):
        """Returns an html snippet containing materials in table rows."""
        import time
        time.sleep(1)
        # Check for CSRF: (XMLHttpRequest doesn't allow you to make an AJAX
        # request to a third party domain)
        if web.ctx.env.get("HTTP_X_REQUESTED_WITH") != "XMLHttpRequest":
            return "possible csrf"  # TODO

        sorts = {"NEW": "materials.date_added desc",
                 "HOT": "materials.comments desc",
                 "TOP": "materials.points desc"}
        faculties = ["HUM", "IT", "JSBE", "EDU", "SPORT",
                     "SCIENCE", "YTK", "KIELI", "MUU"]

        query = web.input(query="").query
        key = web.input(key="").key
        user_id = web.input(user_id="").user_id
        course_id = web.input(course_id="").course_id

        if query:  # TODO query min. length?
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
    def GET(self, id):
        """Returns an html snippet containing a material and its comments."""
        import time
        time.sleep(1)

        id = int(id)

        if web.ctx.env.get("HTTP_X_REQUESTED_WITH") != "XMLHttpRequest":
            return "csrf"  # TODO

        material = db.get_materials(id=id)[0]
        comments = db.get_comments(material_id=id)

        render = create_render(session.privilege, base=False)
        return render.list_single(material, comments)

    def POST(self, id):
        """Add a comment to a material. Returns an error message string if
        fails, otherwise an empty string."""
        if session.privilege < 1:
            return "not signed in"  # TODO
        if web.ctx.env.get("HTTP_X_REQUESTED_WITH") != "XMLHttpRequest":
            return "possible csrf"  # TODO

        comment = web.input().comment

        if len(comment) > 300:
            return "Kommentin maksimipituus on 300 merkkiä"
        db.add_comment(comment, session.id, int(id))
        return ""


class Index:
    def GET(self):
        """Index page with lists of newest and most popular materials."""
        render = create_render(session.privilege)
        return render.index()


class SetTimezone():
    def POST(self):
        """Stores user's timezone offset to the session object."""
        offset = web.input(offset=None).offset
        if offset:
            offset = int(offset) / 60 * -1
        session.timezone = offset


class Logout:
    """Kill the session."""
    def POST(self):
        path = web.ctx.env.get("HTTP_REFERER", "/")  # Previous page or index.
        session.login = 0
        session.kill()
        raise web.seeother(path)


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


def urlencode(url):
    return urllib2.quote(url.encode("utf-8")) if url else ""


def urldecode(url):
    return urllib2.unquote(url) if url else ""


def create_render(privilege, base=True):
    """Create a render object based on user's privilege; different privileges
    use different HTML templates."""
    my_globals = {"session": session,
                  "format_date": format_date,
                  "format_size": format_size,
                  "format_time": format_time}

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


### TEMPLATE FUNCTIONS ###


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

if __name__ == "__main__":
    app.run()
